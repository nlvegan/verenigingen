# Copyright (c) 2026, Veganisme.org and contributors
# For license information, please see license.txt

"""
#1639: a member approved while the Account Creation Request queue REFUSED the
account must leave a trace and tell the reviewer.

The refusal is real, not mocked: an earlier Failed ACR with retries left makes
``queue_account_creation_for_member`` refuse ("already exists") while the
service's own pre-check (Pending / In Progress / Completed only) lets the call
through. The ACR is inserted and its status set with ``db.set_value`` (probe
shortcut: it stands in for a queue job that failed; the refusal path itself
is the real queue function).
"""

import frappe

from verenigingen.api.membership_application_review import (
    _build_approval_response,
    _create_user_account_safe,
)
from verenigingen.events.subscribers.approval_subscribers import handle_user_account_creation
from verenigingen.services.member.account.member_user_account_service import (
    create_secure_user_account_for_member,
)
from verenigingen.tests.utils.base import VereningingenTestCase

REFUSED_TITLE = "Account Creation Queue Refused"


class TestAcrQueueRefusalRecorded(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.h = frappe.generate_hash(length=6)
        self.member = self.create_test_member(
            first_name="AcrRefuse",
            last_name=f"Member{self.h}",
            email=f"acrrefuse.{self.h}@test.invalid",
            status="Active",
        )
        self.failed_request = self._make_failed_acr()

    def _make_failed_acr(self):
        request = frappe.get_doc(
            {
                "doctype": "Account Creation Request",
                "request_type": "Member",
                "source_record": self.member.name,
                "email": self.member.email,
                "full_name": self.member.full_name,
                "role_profile": "Verenigingen Member",
                "business_justification": "test",
                "requested_roles": [{"role": "Verenigingen Member"}],
            }
        )
        request.insert()
        self.track_doc("Account Creation Request", request.name)
        frappe.db.set_value("Account Creation Request", request.name, "status", "Failed")
        return request.name

    def _refusal_logs(self):
        # Error Log is MyISAM (survives rollback) and member names repeat across runs, so key on
        # this test's own ACR name.
        return frappe.get_all(
            "Error Log",
            filters={"method": REFUSED_TITLE, "error": ["like", f"%{self.failed_request}%"]},
            pluck="error",
        )

    def test_service_refusal_is_failure_with_code_and_error_log(self):
        self.expectErrorLog(REFUSED_TITLE)
        with self.assertErrorLog(REFUSED_TITLE):
            result = create_secure_user_account_for_member(self.member)

        self.assertFalse(result.get("success"), msg=result)
        self.assertEqual((result.get("meta") or {}).get("action"), "queue_failed")
        self.assertEqual((result.get("error") or {}).get("code"), "ACR_QUEUE_REFUSED")
        logs = self._refusal_logs()
        self.assertEqual(len(logs), 1)
        self.assertIn(self.member.name, logs[0])

    def test_subscriber_records_the_refusal(self):
        self.expectErrorLog(REFUSED_TITLE)
        with self.assertErrorLog(REFUSED_TITLE):
            result = handle_user_account_creation("member_approval_initiated", {"member": self.member.name})

        self.assertFalse(result.get("success"))
        self.assertEqual(len(self._refusal_logs()), 1)

    def test_review_endpoint_helpers_surface_reason_without_rolling_back(self):
        self.expectErrorLog(REFUSED_TITLE)
        with self.assertErrorLog(REFUSED_TITLE):
            user_result = _create_user_account_safe(self.member, False)
        invoice = frappe._dict(name="INV-1639")
        response = _build_approval_response(self.member, invoice, 10, user_result)

        # Approval itself still succeeds (existing contract)...
        self.assertTrue(response["success"])
        self.assertEqual(response["user_account_status"], "failed")
        # ...but the reviewer is told why, and it is machine-readable.
        self.assertIn("already exists", response["message"])
        self.assertEqual(response["user_account_error_code"], "ACR_QUEUE_REFUSED")
        self.assertEqual(len(self._refusal_logs()), 1)

    def test_control_success_path_logs_nothing_and_has_no_error(self):
        """Control: a member with no earlier ACR queues cleanly; nothing is logged."""
        frappe.db.set_value("Account Creation Request", self.failed_request, "status", "Cancelled")
        with self.assertNoErrorLog():
            result = create_secure_user_account_for_member(self.member)
        self.assertTrue(result.get("success"), msg=result)
        self.assertEqual((result.get("meta") or {}).get("action"), "queued_secure")
        self.track_doc("Account Creation Request", (result.get("meta") or {}).get("account_request"))
        response = _build_approval_response(self.member, frappe._dict(name="INV"), 10, result)
        self.assertNotEqual(response["user_account_status"], "failed")
        self.assertNotIn("Reason:", response["message"])
        self.assertNotIn("user_account_error_code", response)
