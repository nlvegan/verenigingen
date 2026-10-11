# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt

"""
Coverage-focused real-DB integration tests for the Chapter Join Request controller.

These exercise the approve/reject workflows, the error-swallowing notification /
history helpers, on_submit, and the module-level whitelisted API functions
(run as Administrator). They complement the behavioural tests in
test_chapter_join_request.py.
"""

import unittest

import frappe
from frappe.utils import getdate, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.chapter_join_request.chapter_join_request import (
    approve_join_request,
    bulk_approve_requests,
    get_chapter_join_requests,
    get_member_chapter_join_requests,
    has_chapter_approval_permission,
    reject_join_request,
)


class TestChapterJoinRequestCoverage(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

        self.test_member = self.create_test_member(
            first_name="Cover", last_name="Member", birth_date="1990-01-01", status="Active"
        )
        self.test_member2 = self.create_test_member(
            first_name="Coverb", last_name="Member", birth_date="1988-01-01", status="Active"
        )
        self.test_member3 = self.create_test_member(
            first_name="Coverc", last_name="Member", birth_date="1987-01-01", status="Active"
        )

        self.test_chapter = self.factory.ensure_test_chapter(
            "Coverage Chapter",
            {
                "status": "Active",
                "published": 1,
                "introduction": "Chapter for coverage tests",
                "contact_email": self.factory.generate_test_email("cov_chapter"),
            },
        )
        # Clear stray members from previous (non-rolled-back) chapter state.
        chapter = frappe.get_doc("Chapter", self.test_chapter.name)
        chapter.members = []
        chapter.save()

    # ----- helpers -----------------------------------------------------------

    def _make_request(self, member, submit=True):
        req = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": member.name,
                "chapter": self.test_chapter.name,
                "introduction": f"Coverage request introduction for {member.name}",
            }
        )
        req.insert()
        if submit:
            req.submit()
        return req

    def _chapter_member_exists(self, member):
        return frappe.db.exists("Chapter Member", {"parent": self.test_chapter.name, "member": member.name})

    # ----- approve_request ---------------------------------------------------

    def test_approve_request_success_creates_membership(self):
        """approve_request on a Pending request flips status, creates the Chapter Member,
        and returns the documented success dict."""
        req = self._make_request(self.test_member)
        self.assertEqual(req.status, "Pending")
        self.assertFalse(self._chapter_member_exists(self.test_member))

        result = req.approve_request(approved_by="Administrator", notes="Looks good")

        self.assertTrue(result["success"])
        self.assertIn("notification_sent", result)
        self.assertEqual(result["message"], "Request approved successfully")

        req.reload()
        self.assertEqual(req.status, "Approved")
        self.assertEqual(req.reviewed_by, "Administrator")
        self.assertEqual(getdate(req.review_date), getdate(today()))
        self.assertEqual(req.review_notes, "Looks good")
        # Membership and history side effects.
        self.assertTrue(self._chapter_member_exists(self.test_member))

    def test_approve_request_defaults_reviewer_to_session_user(self):
        """When approved_by is omitted, reviewed_by falls back to the session user."""
        req = self._make_request(self.test_member2)
        result = req.approve_request()
        self.assertTrue(result["success"])
        req.reload()
        self.assertEqual(req.reviewed_by, "Administrator")
        self.assertEqual(req.status, "Approved")

    def test_approve_request_rejects_non_pending(self):
        """The 'Only pending requests can be approved' guard fires for an already-approved
        request and does not create a second membership."""
        req = self._make_request(self.test_member3)
        req.approve_request()
        self.assertTrue(self._chapter_member_exists(self.test_member3))
        count_before = frappe.db.count(
            "Chapter Member", {"parent": self.test_chapter.name, "member": self.test_member3.name}
        )

        with self.assertRaises(frappe.ValidationError):
            req.approve_request()

        count_after = frappe.db.count(
            "Chapter Member", {"parent": self.test_chapter.name, "member": self.test_member3.name}
        )
        self.assertEqual(count_before, count_after)

    # ----- reject_request ----------------------------------------------------

    def test_reject_request_success_no_membership(self):
        """reject_request flips status to Rejected, records the reason, and creates no
        Chapter Member."""
        req = self._make_request(self.test_member)

        result = req.reject_request(rejected_by="Administrator", reason="Not a fit")

        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "Request rejected successfully")
        req.reload()
        self.assertEqual(req.status, "Rejected")
        self.assertEqual(req.reviewed_by, "Administrator")
        self.assertEqual(getdate(req.review_date), getdate(today()))
        self.assertEqual(req.rejection_reason, "Not a fit")
        self.assertFalse(self._chapter_member_exists(self.test_member))

    def test_reject_request_defaults_reviewer_to_session_user(self):
        req = self._make_request(self.test_member2)
        result = req.reject_request(reason="No reason given session default")
        self.assertTrue(result["success"])
        req.reload()
        self.assertEqual(req.reviewed_by, "Administrator")

    def test_reject_request_rejects_non_pending(self):
        """The 'Only pending requests can be rejected' guard fires once not Pending."""
        req = self._make_request(self.test_member3)
        req.reject_request(reason="first rejection")
        req.reload()
        self.assertEqual(req.status, "Rejected")

        with self.assertRaises(frappe.ValidationError):
            req.reject_request(reason="second rejection")

    # ----- on_submit / notify_chapter_board ----------------------------------

    def test_on_submit_triggers_board_notification(self):
        """Submitting a request runs on_submit -> notify_chapter_board without error and
        leaves the request submitted in Pending state."""
        req = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.test_member.name,
                "chapter": self.test_chapter.name,
                "introduction": "on_submit board notification coverage",
            }
        )
        req.insert()
        with self.assertNoErrorLog():
            req.submit()
        self.assertEqual(req.docstatus, 1)
        self.assertEqual(req.status, "Pending")

    def test_notify_chapter_board_with_board_member(self):
        """notify_chapter_board collects board-member recipients and sends without raising
        even when a real board member is present."""
        # Create a volunteer linked to a member and add as active board member.
        volunteer = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": "Board Vol Coverage",
                "member": self.test_member2.name,
                "email": self.factory.generate_test_email("boardvol"),
                "status": "Active",
            }
        )
        volunteer.insert()
        self.track_doc("Volunteer", volunteer.name)

        board_role = self.factory.ensure_chapter_role("Coverage Board Role", {"permissions_level": "Admin"})

        chapter = frappe.get_doc("Chapter", self.test_chapter.name)
        chapter.append(
            "board_members",
            {
                "volunteer": volunteer.name,
                "volunteer_name": volunteer.volunteer_name,
                "chapter_role": board_role.name,
                "is_active": 1,
                "from_date": today(),
            },
        )
        chapter.save()

        req = self._make_request(self.test_member, submit=False)
        with self.assertNoErrorLog():
            req.notify_chapter_board()

    # ----- direct notify / history helpers -----------------------------------

    def test_notify_member_approved_runs(self):
        req = self._make_request(self.test_member, submit=False)
        with self.assertNoErrorLog():
            req.notify_member_approved()

    def test_notify_member_rejected_runs_with_reason(self):
        req = self._make_request(self.test_member, submit=False)
        req.rejection_reason = "Coverage reason text"
        with self.assertNoErrorLog():
            req.notify_member_rejected()

    def test_add_membership_history_runs(self):
        """add_membership_history records a history entry for the member without raising."""
        req = self._make_request(self.test_member, submit=False)
        with self.assertNoErrorLog():
            req.add_membership_history()

    # ----- has_chapter_approval_permission -----------------------------------

    def test_has_chapter_approval_permission_admin_true(self):
        """Administrator (Verenigingen Administrator role) returns True for any chapter."""
        self.assertTrue(has_chapter_approval_permission(self.test_chapter.name))

    def test_has_chapter_approval_permission_no_chapter_false(self):
        """No chapter argument returns False (form-load guard) rather than raising."""
        self.assertFalse(has_chapter_approval_permission(None))
        self.assertFalse(has_chapter_approval_permission(""))

    # ----- whitelisted API wrappers ------------------------------------------

    def test_approve_join_request_api_success(self):
        req = self._make_request(self.test_member)
        result = approve_join_request(req.name, notes="api approve")
        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "Chapter join request approved successfully")
        req.reload()
        self.assertEqual(req.status, "Approved")
        self.assertTrue(self._chapter_member_exists(self.test_member))

    def test_approve_join_request_api_bad_name_returns_error(self):
        """A non-existent request returns the swallowed-error dict and logs an Error."""
        self.expectErrorLog("Failed to approve join request")
        result = approve_join_request("CJR-DOES-NOT-EXIST-0001")
        self.assertFalse(result["success"])
        self.assertIn("error", result)

    def test_reject_join_request_api_success(self):
        req = self._make_request(self.test_member2)
        result = reject_join_request(req.name, reason="api reject")
        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "Chapter join request rejected")
        req.reload()
        self.assertEqual(req.status, "Rejected")
        self.assertEqual(req.rejection_reason, "api reject")
        self.assertFalse(self._chapter_member_exists(self.test_member2))

    def test_reject_join_request_api_bad_name_returns_error(self):
        self.expectErrorLog("Failed to reject join request")
        result = reject_join_request("CJR-DOES-NOT-EXIST-0002")
        self.assertFalse(result["success"])
        self.assertIn("error", result)

    def test_get_member_chapter_join_requests(self):
        """Returns submitted requests for the member with the documented field set."""
        req = self._make_request(self.test_member)  # submitted (docstatus 1)
        rows = get_member_chapter_join_requests(self.test_member.name)
        names = [r["name"] for r in rows]
        self.assertIn(req.name, names)
        row = next(r for r in rows if r["name"] == req.name)
        self.assertEqual(row["chapter"], self.test_chapter.name)
        self.assertEqual(row["status"], "Pending")

    def test_get_member_chapter_join_requests_empty_for_unknown(self):
        rows = get_member_chapter_join_requests("Nonexistent-Member-XYZ")
        self.assertEqual(rows, [])

    def test_get_chapter_join_requests_includes_can_approve_flag(self):
        """Returns submitted requests for the chapter, each annotated with can_approve
        (True for Administrator)."""
        req = self._make_request(self.test_member3)
        rows = get_chapter_join_requests(self.test_chapter.name)
        names = [r["name"] for r in rows]
        self.assertIn(req.name, names)
        row = next(r for r in rows if r["name"] == req.name)
        self.assertEqual(row["member"], self.test_member3.name)
        self.assertTrue(row["can_approve"])

    def test_bulk_approve_requests_success(self):
        """bulk_approve_requests approves several pending requests and reports the count."""
        req_a = self._make_request(self.test_member)
        req_b = self._make_request(self.test_member2)

        message = bulk_approve_requests([req_a.name, req_b.name])

        self.assertIn("Successfully approved 2 request(s)", message)
        req_a.reload()
        req_b.reload()
        self.assertEqual(req_a.status, "Approved")
        self.assertEqual(req_b.status, "Approved")
        self.assertTrue(self._chapter_member_exists(self.test_member))
        self.assertTrue(self._chapter_member_exists(self.test_member2))

    def test_bulk_approve_requests_reports_failures(self):
        """A bad name in the batch is collected into the failed list while valid ones
        still approve."""
        req_ok = self._make_request(self.test_member3)
        message = bulk_approve_requests([req_ok.name, "CJR-BOGUS-NAME-0003"])

        self.assertIn("Successfully approved 1 request(s)", message)
        self.assertIn("Failed requests", message)
        self.assertIn("CJR-BOGUS-NAME-0003", message)
        req_ok.reload()
        self.assertEqual(req_ok.status, "Approved")

    # ----- failure reason surfaced to the approver (#1591) -------------------

    def _approval_error(self, req):
        """Approve through the real controller and return the thrown message."""
        with self.assertRaises(frappe.ValidationError) as ctx:
            req.approve_request()
        return str(ctx.exception)

    def test_approve_already_member_surfaces_the_real_reason(self):
        """#1591: a request approved after the member joined the chapter by another
        route must say the member is already in the chapter, not 'Unknown error'.

        Real flow: the request is submitted while the member has no row (the
        validators refuse otherwise), then the member is added via
        ChapterMembershipManager, then the request is approved.
        """
        from verenigingen.services.chapter.chapter_membership_manager import ChapterMembershipManager

        req = self._make_request(self.test_member)
        joined = ChapterMembershipManager.assign_member_to_chapter(
            member_id=self.test_member.name, chapter_name=self.test_chapter.name, notify=False
        )
        self.assertTrue(joined["success"], joined)

        message = self._approval_error(req)

        self.assertNotIn("Unknown error", message)
        self.assertIn("already in this chapter", message)

    def _suspended_member_with_disabled_row_and_request(self, member):
        """Return a pending request for `member`, whose row is disabled and who is Suspended.

        Real writers throughout: the row is created by ChapterMembershipManager,
        disabled by the termination writer (disable_chapter_memberships_safe), and the
        member is suspended by suspend_member_safe. No db.set_value.
        """
        from verenigingen.services.chapter.chapter_membership_manager import ChapterMembershipManager
        from verenigingen.services.termination.termination_integration import (
            disable_chapter_memberships_safe,
            suspend_member_safe,
        )

        req = self._make_request(member)
        ChapterMembershipManager.assign_member_to_chapter(
            member_id=member.name, chapter_name=self.test_chapter.name, notify=False
        )
        disable_chapter_memberships_safe(member.name, today(), "join request test")
        suspend_member_safe(member.name, "join request test", suspend_user=False)
        self.assertEqual(frappe.db.get_value("Member", member.name, "status"), "Suspended")
        row = frappe.db.get_value(
            "Chapter Member",
            {"parent": self.test_chapter.name, "member": member.name},
            ["enabled", "status"],
            as_dict=True,
        )
        self.assertEqual((row.enabled, row.status), (0, "Inactive"))
        return req

    def test_approve_not_reenabled_member_surfaces_the_real_reason(self):
        """#1591/#1564: a disabled row whose member is currently Suspended is refused by
        add_member with action 'not_reenabled'; an approver who can read the Member must
        see why, status included."""
        req = self._suspended_member_with_disabled_row_and_request(self.test_member2)

        message = self._approval_error(req)

        self.assertNotIn("Unknown error", message)
        self.assertIn("was not re-enabled", message)
        self.assertIn("Suspended", message)

    def test_approve_not_reenabled_does_not_disclose_status_to_unreadable_member(self):
        """#1590: surfacing the not_reenabled message must not WIDEN what the approver
        can learn. A board approver who fails has_permission(Member, read) on the target
        (its row is disabled) gets the refusal WITHOUT the member's status.

        Probe shortcut: approve_request is called directly as the board user; over HTTP
        approve_join_request is @critical_api, which a Chapter-Board-only profile does
        not clear (#1590), so this models a board seat held by a user who does.
        """
        board = self.create_test_board_member(self.test_chapter.name)
        req = self._suspended_member_with_disabled_row_and_request(self.test_member2)
        # Control: the approver really cannot read this Member, and the reason is real.
        self.assertFalse(frappe.has_permission("Member", "read", doc=self.test_member2.name, user=board.user))

        approver_before = frappe.session.user
        frappe.set_user(board.user)
        try:
            message = self._approval_error(req)
        finally:
            frappe.set_user(approver_before)

        self.assertNotIn("Unknown error", message)
        self.assertIn("could not be re-enabled", message)
        self.assertNotIn("Suspended", message)
        self.assertNotIn(self.test_member2.name, message)


if __name__ == "__main__":
    unittest.main()
