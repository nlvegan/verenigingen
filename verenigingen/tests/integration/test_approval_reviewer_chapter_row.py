# -*- coding: utf-8 -*-
"""#1797: a chapter picked by the REVIEWER at approval must leave the approved member enabled there.

approve_membership_application used to assign the reviewer's chapter BEFORE the Member's status
flipped from Pending to Active. add_member's new-row branch derives the row from the Member's
current status, so the row came out enabled=0 / Inactive, and _activate_pending_chapter_memberships
(which only touches 'Pending' rows) never fixed it: an Active member, invisible in their chapter.

Every test drives the real flow: submit_application as Guest, then approve_membership_application
as Administrator. No field is set directly.
"""

from unittest.mock import patch

import frappe

from verenigingen.api.membership_application_review import approve_membership_application
from verenigingen.tests.backend.unit.api.test_membership_application_coverage import (
    _ensure_test_membership_type,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.utils.guest_application import submit_application_as_guest

ASSIGNMENT_FAILURE_TITLE = "Approval Chapter Assignment Failed"


class TestReviewerChosenChapterRowAtApproval(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        from verenigingen.tests.setup import ensure_member_test_masters

        ensure_member_test_masters()
        self.membership_type = _ensure_test_membership_type()

    def _apply_as_guest(self, **overrides):
        return submit_application_as_guest(self, self.membership_type, **overrides)

    def _rows(self, member):
        return {
            r.parent: (r.enabled, r.status)
            for r in frappe.get_all(
                "Chapter Member", filters={"member": member}, fields=["parent", "enabled", "status"]
            )
        }

    def _approve(self, member, chapter):
        approve_membership_application(
            member_name=member, membership_type=self.membership_type, chapter=chapter
        )
        self.assertEqual(frappe.db.get_value("Member", member, "status"), "Active")

    def test_reviewer_chapter_for_applicant_without_one_is_enabled(self):
        chapter = self.create_test_chapter(published=1)
        member = self._apply_as_guest()
        self.assertEqual(self._rows(member), {}, "precondition: no chapter row before approval")

        self._approve(member, chapter.name)

        self.assertEqual(self._rows(member), {chapter.name: (1, "Active")})
        # The assignment reported success, so the tracking fields are written again.
        self.assertEqual(
            frappe.db.get_value("Member", member, "chapter_change_reason"), "Membership application approval"
        )

    def test_reviewer_overriding_the_applicants_chapter_enables_both_rows(self):
        chosen = self.create_test_chapter(published=1)
        picked = self.create_test_chapter(published=1)
        member = self._apply_as_guest(selected_chapter=chosen.name)
        self.assertEqual(self._rows(member), {chosen.name: (1, "Pending")}, "precondition")

        self._approve(member, picked.name)

        self.assertEqual(self._rows(member), {chosen.name: (1, "Active"), picked.name: (1, "Active")})

    def test_approving_with_the_applicants_own_chapter_keeps_one_active_row(self):
        """Control: the path #1797 found already working must keep working (no duplicate row,
        the Pending row is the one activated)."""
        chosen = self.create_test_chapter(published=1)
        member = self._apply_as_guest(selected_chapter=chosen.name)

        start = frappe.utils.now()
        self._approve(member, chosen.name)

        self.assertEqual(self._rows(member), {chosen.name: (1, "Active")})
        # The assignment answers already_exists here (the row is the applicant's own); that is
        # benign, so it must not be logged as a failure on every ordinary approval.
        self.assertEqual(self._assignment_failures_since(start), [])

    def _assignment_failures_since(self, start):
        return frappe.get_all(
            "Error Log",
            filters={"creation": [">=", start], "method": ASSIGNMENT_FAILURE_TITLE},
            fields=["name", "error"],
        )

    def test_an_assignment_the_approval_could_not_make_is_logged(self):
        """A non-success from the assignment (other than the benign already_exists) is logged to
        the Error Log rather than only to frappe.logger(). Since #1860 an approval naming a
        nonexistent chapter is refused before this point, so the non-success is injected at the
        collaborator boundary (Mock justified: fault injection), like the except-branch test below."""
        from verenigingen.api.membership_application_review import assign_member_to_chapter

        member = frappe._dict(name=f"MEM-{frappe.generate_hash(length=6)}")
        self.expectErrorLog(ASSIGNMENT_FAILURE_TITLE)
        start = frappe.utils.now()
        target = (
            "verenigingen.services.chapter.chapter_membership_manager."
            "ChapterMembershipManager.assign_member_to_chapter"
        )
        refused = {"success": False, "error": "refused-1797", "action": "added_disabled"}
        with self.assertErrorLog(ASSIGNMENT_FAILURE_TITLE):
            with patch(target, return_value=refused):  # Mock justified: fault injection
                assign_member_to_chapter(member, "Some Chapter")

        failures = self._assignment_failures_since(start)
        self.assertEqual(len(failures), 1, msg=str(failures))
        self.assertIn("refused-1797", failures[0].error)
        self.assertIn(member.name, failures[0].error)

    def test_an_assignment_that_raises_is_logged_and_the_approval_wrapper_survives(self):
        """The wrapper's except branch: the manager is the collaborator, so stubbing it to raise
        is a boundary fault, not mocked business logic (Mock justified: fault injection)."""
        from verenigingen.api.membership_application_review import assign_member_to_chapter

        member = frappe._dict(name=f"MEM-{frappe.generate_hash(length=6)}")
        self.expectErrorLog(ASSIGNMENT_FAILURE_TITLE)
        start = frappe.utils.now()
        target = (
            "verenigingen.services.chapter.chapter_membership_manager."
            "ChapterMembershipManager.assign_member_to_chapter"
        )
        with self.assertErrorLog(ASSIGNMENT_FAILURE_TITLE):
            with patch(target, side_effect=RuntimeError("boom-1797")):  # Mock justified: fault injection
                assign_member_to_chapter(member, "Some Chapter")

        failures = self._assignment_failures_since(start)
        self.assertEqual(len(failures), 1, msg=str(failures))
        self.assertIn(member.name, failures[0].error)
        self.assertIn("boom-1797", failures[0].error)

    def test_a_board_member_approver_can_approve_into_their_own_chapter(self):
        """Regression found via #1860: the post-activation chapter step (#1797) re-saved the
        Member, and a non-admin board-member approver may write a PENDING applicant but not an
        ACTIVE member, so the approval raised PermissionError after the member was already Active.
        All other tests here run as Administrator, which hid it."""
        chapter = self.create_test_chapter(published=1)
        board = self.create_test_board_member(chapter.name)
        member = self._apply_as_guest(selected_chapter=chapter.name)

        with self.set_user(board.user):
            approve_membership_application(
                member_name=member, membership_type=self.membership_type, chapter=chapter.name
            )

        self.assertEqual(frappe.db.get_value("Member", member, "status"), "Active")
        self.assertEqual(self._rows(member), {chapter.name: (1, "Active")})
        self.assertEqual(frappe.db.get_value("Member", member, "current_chapter"), chapter.name)
