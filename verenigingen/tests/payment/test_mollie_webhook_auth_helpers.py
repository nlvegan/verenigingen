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


class TestValidateWebhookUserPermissionsEffectiveRoles(FrappeTestCase):
    """
    validate_webhook_user_permissions() as the real service account.

    The service account holds the "Verenigingen Webhook User" ROLE PROFILE, which
    materialises three roles onto the user: the literal webhook role plus Accounts User
    and Sales User. These tests pin the two properties that literal-role-only checking
    got wrong: profile-granted permissions must count, and "submit" must be checked for
    submittable doctypes only.

    Real DocPerm / Custom DocPerm rows are used throughout - the doctypes below were
    chosen because their real permission rows isolate one property each:
      * Sales Invoice   - create/write/submit granted ONLY via Accounts User (profile).
      * Payment Request - submittable; Accounts User has create/write but NOT submit.
      * Member          - not submittable; webhook role has create/write, submit is 0.
    """

    SERVICE_USER = "webhook-perm-check@test.invalid"

    def setUp(self):
        if frappe.db.exists("User", self.SERVICE_USER):
            frappe.delete_doc("User", self.SERVICE_USER, force=True)

        frappe.get_doc(
            {
                "doctype": "User",
                "email": self.SERVICE_USER,
                "first_name": "Webhook Perm Check",
                "send_welcome_email": 0,
                # v16: role_profile_name alone is silently dropped
                # (User.move_role_profile_name_to_role_profiles clears it when the
                # role_profiles table is empty) - the table is the live field.
                "role_profiles": [{"role_profile": "Verenigingen Webhook User"}],
            }
        ).insert()

        # Guard the fixture assumption: if the role profile stops materialising these
        # roles, the tests below would silently stop testing what they claim to.
        roles = frappe.get_roles(self.SERVICE_USER)
        self.assertIn("Verenigingen Webhook User", roles)
        self.assertIn("Accounts User", roles)

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.rollback()

    def _missing_permissions(self, doctypes):
        """Run the check for `doctypes` as the service user, returning (ok, message)."""
        with patch.object(ws, "REQUIRED_DOCTYPES", doctypes), patch.object(frappe, "log_error") as mock_log:
            with self.set_user(self.SERVICE_USER):
                ok = ws.validate_webhook_user_permissions()
        message = mock_log.call_args[0][0] if mock_log.call_args else ""
        # Flatten so a failure shows the whole list on the assertion line.
        return ok, " ".join(message.split())

    def test_profile_granted_doctype_is_permitted(self):
        # Sales Invoice is not granted to the literal "Verenigingen Webhook User" role at
        # all; the grant arrives via Accounts User in the role profile.
        ok, message = self._missing_permissions(["Sales Invoice"])
        self.assertTrue(ok, f"Sales Invoice should be permitted via the role profile: {message}")

    def test_submit_is_checked_for_submittable_doctype(self):
        # Payment Request is submittable and the service account's effective roles grant
        # create/write but not submit - so submit, and only submit, must be reported.
        ok, message = self._missing_permissions(["Payment Request"])
        self.assertFalse(ok, "a missing submit permission must be reported")
        self.assertIn("Payment Request (submit)", message)
        self.assertNotIn("Payment Request (create)", message)
        self.assertNotIn("Payment Request (write)", message)

    def test_no_spurious_submit_miss_for_non_submittable_doctype(self):
        # Member has no submit DocPerm because Member is not submittable. Demanding one
        # would report a miss that means nothing.
        ok, message = self._missing_permissions(["Member"])
        self.assertTrue(ok, f"non-submittable Member must not report a submit miss: {message}")

    def test_real_required_doctypes_all_pass(self):
        # The shipped list must pass for the real service account - this check runs on
        # every webhook and a false miss would log an Error Log each time.
        ok, message = self._missing_permissions(ws.REQUIRED_DOCTYPES)
        self.assertTrue(ok, message)


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
