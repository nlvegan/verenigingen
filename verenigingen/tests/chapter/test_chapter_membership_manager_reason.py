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
