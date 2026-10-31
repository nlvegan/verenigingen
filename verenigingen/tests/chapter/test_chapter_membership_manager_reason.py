"""#1631: ChapterMembershipManager failure results carry the reason under BOTH keys.

add_member/remove_member failures are keyed "message"; the manager's own early exits
are keyed "error". Callers reading only "error" lost the reason (#1591 siblings).
"""

import frappe
from frappe.utils import today

from verenigingen.services.chapter.chapter_membership_manager import ChapterMembershipManager
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestChapterMembershipManagerReason(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self.member = self.create_test_member(
            first_name="Reason", last_name="Member", birth_date="1990-01-01", status="Active"
        )
        self.chapter = self.factory.ensure_test_chapter(
            "Reason Chapter",
            {
                "status": "Active",
                "published": 1,
                "introduction": "Chapter for #1631",
                "contact_email": self.factory.generate_test_email("reason_chapter"),
            },
        )
        chapter = frappe.get_doc("Chapter", self.chapter.name)
        chapter.members = []
        chapter.save()
        self.other_chapter = self.factory.ensure_test_chapter(
            "Reason Chapter Two",
            {
                "status": "Active",
                "published": 1,
                "introduction": "Second chapter for #1631",
                "contact_email": self.factory.generate_test_email("reason_chapter2"),
            },
        )

    def _assign(self, chapter=None):
        return ChapterMembershipManager.assign_member_to_chapter(
            member_id=self.member.name, chapter_name=(chapter or self.chapter).name, notify=False
        )

    def _suspended_with_disabled_row(self):
        """Real writers: manager creates the row, termination disables it, suspend_member_safe suspends."""
        from verenigingen.services.termination.termination_integration import (
            disable_chapter_memberships_safe,
            suspend_member_safe,
        )

        self.assertTrue(self._assign()["success"])
        disable_chapter_memberships_safe(self.member.name, today(), "#1631 test")
        suspend_member_safe(self.member.name, "#1631 test", suspend_user=False)
        self.assertEqual(frappe.db.get_value("Member", self.member.name, "status"), "Suspended")

    def test_assign_already_member_populates_error(self):
        self.assertTrue(self._assign()["success"])
        result = self._assign()
        self.assertFalse(result["success"])
        self.assertIn("already in this chapter", result.get("error") or "")
        self.assertEqual(result["action"], "already_exists")

    def test_leave_when_not_in_chapter_populates_error(self):
        result = ChapterMembershipManager.leave_chapter(
            member_id=self.member.name, chapter_name=self.chapter.name
        )
        self.assertFalse(result["success"])
        self.assertIn("not in this chapter", result.get("error") or "")

    def test_transfer_reports_leave_reason(self):
        result = ChapterMembershipManager.transfer_member_between_chapters(
            self.member.name, self.chapter.name, self.other_chapter.name
        )
        self.assertFalse(result["success"])
        self.assertNotIn("None", result["error"])
        self.assertIn("not in this chapter", result["error"])

    def test_transfer_reports_join_reason(self):
        """Leave succeeds, join is refused as already_exists (member already in the target)."""
        self.assertTrue(self._assign()["success"])
        self.assertTrue(self._assign(self.other_chapter)["success"])
        result = ChapterMembershipManager.transfer_member_between_chapters(
            self.member.name, self.chapter.name, self.other_chapter.name
        )
        self.assertFalse(result["success"])
        self.assertNotIn("None", result["error"])
        self.assertIn("already in this chapter", result["error"])

    # --- transfer: a refused join must not strand the member (#1846) ---
    def _rows(self):
        """Every Chapter Member row of the member: the state leave_chapter writes."""
        return [
            dict(r)
            for r in frappe.get_all(
                "Chapter Member",
                filters={"member": self.member.name},
                fields=["parent", "enabled", "leave_reason", "status"],
                order_by="parent asc, name asc",
            )
        ]

    def _suspended_member_in_source(self):
        """Real writers: manager assigns, suspend_member_safe suspends. Returns the pre-transfer rows."""
        from verenigingen.services.termination.termination_integration import suspend_member_safe

        self.assertTrue(self._assign()["success"])
        suspend_member_safe(self.member.name, "#1846 test", suspend_user=False)
        self.assertEqual(frappe.db.get_value("Member", self.member.name, "status"), "Suspended")
        before = self._rows()
        # Control: the source row is enabled, which is what a stranding would destroy.
        self.assertTrue(any(r["enabled"] and r["parent"] == self.chapter.name for r in before), before)
        return before

    def _transfer(self):
        return ChapterMembershipManager.transfer_member_between_chapters(
            self.member.name, self.chapter.name, self.other_chapter.name
        )

    def test_transfer_refused_join_leaves_the_member_in_the_source_chapter(self):
        """#1846: Suspended member's first add to the target is refused (added_disabled)."""
        before = self._suspended_member_in_source()

        result = self._transfer()

        self.assertFalse(result["success"], result)
        self.assertIn("Failed to join", result["error"])
        self.assertEqual(self._rows(), before)

    def test_transfer_not_reenabled_refusal_leaves_the_member_in_the_source_chapter(self):
        """#1846/#1564: the target holds a disabled row that add_member will not re-enable."""
        from verenigingen.services.termination.termination_integration import suspend_member_safe

        self.assertTrue(self._assign()["success"])
        self.assertTrue(self._assign(self.other_chapter)["success"])
        other = frappe.get_doc("Chapter", self.other_chapter.name)
        other.member_manager.remove_member(self.member.name, permanent=False)
        suspend_member_safe(self.member.name, "#1846 test", suspend_user=False)
        before = self._rows()
        # Controls: the target row is DISABLED (not_reenabled shape), the source is enabled.
        self.assertTrue(any(not r["enabled"] and r["parent"] == self.other_chapter.name for r in before))
        self.assertTrue(any(r["enabled"] and r["parent"] == self.chapter.name for r in before))

        result = self._transfer()

        self.assertFalse(result["success"], result)
        self.assertIn("not re-enabled", result["error"])
        self.assertEqual(self._rows(), before)

    def test_transfer_join_that_raises_leaves_the_member_in_the_source_chapter(self):
        """#1846: the fail-closed path: the join raising must not leave the leave applied."""
        from unittest.mock import patch

        self.assertTrue(self._assign()["success"])
        before = self._rows()
        self.expectErrorLog("ChapterMembershipManager")

        # Mock justified: forces the join to raise, which no real input reliably does.
        with patch.object(
            ChapterMembershipManager, "assign_member_to_chapter", side_effect=frappe.ValidationError("boom")
        ):
            result = self._transfer()

        self.assertFalse(result["success"], result)
        self.assertEqual(self._rows(), before)

    def test_transfer_refused_leave_rolls_back_the_disabled_source_row(self):
        """#1846: remove_member saves the row disabled BEFORE the history write; leave_chapter
        swallows that write's failure into success False, so the leave itself must be undone."""
        from unittest.mock import patch

        from verenigingen.utils.chapter_membership_history_manager import ChapterMembershipHistoryManager

        self.assertTrue(self._assign()["success"])
        before = self._rows()
        self.expectErrorLog("ChapterMembershipManager")

        # Mock justified: fault injection after the row was saved disabled.
        with patch.object(
            ChapterMembershipHistoryManager,
            "terminate_chapter_membership",
            side_effect=frappe.ValidationError("hist"),
        ):
            result = self._transfer()

        self.assertFalse(result["success"], result)
        self.assertIn("Failed to leave", result["error"])
        self.assertEqual(self._rows(), before)

    def test_transfer_lock_timeout_rolls_back_then_propagates(self):
        """#1846: a 1205 keeps the transaction alive, so the leave is undone before it propagates."""
        from unittest.mock import patch

        self.assertTrue(self._assign()["success"])
        before = self._rows()

        # Mock justified: infrastructure fault injection at the join.
        with patch.object(
            ChapterMembershipManager, "assign_member_to_chapter", side_effect=frappe.QueryTimeoutError("lock")
        ):
            with self.assertRaises(frappe.QueryTimeoutError):
                self._transfer()

        self.assertEqual(self._rows(), before)

    def test_transfer_deadlock_propagates_unchanged(self):
        """#1846: a 1213 destroys the savepoint; the guard must re-raise the deadlock, not a 1305."""
        from unittest.mock import patch

        self.assertTrue(self._assign()["success"])

        # Mock justified: infrastructure fault injection at the join.
        with patch.object(
            ChapterMembershipManager, "assign_member_to_chapter", side_effect=frappe.QueryDeadlockError("dl")
        ):
            with self.assertRaises(frappe.QueryDeadlockError):
                self._transfer()

    def test_transfer_of_an_active_member_still_moves_the_row(self):
        """Control: a real transfer still leaves the source and joins the target."""
        self.assertTrue(self._assign()["success"])

        result = self._transfer()

        self.assertTrue(result["success"], result)
        enabled = {r["parent"] for r in self._rows() if r["enabled"]}
        self.assertEqual(enabled, {self.other_chapter.name})

    def test_roster_helper_logs_the_reason(self):
        from verenigingen.api.member_management import add_member_to_chapter_roster

        self.expectErrorLog("Chapter Roster Update Error")
        self.assertTrue(self._assign()["success"])
        add_member_to_chapter_roster(self.member.name, self.chapter.name)
        logged = frappe.get_all(
            "Error Log",
            filters={"error": ["like", "%already in this chapter%"]},
            fields=["name"],
            limit=1,
        )
        self.assertTrue(logged, "Error Log carries no reason for the refused roster add")

    def test_not_reenabled_reason_names_status_for_a_reader(self):
        """Control: someone who can read the Member gets the real reason, status included."""
        self._suspended_with_disabled_row()
        result = self._assign()
        self.assertEqual(result["action"], "not_reenabled")
        self.assertIn("Suspended", result.get("error") or "")

    def test_not_reenabled_withholds_status_from_unreadable_member(self):
        """#1590: both keys are scrubbed for a caller who fails has_permission(Member, read)."""
        board = self.create_test_board_member(self.chapter.name)
        self._suspended_with_disabled_row()
        caller_before = frappe.session.user
        frappe.set_user(board.user)
        try:
            self.assertFalse(frappe.has_permission("Member", "read", doc=self.member.name))
            result = self._assign()
        finally:
            frappe.set_user(caller_before)
        self.assertEqual(result["action"], "not_reenabled")
        for key in ("error", "message"):
            self.assertIn("could not be re-enabled", result.get(key) or "", key)
            self.assertNotIn("Suspended", result[key])
