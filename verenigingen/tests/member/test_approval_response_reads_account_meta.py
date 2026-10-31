# Copyright (c) 2026, Veganisme.org and contributors
# For license information, please see license.txt

"""
#1739: ``_build_approval_response`` / ``_create_user_account_safe`` read the account
outcome from the dict ``create_secure_user_account_for_member`` returns. That dict is
``OperationResult.to_dict()``, which nests ``action`` and ``account_request`` under
``meta``; reading them at the top level made every success branch unreachable.

Real flow, no mock of the service: the member is created, the service really queues an
Account Creation Request (or links a real User), and the response the caller receives is
asserted. No probe shortcuts except where a test says so.
"""

import frappe

from verenigingen.api.membership_application_review import (
    _build_approval_response,
    _create_user_account_safe,
)
from verenigingen.tests.utils.base import VereningingenTestCase


class TestApprovalResponseReadsAccountMeta(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.h = frappe.generate_hash(length=6)
        self.member = self.create_test_member(
            first_name="ApprMeta",
            last_name=f"Member{self.h}",
            email=f"apprmeta.{self.h}@test.invalid",
            status="Active",
        )

    def _respond(self, user_result):
        return _build_approval_response(self.member, frappe._dict(name="INV-1739"), 10, user_result)

    def test_queued_account_is_reported_with_tracking(self):
        user_result = _create_user_account_safe(self.member, False)
        acr = (user_result.get("meta") or {}).get("account_request")
        self.assertTrue(acr, msg=user_result)
        self.track_doc("Account Creation Request", acr)

        log_len = len(frappe.local.message_log)
        response = self._respond(user_result)

        self.assertEqual(response["user_account_status"], "queued", msg=response)
        self.assertTrue(
            any("Account Creation in Progress" in str(m) for m in frappe.local.message_log[log_len:])
        )
        self.assertIn("queued for secure background processing", response["message"])
        self.assertEqual(response["progress_tracking"]["account_request_id"], acr)
        self.assertEqual(response["progress_tracking"]["tracking_url"], f"/app/account-creation-request/{acr}")
        self.assertEqual(response["progress_tracking"]["estimated_completion"], "2-3 minutes")
        self.assertEqual(response["user_account"], user_result)

    def test_linked_existing_user_is_reported_as_linked(self):
        user = self.create_test_user(self.member.email)
        self.track_doc("User", user.name)
        self.member.reload()

        user_result = _create_user_account_safe(self.member, False)
        self.assertEqual((user_result.get("meta") or {}).get("action"), "linked_existing", msg=user_result)

        response = self._respond(user_result)

        self.assertEqual(response["user_account_status"], "linked", msg=response)
        self.assertIn("Linked to existing user account", response["message"])
        self.assertIsNone(response["progress_tracking"]["account_request_id"])

    def test_existing_request_keeps_pending_but_exposes_tracking(self):
        """Control: an in-flight ACR is neither queued nor failed; it stays 'pending' and
        its id still reaches the caller (the second call finds the first call's real ACR)."""
        first = _create_user_account_safe(self.member, False)
        acr = (first.get("meta") or {}).get("account_request")
        self.track_doc("Account Creation Request", acr)

        second = _create_user_account_safe(self.member, False)
        self.assertEqual((second.get("meta") or {}).get("action"), "existing_request", msg=second)

        response = self._respond(second)

        self.assertEqual(response["user_account_status"], "pending", msg=response)
        self.assertEqual(response["progress_tracking"]["account_request_id"], acr)
        self.assertIsNone(response["progress_tracking"]["estimated_completion"])

    def test_failed_result_has_no_tracking(self):
        """Control: a failure carries no meta and must not gain an account request id."""
        response = self._respond({"success": False, "error": "Account creation failed"})
        self.assertEqual(response["user_account_status"], "failed")
        self.assertIsNone(response["progress_tracking"]["account_request_id"])
        self.assertIsNone(response["progress_tracking"]["tracking_url"])
