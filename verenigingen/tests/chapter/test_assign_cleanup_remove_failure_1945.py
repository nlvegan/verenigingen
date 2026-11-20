"""#1945: the staff move must not half-record when the old chapter cannot be saved.

``ChapterAssignmentService._cleanup_chapter_memberships`` used to fall back to
``frappe.db.set_value("Chapter Member", ..., "enabled", 0)`` whenever
``Chapter.remove_member`` raised. The fallback skips the termination history, the
"Member left" mail to the source board and the permission/validation refusal that
made ``remove_member`` raise. Measured on test_site_5, each of these raises left the
source row ``enabled=0, status='Active'`` with the member's history still Active:

* the source chapter fails its own validation (legacy data) -> ValidationError;
* a Verenigingen Administrator (role only) moves a member out of the National
  Board chapter -> PermissionError, a deliberate refusal;
* a lock wait timeout (1205) -> QueryTimeoutError, which the surrounding code
  propagates everywhere else (#561).

Real flows throughout (the real move, real ``remove_member``). Two probe shortcuts,
stated here: the invalid chapter data is written with ``db.set_value`` (that is how
legacy invalid data exists; the validator itself refuses to save it), and the lock
timeout is injected with a patch because a real one needs a second committed
connection (infrastructure fault injection, not a business input).
"""

from unittest.mock import patch

import frappe

from verenigingen.services.chapter.chapter_membership_manager import ChapterMembershipManager
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.constants import Roles

BAD_POSTAL = "9999-1000"  # reversed range: Chapter.validate refuses it


class TestAssignCleanupRemoveFailure1945(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        suffix = frappe.generate_hash(length=6)
        self.source = self.ensure_test_chapter(f"Test 1945 Source {suffix}")
        self.target = self.ensure_test_chapter(f"Test 1945 Target {suffix}")
        self.member = self.create_test_member(first_name="Move", last_name=f"Out{suffix}")
        ChapterMembershipManager.assign_member_to_chapter(
            member_id=self.member.name, chapter_name=self.source.name, notify=False
        )

    def _svc(self):
        from verenigingen.services.chapter.chapter_assignment_service import get_chapter_assignment_service

        return get_chapter_assignment_service()

    def _rows(self):
        return {
            r.parent: (r.enabled, r.leave_reason)
            for r in frappe.get_all(
                "Chapter Member", filters={"member": self.member.name}, fields=["parent", "enabled", "leave_reason"]
            )
        }

    def _history(self, chapter):
        return frappe.get_all(
            "Chapter Membership History",
            filters={"parent": self.member.name, "chapter_name": chapter},
            pluck="status",
        )

    def _board_mail(self):
        return frappe.get_all(
            "Email Queue", filters={"reference_doctype": "Chapter", "reference_name": self.source.name}, pluck="name"
        )

    def _assert_untouched(self, result):
        self.assertFalse(result["success"], result)
        self.assertTrue(result["message"], "the refusal must say why")
        self.assertEqual(self._rows(), {self.source.name: (1, None)})
        self.assertEqual(self._history(self.source.name), ["Active"])

    def test_control_valid_source_move_records_row_and_history(self):
        """Control: a valid source chapter is left through the full path (history Quit)."""
        result = self._svc().assign_with_cleanup(self.member.name, self.target.name)

        self.assertTrue(result["success"], result)
        rows = self._rows()
        self.assertEqual(rows[self.source.name][0], 0)
        self.assertEqual(rows[self.target.name][0], 1)
        self.assertEqual(self._history(self.source.name), ["Quit"])

    def test_source_chapter_failing_validation_fails_the_move(self):
        frappe.db.set_value("Chapter", self.source.name, "postal_codes", BAD_POSTAL)

        self.expectErrorLog("Failed to remove member", "Range start 9999")
        result = self._svc().assign_with_cleanup(self.member.name, self.target.name)

        self._assert_untouched(result)
        self.assertIn(self.source.name, result["message"])

    def test_va_cannot_move_a_member_out_of_the_national_board_chapter(self):
        user = self.create_test_user_with_roles(roles=[Roles.VERENIGINGEN_ADMIN])
        user_name = user.name if hasattr(user, "name") else user
        original = frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter")
        frappe.db.set_single_value("Verenigingen Settings", "national_board_chapter", self.source.name)
        self.addCleanup(
            frappe.db.set_single_value, "Verenigingen Settings", "national_board_chapter", original
        )

        self.expectErrorLog("Failed to remove member", "Secure Operation Failed")
        self.addCleanup(frappe.set_user, "Administrator")
        frappe.set_user(user_name)
        result = self._svc().assign_with_cleanup(self.member.name, self.target.name)

        self._assert_untouched(result)
        self.assertIn("National Board", result["message"])

    def test_lock_timeout_on_the_old_chapter_propagates_and_rolls_back(self):
        # Mock justified: infrastructure fault injection; a real 1205 needs a second
        # committed connection holding the Chapter row.
        with patch(
            "verenigingen.verenigingen.doctype.chapter.chapter.Chapter.remove_member",
            side_effect=frappe.QueryTimeoutError("lock-1945"),
        ):
            with self.assertRaises(frappe.QueryTimeoutError):
                self._svc().assign_with_cleanup(self.member.name, self.target.name)

        self.assertEqual(self._rows(), {self.source.name: (1, None)})

    def test_failed_move_produces_exactly_one_message_with_a_reason(self):
        """The caller sees one message, and a PermissionError with no text still says why."""
        user = self.create_test_user_with_roles(roles=[Roles.VERENIGINGEN_ADMIN])
        user_name = user.name if hasattr(user, "name") else user
        original = frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter")
        frappe.db.set_single_value("Verenigingen Settings", "national_board_chapter", self.source.name)
        self.addCleanup(
            frappe.db.set_single_value, "Verenigingen Settings", "national_board_chapter", original
        )
        self.expectErrorLog("Failed to remove member", "Secure Operation Failed")
        self.addCleanup(frappe.set_user, "Administrator")
        frappe.set_user(user_name)
        before = len(frappe.local.message_log)

        # Call the cleanup directly: assign_with_cleanup turns the raise into a dict.
        with self.assertRaises(frappe.ValidationError) as ctx:
            self._svc()._cleanup_chapter_memberships(self.member.name, self.target.name)

        self.assertEqual(len(frappe.local.message_log) - before, 1, frappe.local.message_log[before:])
        self.assertIn("National Board", str(ctx.exception))

    def test_mijnrood_sync_reports_a_failed_move_as_a_message_and_keeps_the_old_chapter(self):
        """Pins the sync behaviour (#1945 review): no raise, a message, the old chapter kept (the alert is #2199's)."""
        from unittest.mock import MagicMock

        from verenigingen.mijnrood_sync.services.event_application.related_records_orchestrator import (
            get_related_records_orchestrator,
        )

        division_id = 7000000 + int(frappe.generate_hash(length=4), 16) % 900000
        frappe.db.set_value("Chapter", self.target.name, "mijnrood_division_id", division_id)
        frappe.db.set_value("Chapter", self.source.name, "postal_codes", BAD_POSTAL)
        self.expectErrorLog("Failed to remove member", "Range start 9999")
        event = MagicMock()
        event.name = "EVT-1945"

        message = get_related_records_orchestrator()._assign_chapter_from_division(
            self.member.name, division_id, event
        )

        self.assertTrue(message.startswith("Chapter assignment failed:"), message)
        self.assertEqual(self._rows(), {self.source.name: (1, None)})
        self.assertEqual(self._history(self.source.name), ["Active"])
