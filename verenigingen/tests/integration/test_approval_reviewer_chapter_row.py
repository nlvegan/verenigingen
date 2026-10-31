# -*- coding: utf-8 -*-
"""#1797: a chapter picked by the REVIEWER at approval must leave the approved member enabled there.

approve_membership_application used to assign the reviewer's chapter BEFORE the Member's status
flipped from Pending to Active. add_member's new-row branch derives the row from the Member's
current status, so the row came out enabled=0 / Inactive, and _activate_pending_chapter_memberships
(which only touches 'Pending' rows) never fixed it: an Active member, invisible in their chapter.

Every test drives the real flow: submit_application as Guest, then approve_membership_application
as Administrator. No field is set directly.
"""

import json

import frappe

from verenigingen.api.membership_application import submit_application
from verenigingen.api.membership_application_review import approve_membership_application
from verenigingen.tests.backend.unit.api.test_membership_application_coverage import (
    _ensure_test_membership_type,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestReviewerChosenChapterRowAtApproval(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        from verenigingen.tests.setup import ensure_member_test_masters

        ensure_member_test_masters()
        self.membership_type = _ensure_test_membership_type()

    def _apply_as_guest(self, **overrides):
        data = {
            "first_name": "Reviewer",
            "last_name": f"Chapter{frappe.generate_hash(length=6)}",
            "email": f"rc-{frappe.generate_hash(length=8)}@example.com",
            "birth_date": "1990-01-01",
            "address_line1": "1 Test Street",
            "city": "Amsterdam",
            # Outside every chapter's postal range a test creates, so no chapter is SUGGESTED;
            # the precondition assertions below check that rather than trusting it.
            "postal_code": "9999ZZ",
            "country": "Netherlands",
            "selected_membership_type": self.membership_type,
        }
        data.update(overrides)
        frappe.set_user("Guest")
        self.addCleanup(frappe.set_user, "Administrator")
        result = submit_application(**data)
        frappe.set_user("Administrator")
        self.assertTrue(result["success"], msg=json.dumps(result, default=str))
        member = result["data"]["member_record"]
        self.track_doc("Member", member)
        return member

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
        """A chapter the assignment refuses (here: one that does not exist; approval checks
        the member and the caller's chapter permission, not the chapter's existence) leaves
        the member approved with no row. That used to be reported only through
        frappe.logger().warning, which nobody reads; it must reach the Error Log."""
        ghost = f"No Such Chapter {frappe.generate_hash(length=6)}"
        member = self._apply_as_guest()
        self.expectErrorLog(ASSIGNMENT_FAILURE_TITLE)  # silences tearDown; the assert below checks
        start = frappe.utils.now()

        with self.assertErrorLog(ASSIGNMENT_FAILURE_TITLE):
            self._approve(member, ghost)

        self.assertEqual(self._rows(member), {})
        failures = self._assignment_failures_since(start)
        self.assertEqual(len(failures), 1, msg=str(failures))
        self.assertIn(ghost, failures[0].error)
        self.assertIn(member, failures[0].error)


ASSIGNMENT_FAILURE_TITLE = "Approval Chapter Assignment Failed"
