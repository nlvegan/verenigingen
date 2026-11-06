"""#2064: approval activates ONLY the Pending Chapter Member row of the chapter the application named.

A Member can hold a Pending row for a chapter that is NOT the application's: an Active member who asks to
join a chapter (request_to_join) gets a Pending row that chapter's board has yet to decide, and rows written
before #2021 (join_chapter did not look at Member.status) can sit on a member who later applies. Approving
the application must not also approve that request behind its board's back.

Measured while writing this: a REAL termination turns the Pending row Inactive/enabled=0, so
"request, quit, reapply" does not reach the sweep (test_terminated_members_old_request_stays_inactive is
that control). No current writer is known to produce the state, so the red tests seed it:
PROBE SHORTCUT, stated: the stale row is written with create_pending_chapter_membership (the writer
materialise_member uses) AFTER the real termination, standing in for a pre-#2021 row. Everything else is
the real flow: submit_application -> confirm -> approve_application. The direct tests call
`_activate_pending_chapter_memberships` itself.
"""

import frappe
from frappe.utils import today

from verenigingen.api.membership_application_review import _activate_pending_chapter_memberships
from verenigingen.tests.integration.test_application_record_approval import ApprovalCase
from verenigingen.tests.support.termination_request import execute_real_termination
from verenigingen.utils.application_helpers import create_pending_chapter_membership


def _applied_chapter_row_state(chapter, member):
    return frappe.db.get_value(
        "Chapter Member", {"parent": chapter, "member": member}, ["status", "enabled"], as_dict=True
    )


class TestApprovalActivatesAppliedChapterOnly(ApprovalCase):
    def setUp(self):
        super().setUp()
        self.old_chapter = self.factory.ensure_test_chapter(
            f"Test Old Chapter {frappe.generate_hash(length=6)}", {"short_name": "OLD", "country": "Netherlands"}
        )

    def _quit_member(self):
        member = self.create_test_member(email=self.email)
        execute_real_termination(self, member.name, today())
        self.assertEqual(frappe.db.get_value("Member", member.name, "status"), "Quit", "premise")
        return member

    def test_reapplication_does_not_activate_a_pending_row_in_another_chapter(self):
        member = self._quit_member()
        create_pending_chapter_membership(member, self.old_chapter.name)  # probe shortcut, see docstring
        self.assertEqual(_applied_chapter_row_state(self.old_chapter.name, member.name).status, "Pending", "premise")
        name = self._stage_and_confirm()  # names self.chapter

        result = self._approve_as(name)

        self.assertTrue(result["success"], result)
        self.assertEqual(frappe.db.get_value("Member", member.name, "status"), "Active", "control")
        self.assertEqual(_applied_chapter_row_state(self.chapter.name, member.name).status, "Active", "the applied chapter")
        self.assertEqual(
            _applied_chapter_row_state(self.old_chapter.name, member.name).status,
            "Pending",
            "the other chapter's undecided request stays Pending",
        )

    def test_terminated_members_old_request_stays_inactive(self):
        """Control, real flow: request_to_join, quit (the termination inactivates the row), reapply."""
        from verenigingen.verenigingen.doctype.chapter.managers.member_manager import MemberManager

        member = self.create_test_member(email=self.email)
        old = frappe.get_doc("Chapter", self.old_chapter.name)
        result = MemberManager(old).request_to_join(member.name, introduction="please", notify=False)
        self.assertTrue(result.get("success"), result)
        self.assertEqual(_applied_chapter_row_state(self.old_chapter.name, member.name).status, "Pending", "premise")
        execute_real_termination(self, member.name, today())
        name = self._stage_and_confirm()

        self.assertTrue(self._approve_as(name)["success"])

        self.assertEqual(_applied_chapter_row_state(self.old_chapter.name, member.name).status, "Inactive")
        self.assertEqual(_applied_chapter_row_state(self.chapter.name, member.name).status, "Active")

    def test_helper_activates_only_the_named_chapter(self):
        member = self.create_test_member(email=self.email, status="Pending", application_status="Pending")
        create_pending_chapter_membership(member, self.chapter.name)
        create_pending_chapter_membership(member, self.old_chapter.name)

        _activate_pending_chapter_memberships(member, self.chapter.name)

        self.assertEqual(_applied_chapter_row_state(self.chapter.name, member.name).status, "Active")
        self.assertEqual(_applied_chapter_row_state(self.old_chapter.name, member.name).status, "Pending")

    def test_helper_with_no_applied_chapter_activates_nothing(self):
        member = self.create_test_member(email=self.email, status="Pending", application_status="Pending")
        create_pending_chapter_membership(member, self.old_chapter.name)

        _activate_pending_chapter_memberships(member, None)

        self.assertEqual(_applied_chapter_row_state(self.old_chapter.name, member.name).status, "Pending")
