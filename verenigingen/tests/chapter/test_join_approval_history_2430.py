"""#2430: approving a chapter join request must move the member's Chapter Membership History
entry from Pending to Active (it stayed Pending: add_membership_history refuses Active beside a
Pending entry and the caller ignored the False).

Flows are real: the applicant asks through `request_to_join` / `join_chapter`, and a REAL
least-privileged board member (Admin seat, no System Manager) approves through the dashboard
endpoint `quick_approve_join_request`, which calls `MemberManager.approve_member_request`.
PROBE SHORTCUT: the "legacy" test deletes the history rows with `frappe.db.delete` to stand in
for a site where the request never wrote one.
"""

import frappe
from frappe.utils import getdate, today

from verenigingen.api.chapter_dashboard_api import quick_approve_join_request
from verenigingen.setup.role_profile_setup import assign_role_profile_to_user
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.chapter.chapter import join_chapter, leave_chapter


class TestJoinApprovalHistory2430(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter(
            chapter_name=f"TEST 2430 Chapter {frappe.generate_hash()[:6]}", region="Test Region 2430"
        )
        self.board = self.create_test_board_member(
            self.chapter.name, permissions_level="Admin", role_name="Chapter Head"
        )
        self.applicant = self._active_member("Applicant")

    def _active_member(self, last_name):
        email = f"jh2430-{frappe.generate_hash()[:8]}0@example.com"
        member = self.create_test_member(
            first_name="Jh", last_name=last_name, email=email, birth_date="1990-01-01"
        )
        member.db_set("status", "Active")
        self.create_test_user_with_roles(email=email, roles=["Verenigingen Member"])
        member.db_set("user", email)
        assign_role_profile_to_user(email, "Verenigingen Chapter Board Member")
        member.user_email = email
        return member

    def _request(self, chapter_name=None):
        manager = frappe.get_doc("Chapter", chapter_name or self.chapter.name).member_manager
        result = manager.request_to_join(self.applicant.name, notify=False)
        self.assertTrue(result["success"], result)

    def _approve(self, chapter_name=None):
        with self.as_user(self.board.user):
            self.assertNotIn("System Manager", frappe.get_roles())
            # The dashboard's own Member audit comment is refused for a board user (separate defect,
            # logged by the endpoint); it does not affect the history under test.
            self.expectErrorLog()
            return quick_approve_join_request(self.applicant.name, chapter_name or self.chapter.name)

    def _history(self, chapter_name=None):
        return frappe.get_all(
            "Chapter Membership History",
            filters={
                "parent": self.applicant.name,
                "chapter_name": chapter_name or self.chapter.name,
                "assignment_type": "Member",
            },
            fields=["status", "start_date", "end_date", "reason"],
            order_by="idx asc",
        )

    def _row(self, chapter_name=None):
        return frappe.get_all(
            "Chapter Member",
            filters={"parent": chapter_name or self.chapter.name, "member": self.applicant.name},
            fields=["status", "enabled"],
        )

    def test_first_time_join_approval_activates_the_history_entry(self):
        self._request()
        self.assertEqual([h.status for h in self._history()], ["Pending"])

        result = self._approve()

        self.assertTrue(result["success"], result)
        self.assertEqual([(r.status, r.enabled) for r in self._row()], [("Active", 1)])
        history = self._history()
        self.assertEqual([h.status for h in history], ["Active"], history)
        self.assertEqual(history[0].start_date, getdate(today()))
        self.assertIsNone(history[0].end_date)

    def test_rejoin_approval_activates_the_new_entry_and_keeps_the_earlier_period(self):
        self.add_member_to_test_chapter(self.applicant.name, self.chapter.name)
        with self.as_user(self.applicant.user_email):
            self.assertTrue(leave_chapter(self.applicant.name, self.chapter.name, "moving")["removed"])
            self.assertTrue(join_chapter(self.applicant.name, self.chapter.name, "back")["success"])
        before = self._history()
        self.assertEqual(before[-1].status, "Pending", before)

        self.assertTrue(self._approve()["success"])

        self.assertEqual([(r.status, r.enabled) for r in self._row()], [("Active", 1)])
        after = self._history()
        self.assertEqual(len(after), len(before), after)
        self.assertEqual(after[-1].status, "Active", after)
        ended = [h for h in after if h.status == "Quit"]
        self.assertEqual([(h.reason) for h in ended], ["moving"], after)

    def test_approval_activates_only_the_approved_chapters_entry(self):
        """Control: a Pending request in a second chapter keeps its Pending entry."""
        other = self.create_test_chapter(
            chapter_name=f"TEST 2430 Other {frappe.generate_hash()[:6]}", region=self.chapter.region
        )
        self._request()
        self._request(other.name)

        self.assertTrue(self._approve()["success"])

        self.assertEqual([h.status for h in self._history()], ["Active"])
        self.assertEqual([h.status for h in self._history(other.name)], ["Pending"])
        self.assertEqual([(r.status, r.enabled) for r in self._row(other.name)], [("Pending", 1)])

    def test_approval_without_a_pending_entry_still_records_an_active_one(self):
        """Legacy: the request wrote no history; approval must still leave exactly one Active entry."""
        self._request()
        frappe.db.delete(
            "Chapter Membership History", {"parent": self.applicant.name, "chapter_name": self.chapter.name}
        )

        self.assertTrue(self._approve()["success"])

        self.assertEqual([h.status for h in self._history()], ["Active"])
