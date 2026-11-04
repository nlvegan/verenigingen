"""An Active Member whose application_status was never written may not reapply (#1989).

A Member's application_status is a Select with no default, so Frappe fills its first option, "Pending", for
every Member that never had it written: MijnRood-imported members (update_member_fields does not set it) and
most fixtures. _handle_existing_member used to answer "update" for that "Pending" before it looked at the
status, so such a member's email was staged as a Pending Review application, and approving it overwrote the
Active member's name and IBAN and reset member_since (measured on test_site_3 before the fix).

No probe shortcuts for the member under test: create_test_member leaves application_status at the field
default, which is what an imported member has. Where a db write stands in for a flow, the test says so.
"""

import json
from unittest.mock import patch

import frappe

from verenigingen.api.membership_application import _handle_existing_member, submit_application
from verenigingen.api.membership_application_review import approve_application
from verenigingen.tests.services.event_application.test_application_sync_service import (
    SUBMISSION,
    MijnRoodApplicationCase,
)


class TestActiveMemberCannotReapply(MijnRoodApplicationCase):
    def _imported_active_member(self):
        member = self.create_test_member(email=self.email)
        # The state under test, read back rather than assumed: Active, application_status the field default.
        state = frappe.db.get_value("Member", member.name, ["status", "application_status"], as_dict=True)
        self.assertEqual((state.status, state.application_status), ("Active", "Pending"))
        return member

    def test_mijnrood_application_is_not_staged(self):
        member = self._imported_active_member()
        event = self._sync_event("New", "admin_membership_application", self._application_row())

        result = self._apply_sync_event(event)

        self.assertTrue(result["success"], result)
        self.assertEqual(frappe.db.count(SUBMISSION, {"email": self.email}), 0)
        self.assertEqual(frappe.db.get_value("MijnRood Sync Event", event, "linked_member"), member.name)

    def test_web_form_application_is_not_staged(self):
        self._imported_active_member()
        self._request_from_fresh_ip()
        previous = frappe.session.user
        frappe.set_user("Guest")
        try:
            # Mock justified: External Service - SMTP delivery, not business logic
            with patch("frappe.sendmail"):
                response = submit_application(**self._full_form_data())
        finally:
            frappe.set_user(previous)

        self.assertTrue(response["success"], response)  # the same answer as for any email
        self.assertEqual(frappe.db.count(SUBMISSION, {"email": self.email}), 0)

    def test_application_staged_before_the_import_cannot_be_approved_by_a_board_member(self):
        """Staged while no Member existed (real flow), then the Member arrives as an import does. The
        approval gate must refuse, and the Member must be exactly as it was."""
        _application, name = self._stage()
        member = self._imported_active_member()
        member.db_set("member_since", "2019-03-04")  # fixture: an imported member has a join date
        before = frappe.db.get_value(
            "Member", member.name, ["first_name", "last_name", "iban", "member_since", "status"], as_dict=True
        )
        board = self.create_test_board_member(self.chapter.name, permissions_level="Admin")

        with self.as_user(board.user.name if hasattr(board.user, "name") else board.user):
            # Mock justified: External Service - SMTP delivery, not business logic
            with patch("frappe.sendmail"), self.assertRaises(frappe.ValidationError) as caught:
                approve_application(name, create_invoice=False)

        self.assertIn("cannot be approved in its current state", str(caught.exception))
        after = frappe.db.get_value(
            "Member", member.name, ["first_name", "last_name", "iban", "member_since", "status"], as_dict=True
        )
        self.assertEqual(after, before)
        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "status"), "Pending Review")
        self.assertEqual(frappe.db.count("Membership", {"member": member.name}), 0)


class TestHandleExistingMemberActiveFirst(MijnRoodApplicationCase):
    def _existing(self, status, application_status):
        return frappe._dict(name="X", status=status, application_status=application_status)

    def test_active_is_refused_whatever_the_application_status_says(self):
        for application_status in ("Pending", "Rejected", "Approved", None):
            action, error = _handle_existing_member(self._existing("Active", application_status), {})
            self.assertIsNone(action, application_status)
            self.assertIn("already_active_member", json.dumps(error.to_dict(nested=True)), application_status)

    def test_a_pending_or_rejected_member_that_is_not_active_still_reapplies(self):
        """Controls: the refusal keys on status, so a real pending/rejected applicant is untouched.
        (status given directly: the helper reads two fields, and the real writers of these states are
        _update_member and reject, which the integration suites drive.)"""
        for status, application_status in (("Pending", "Pending"), ("Rejected", "Rejected")):
            action, error = _handle_existing_member(self._existing(status, application_status), {})
            self.assertEqual(action, "update", (status, application_status))
            self.assertIsNone(error)
