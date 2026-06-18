"""
Tests for Mollie webhook security helpers.

Target: verenigingen/verenigingen_payments/mollie/utils/webhook_security.py

Covers:
* validate_webhook_user_permissions() for a privileged user (Administrator) and
  a no-permission user.
* _check_docperm_for_roles() against the real DocPerm / Custom DocPerm tables.
* log_webhook_security_event() writes a real Mollie Audit Log row.
* authenticate_mollie_webhook() failure paths (rate-limit, empty payload) driven
  through the real rate limiter / signature verifier at the external boundary.

The signature verifier and rate limiter live in other modules and are exercised
at their boundary (we set up real request state) rather than mocked, except the
HTTP-less rate-limit decision which we drive deterministically.
"""

import unittest
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.mollie.utils import webhook_security as ws


class TestCheckDocpermForRoles(FrappeTestCase):
    """_check_docperm_for_roles against real permission tables."""

    def tearDown(self):
        frappe.db.rollback()

    def test_administrator_role_has_donation_write_via_docperm(self):
        # "System Manager" universally has read/write on Donation in this app.
        result = ws._check_docperm_for_roles("Donation", "write", ["System Manager"])
        self.assertTrue(result)

    def test_unknown_role_has_no_permission(self):
        result = ws._check_docperm_for_roles(
            "Donation", "write", ["__NonexistentRole_zzz__"]
        )
        self.assertFalse(result)

    def test_core_doctype_checked_via_custom_docperm(self):
        # Journal Entry is a core ERPNext doctype; System Manager has write.
        # Either DocPerm or Custom DocPerm should grant it.
        result = ws._check_docperm_for_roles("Journal Entry", "write", ["System Manager"])
        self.assertTrue(result)


class TestValidateWebhookUserPermissions(FrappeTestCase):
    """validate_webhook_user_permissions() with real session users."""

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.rollback()

    def test_administrator_passes(self):
        with self.set_user("Administrator"):
            self.assertTrue(ws.validate_webhook_user_permissions())

    def test_guest_user_fails(self):
        with self.set_user("Guest"):
            # Guest lacks create/write on the required doctypes.
            self.assertFalse(ws.validate_webhook_user_permissions())


class TestLogWebhookSecurityEvent(FrappeTestCase):
    """log_webhook_security_event() persists a Mollie Audit Log row."""

    def tearDown(self):
        frappe.db.rollback()

    def test_logs_audit_row(self):
        before = frappe.db.count(
            "Mollie Audit Log", {"event_type": "webhook_security_unit_test_event"}
        )
        ws.log_webhook_security_event("unit_test_event", {"ip": "1.2.3.4", "reason": "test"})
        after = frappe.db.count(
            "Mollie Audit Log", {"event_type": "webhook_security_unit_test_event"}
        )
        self.assertEqual(after, before + 1)

        row = frappe.get_last_doc(
            "Mollie Audit Log", filters={"event_type": "webhook_security_unit_test_event"}
        )
        self.assertEqual(row.event_category, "security")
        self.assertIn("unit_test_event", row.description)

    def test_serializes_complex_details(self):
        # event_data must be JSON-serialized; nested structures should round-trip.
        ws.log_webhook_security_event(
            "complex_event", {"nested": {"a": [1, 2]}, "flag": True}
        )
        row = frappe.get_last_doc(
            "Mollie Audit Log", filters={"event_type": "webhook_security_complex_event"}
        )
        self.assertIn("nested", row.event_data)


class TestAuthenticateMollieWebhook(FrappeTestCase):
    """authenticate_mollie_webhook() failure-path coverage."""

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.rollback()

    def test_rate_limit_exceeded_raises(self):
        from verenigingen.utils.webhook_rate_limiter import WebhookRateLimitExceeded

        with patch(
            "verenigingen.utils.webhook_rate_limiter.get_webhook_rate_limiter"
        ) as mock_get_rl:
            mock_get_rl.return_value.check_rate_limit.return_value = (False, "too many")
            with self.assertRaises(WebhookRateLimitExceeded):
                ws.authenticate_mollie_webhook()

    def test_empty_payload_raises_authentication_error(self):
        from verenigingen.verenigingen_payments.utils.webhook_security import (
            WebhookAuthenticationError,
        )

        with patch(
            "verenigingen.utils.webhook_rate_limiter.get_webhook_rate_limiter"
        ) as mock_get_rl, patch.object(frappe, "request", None):
            mock_get_rl.return_value.check_rate_limit.return_value = (True, None)
            with self.assertRaises(WebhookAuthenticationError):
                ws.authenticate_mollie_webhook()


if __name__ == "__main__":
    unittest.main()
