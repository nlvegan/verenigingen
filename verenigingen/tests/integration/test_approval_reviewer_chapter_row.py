# -*- coding: utf-8 -*-
"""#1797: a chapter picked by the REVIEWER at approval must leave the approved member enabled there.

The approval core used to assign the reviewer's chapter BEFORE the Member's status flipped from
Pending to Active. add_member's new-row branch derives the row from the Member's current status, so
the row came out enabled=0 / Inactive, and _activate_pending_chapter_memberships (which only touches
'Pending' rows) never fixed it: an Active member, invisible in their chapter.

Driven through the real application-keyed flow (#1765): submit_application as Guest -> confirm link ->
approve_application as staff (ApprovalCase's own staging). No field is set directly. The one stub is
the fault injection in the two logging tests, named where it is used.
"""

from unittest.mock import patch

import frappe

from verenigingen.tests.integration.test_application_record_approval import SUBMISSION, ApprovalCase

ASSIGNMENT_FAILURE_TITLE = "Approval Chapter Assignment Failed"
MANAGER_ASSIGN = (
    "verenigingen.services.chapter.chapter_membership_manager."
    "ChapterMembershipManager.assign_member_to_chapter"
)


class TestReviewerChosenChapterRowAtApproval(ApprovalCase):
    def _stage_without_chapter(self):
        """An applicant who names no chapter. A city and postal code no chapter can match, so none is
        SUGGESTED either: suggest_chapter_for_member also matches on the CITY, and CI shards carry shared
        chapters such as "Test Amsterdam Chapter" (the old test used "Amsterdam" and went red in CI)."""
        application = self._stage_and_confirm(
            selected_chapter="",
            city=f"Nergenshuizen-{frappe.generate_hash(length=6)}",
            postal_code="9999ZZ",
        )
        # Check the precondition rather than trusting it.
        self.assertFalse(frappe.db.get_value(SUBMISSION, application, "chapter"))
        return application

    def _rows(self, member):
        return {
            r.parent: (r.enabled, r.status)
            for r in frappe.get_all(
                "Chapter Member", filters={"member": member}, fields=["parent", "enabled", "status"]
            )
        }

    def _approve(self, application, chapter, user=None):
        result = self._approve_as(
            application, user=user, membership_type=self.membership_type.name, chapter=chapter
        )
        self.assertTrue(result["success"], result)
        member = result["member"]
        self.track_doc("Member", member)
        self.assertEqual(frappe.db.get_value("Member", member, "status"), "Active")
        return member

    def _assignment_failures_since(self, start):
        return frappe.get_all(
            "Error Log",
            filters={"creation": [">=", start], "method": ASSIGNMENT_FAILURE_TITLE},
            fields=["name", "error"],
        )

    def test_reviewer_chapter_for_applicant_without_one_is_enabled(self):
        chapter = self.create_test_chapter(published=1)
        application = self._stage_without_chapter()

        member = self._approve(application, chapter.name)

        self.assertEqual(self._rows(member), {chapter.name: (1, "Active")})
        # The assignment reported success, so the tracking fields are written again.
        self.assertEqual(
            frappe.db.get_value("Member", member, "chapter_change_reason"), "Membership application approval"
        )

    def test_reviewer_overriding_the_applicants_chapter_enables_both_rows(self):
        """Develop's decision (#1797): the applicant's own Pending row is activated and the reviewer's
        pick is added enabled, so both rows end enabled and Active."""
        chosen = self.create_test_chapter(published=1)
        picked = self.create_test_chapter(published=1)
        application = self._stage_and_confirm(selected_chapter=chosen.name)

        member = self._approve(application, picked.name)

        self.assertEqual(self._rows(member), {chosen.name: (1, "Active"), picked.name: (1, "Active")})

    def test_approving_with_the_applicants_own_chapter_keeps_one_active_row(self):
        """Control: the path #1797 found already working must keep working (no duplicate row,
        the Pending row is the one activated)."""
        chosen = self.create_test_chapter(published=1)
        application = self._stage_and_confirm(selected_chapter=chosen.name)

        start = frappe.utils.now()
        member = self._approve(application, chosen.name)

        self.assertEqual(self._rows(member), {chosen.name: (1, "Active")})
        # The assignment answers already_exists here (the row is the applicant's own); that is
        # benign, so it must not be logged as a failure on every ordinary approval.
        self.assertEqual(self._assignment_failures_since(start), [])

    def test_an_assignment_the_approval_could_not_make_is_logged(self):
        """An assignment the manager refuses leaves the member approved with no row. That used to be
        reported only through frappe.logger().warning, which nobody reads; it must reach the Error Log.
        The refusal is injected at the manager boundary (a real chapter that refuses is not reachable
        at approval); the nonexistent-chapter case is deliberately not tested here (#1860)."""
        chapter = self.create_test_chapter(published=1)
        application = self._stage_without_chapter()
        self.expectErrorLog(ASSIGNMENT_FAILURE_TITLE)  # silences tearDown; the assert below checks
        start = frappe.utils.now()
        refusal = {"success": False, "error": "refused-1797"}

        with self.assertErrorLog(ASSIGNMENT_FAILURE_TITLE):
            # Mock justified: fault injection at the manager boundary
            with patch(MANAGER_ASSIGN, return_value=refusal):
                member = self._approve(application, chapter.name)

        self.assertEqual(self._rows(member), {})
        failures = self._assignment_failures_since(start)
        self.assertEqual(len(failures), 1, msg=str(failures))
        self.assertIn(chapter.name, failures[0].error)
        self.assertIn(member, failures[0].error)
        self.assertIn("refused-1797", failures[0].error)

    def test_an_assignment_that_raises_is_logged_and_the_approval_wrapper_survives(self):
        """The wrapper's except branch: the manager is the collaborator, so stubbing it to raise
        is a boundary fault, not mocked business logic (Mock justified: fault injection)."""
        from verenigingen.api.membership_application_review import assign_member_to_chapter

        member = frappe._dict(name=f"MEM-{frappe.generate_hash(length=6)}")
        self.expectErrorLog(ASSIGNMENT_FAILURE_TITLE)
        start = frappe.utils.now()
        with self.assertErrorLog(ASSIGNMENT_FAILURE_TITLE):
            with patch(MANAGER_ASSIGN, side_effect=RuntimeError("boom-1797")):  # Mock justified: fault injection
                assign_member_to_chapter(member, "Some Chapter")

        failures = self._assignment_failures_since(start)
        self.assertEqual(len(failures), 1, msg=str(failures))
        self.assertIn(member.name, failures[0].error)
        self.assertIn("boom-1797", failures[0].error)

    def test_a_board_member_approver_can_approve_into_their_own_chapter(self):
        """Regression found via #1860: the post-activation chapter step (#1797) re-saved the
        Member, and a non-admin board-member approver may write a PENDING applicant but not an
        ACTIVE member, so the approval raised PermissionError after the member was already Active.
        All other tests here run as an administrator, which hid it."""
        chapter = self.create_test_chapter(published=1)
        board = self.create_test_board_member(chapter.name)
        application = self._stage_and_confirm(selected_chapter=chapter.name)

        member = self._approve(application, chapter.name, user=board.user)

        self.assertEqual(self._rows(member), {chapter.name: (1, "Active")})
        self.assertEqual(frappe.db.get_value("Member", member, "current_chapter"), chapter.name)
