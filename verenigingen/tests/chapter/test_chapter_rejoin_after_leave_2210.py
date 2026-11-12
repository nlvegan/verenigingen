"""#2210: a member who left a chapter can rejoin it, on the SAME Chapter Member row.

Maintainer ruling 2026-11-11: a rejoin reactivates the member's existing row (no second row)
provided the history is kept: the earlier period and the leave/rejoin events stay recorded in
Member.chapter_membership_history.

Leave and rejoin are driven through the real whitelisted endpoints as the member's own user
(same caller profile as #2166's tests). The board's approval is `approve_member_request`
called as Administrator (probe shortcut: the dashboard API needs a seated board volunteer,
which is not what is under test; the method it calls is the same one).
"""

import frappe

from verenigingen.services.chapter.chapter_membership_manager import ChapterMembershipManager
from verenigingen.setup.role_profile_setup import assign_role_profile_to_user
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.chapter.chapter import join_chapter, leave_chapter


class TestChapterRejoinAfterLeave2210(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter(
            chapter_name=f"TEST 2210 Chapter {frappe.generate_hash()[:6]}", region="Test Region 2210"
        )
        self.me = self._member_user("Own")
        self.add_member_to_test_chapter(self.me.member.name, self.chapter.name)

    def _member_user(self, last_name):
        email = f"rj2210-{frappe.generate_hash()[:8]}@example.com"
        member = self.create_test_member(
            first_name="Rj", last_name=last_name, email=email, birth_date="1990-01-01"
        )
        member.db_set("status", "Active")
        self.create_test_user_with_roles(email=email, roles=["Verenigingen Member"])
        member.db_set("user", email)
        assign_role_profile_to_user(email, "Verenigingen Chapter Board Member")
        return frappe._dict(member=member, user=email)

    def _rows(self):
        return frappe.get_all(
            "Chapter Member",
            filters={"parent": self.chapter.name, "member": self.me.member.name},
            fields=["name", "status", "enabled", "chapter_join_date", "leave_reason"],
        )

    def _history(self):
        return frappe.get_all(
            "Chapter Membership History",
            filters={
                "parent": self.me.member.name,
                "chapter_name": self.chapter.name,
                "assignment_type": "Member",
            },
            fields=["status", "start_date", "end_date", "reason"],
            order_by="idx asc",
        )

    def _leave(self, reason="moving"):
        with self.as_user(self.me.user):
            return leave_chapter(self.me.member.name, self.chapter.name, reason)

    def _rejoin(self):
        with self.as_user(self.me.user):
            return join_chapter(self.me.member.name, self.chapter.name, "back again")

    def _approve(self):
        return frappe.get_doc("Chapter", self.chapter.name).member_manager.approve_member_request(
            self.me.member.name, approved_by="Administrator"
        )

    def test_leave_then_rejoin_reactivates_the_same_row(self):
        (original,) = self._rows()
        self.assertEqual(self._leave("moving")["removed"], True)
        left = self._rows()[0]
        self.assertEqual((left.status, left.enabled), ("Active", 0))

        response = self._rejoin()

        self.assertTrue(response["success"], response)
        (row,) = self._rows()  # exactly one row: no second row
        self.assertEqual(row.name, original.name)
        self.assertEqual((row.status, row.enabled), ("Pending", 1))
        self.assertIsNone(row.leave_reason)

    def test_board_approval_activates_the_rejoined_row(self):
        self._leave()
        self.assertTrue(self._rejoin()["success"])
        self.assertTrue(self._approve()["success"])
        (row,) = self._rows()
        self.assertEqual((row.status, row.enabled), ("Active", 1))

    def test_history_keeps_the_earlier_period_and_records_the_rejoin(self):
        self._leave("moving")
        before = self._history()
        ended = [h for h in before if h.status == "Quit"]
        self.assertEqual(len(ended), 1, before)
        self.assertEqual(ended[0].reason, "moving")

        self.assertTrue(self._rejoin()["success"])
        requested = self._history()
        self.assertEqual(len(requested), len(before) + 1, requested)
        # The entry is written by Chapter.handle_member_changes when the row flips enabled 0 -> 1.
        self.assertEqual(
            (requested[-1].status, requested[-1].reason, requested[-1].end_date),
            ("Pending", "Membership re-enabled", None),
        )
        self.assertTrue(self._approve()["success"])

        after = self._history()
        still_ended = [h for h in after if h.status == "Quit"]
        self.assertEqual(
            [(h.start_date, h.end_date, h.reason) for h in still_ended],
            [(ended[0].start_date, ended[0].end_date, "moving")],
            "the earlier period must stay recorded untouched",
        )
        self.assertEqual(len(after), len(requested), "approval adds no entry")
        # #2430: approval moves the rejoin's Pending entry to Active (it used to stay Pending).
        self.assertEqual(after[-1].status, "Active", after)
        self.assertEqual(after[-1].start_date, frappe.utils.getdate(frappe.utils.today()))

    def test_second_rejoin_after_second_leave_still_one_row(self):
        for _i in range(2):
            self._leave()
            self.assertTrue(self._rejoin()["success"])
            self.assertTrue(self._approve()["success"])
        self.assertEqual(len(self._rows()), 1)
        self.assertEqual(len([h for h in self._history() if h.status == "Quit"]), 2)

    def test_rejoin_of_an_active_member_is_still_refused(self):
        """Control: a member who has not left is told so, and nothing is written."""
        response = self._rejoin()
        self.assertFalse(response["success"])
        (row,) = self._rows()
        self.assertEqual((row.status, row.enabled), ("Active", 1))

    def test_double_rejoin_request_is_already_pending(self):
        self._leave()
        self.assertTrue(self._rejoin()["success"])
        again = frappe.get_doc("Chapter", self.chapter.name).member_manager.request_to_join(
            self.me.member.name, notify=False
        )
        self.assertEqual(again["action"], "already_pending")
        self.assertEqual(len(self._rows()), 1)

    def test_withdrawn_pending_request_can_be_requested_again(self):
        """leave on a Pending row leaves Pending+enabled=0, which must not read as 'pending'."""
        self._leave()
        self.assertTrue(self._rejoin()["success"])
        self.assertTrue(self._leave("changed my mind")["removed"])
        self.assertEqual(self._rows()[0].enabled, 0)
        self.assertTrue(self._rejoin()["success"])
        (row,) = self._rows()
        self.assertEqual((row.status, row.enabled), ("Pending", 1))

    def test_terminated_then_reinstated_member_rejoins_on_the_same_row(self):
        """Row left Inactive+enabled=0 by termination (written here as the termination integration
        writes it: probe shortcut for the termination flow); the member is Active again."""
        (original,) = self._rows()
        frappe.db.set_value(
            "Chapter Member", original.name, {"status": "Inactive", "enabled": 0, "leave_reason": "terminated"}
        )
        self.assertTrue(self._rejoin()["success"])
        (row,) = self._rows()
        self.assertEqual((row.name, row.status, row.enabled), (original.name, "Pending", 1))

    def test_non_active_member_cannot_rejoin(self):
        """#2021: the guard still precedes the reactivation; the left row is untouched."""
        self._leave()
        self.me.member.db_set("status", "Suspended")
        result = frappe.get_doc("Chapter", self.chapter.name).member_manager.request_to_join(
            self.me.member.name, notify=False
        )
        self.assertEqual(result["action"], "not_active")
        row = self._rows()[0]
        self.assertEqual((row.status, row.enabled), ("Active", 0))

    def test_rejoin_by_another_user_is_refused(self):
        other = self._member_user("Other")
        self._leave()
        with self.as_user(other.user):
            response = join_chapter(self.me.member.name, self.chapter.name, "x")
        self.assertFalse(response["success"])
        self.assertEqual(self._rows()[0].enabled, 0)

    def test_manager_internal_caller_keeps_chapter_write_check(self):
        """Control: only a proved Member.user caller is elevated; None caller as a plain user is not."""
        self._leave()
        with self.as_user(self.me.user):
            result = ChapterMembershipManager.join_chapter(
                member_id=self.me.member.name, chapter_name=self.chapter.name
            )
        self.assertFalse(result["success"], result)
        self.assertEqual(self._rows()[0].enabled, 0)
