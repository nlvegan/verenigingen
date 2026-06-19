"""
Real-integration tests for Mollie webhook security utilities.

The signature verification (HMAC-SHA256 build + constant-time compare) is the
logic under test and runs FOR REAL here. The only seam is the *config source*:
`frappe.get_single("Mollie Settings")` is replaced with a lightweight stand-in
settings object so the shared Mollie Settings Single is never mutated and tests
are deterministic regardless of the live config.

Mock justified: `frappe.get_single("Mollie Settings")` is an outbound config
read, not business logic. We substitute a real settings stand-in (with real
test_mode flags and a real secret) so the genuine HMAC verification path is
exercised. The cryptographic comparison itself is never mocked.
"""

import hashlib
import hmac
from types import SimpleNamespace
from unittest.mock import patch

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen_payments.utils.webhook_security import (
    WebhookAuthenticationError,
    log_webhook_security_event,
    verify_mollie_webhook_signature,
)


def _settings(test_mode=False, webhook_secret="whsec_test_key"):
    """Build a real stand-in for the Mollie Settings Single."""
    return SimpleNamespace(
        test_mode=test_mode,
        get_webhook_secret=lambda: webhook_secret,
    )


class TestWebhookSecurity(VereningingenTestCase):
    def _patch_settings(self, settings, developer_mode=True):
        """Patch the config source and developer_mode flag together."""
        self._dev_orig = frappe.conf.get("developer_mode")
        frappe.conf["developer_mode"] = 1 if developer_mode else 0
        # Substitutes the Mollie Settings config source (an outbound Single
        # read), NOT the auth boundary. The HMAC signature verification under
        # test runs for real against this real settings stand-in.
        # Mock justified: config/secret retrieval only — the boundary
        # (signature verify) is never faked; avoids mutating the shared Single.
        p = patch("frappe.get_single", return_value=settings)
        p.start()
        self.addCleanup(p.stop)

        def _restore_dev():
            if self._dev_orig is None:
                frappe.conf.pop("developer_mode", None)
            else:
                frappe.conf["developer_mode"] = self._dev_orig

        self.addCleanup(_restore_dev)

    # ------------------------------------------------------------------
    # Live mode (test_mode=False)
    # ------------------------------------------------------------------
    def test_valid_signature_accepted(self):
        secret = "whsec_live_key"
        payload = '{"id": "tr_abc123"}'
        self._patch_settings(_settings(test_mode=False, webhook_secret=secret), developer_mode=False)
        digest = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        header = f"sha256={digest}"
        self.assertTrue(verify_mollie_webhook_signature(payload, header))

    def test_invalid_signature_rejected(self):
        secret = "whsec_live_key"
        payload = '{"id": "tr_abc123"}'
        self._patch_settings(_settings(test_mode=False, webhook_secret=secret), developer_mode=False)
        with self.assertRaises(WebhookAuthenticationError):
            verify_mollie_webhook_signature(payload, "sha256=deadbeefdeadbeef")

    def test_signature_against_wrong_secret_rejected(self):
        payload = '{"id": "tr_abc123"}'
        self._patch_settings(
            _settings(test_mode=False, webhook_secret="correct_secret"), developer_mode=False
        )
        wrong = hmac.new(b"wrong_secret", payload.encode("utf-8"), hashlib.sha256).hexdigest()
        with self.assertRaises(WebhookAuthenticationError):
            verify_mollie_webhook_signature(payload, f"sha256={wrong}")

    def test_missing_signature_accepted_unsigned_webhook(self):
        # Standard Mollie webhooks are unsigned; a missing header must be accepted.
        self._patch_settings(_settings(test_mode=False, webhook_secret="whsec"), developer_mode=False)
        self.assertTrue(verify_mollie_webhook_signature('{"id": "tr_x"}', None))

    def test_signed_webhook_without_secret_raises(self):
        # A signature IS present but no secret configured -> must raise.
        self._patch_settings(_settings(test_mode=False, webhook_secret=None), developer_mode=False)
        with self.assertRaises(WebhookAuthenticationError):
            verify_mollie_webhook_signature('{"id": "tr_x"}', "sha256=abcd")

    # ------------------------------------------------------------------
    # Test mode behaviour
    # ------------------------------------------------------------------
    def test_test_mode_accepts_no_signature(self):
        self._patch_settings(_settings(test_mode=True, webhook_secret="whsec"), developer_mode=True)
        self.assertTrue(verify_mollie_webhook_signature('{"id": "tr_x"}', None))

    def test_test_mode_accepts_test_signature_prefix(self):
        self._patch_settings(_settings(test_mode=True, webhook_secret="whsec"), developer_mode=True)
        self.assertTrue(verify_mollie_webhook_signature('{"id": "tr_x"}', "test_signature_xyz"))

    def test_test_mode_still_verifies_real_signature(self):
        secret = "whsec_test"
        payload = '{"id": "tr_real"}'
        self._patch_settings(_settings(test_mode=True, webhook_secret=secret), developer_mode=True)
        digest = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        self.assertTrue(verify_mollie_webhook_signature(payload, f"sha256={digest}"))

    def test_test_mode_without_developer_mode_raises_security_error(self):
        # SECURITY: test_mode without any dev/staging override must be rejected.
        self._patch_settings(_settings(test_mode=True, webhook_secret="whsec"), developer_mode=False)
        # ensure no staging override is active
        orig_override = frappe.conf.get("allow_mollie_test_mode")
        frappe.conf.pop("allow_mollie_test_mode", None)
        try:
            with self.assertRaises(WebhookAuthenticationError):
                verify_mollie_webhook_signature('{"id": "tr_x"}', None)
        finally:
            if orig_override is not None:
                frappe.conf["allow_mollie_test_mode"] = orig_override

    def test_test_mode_with_staging_override_allowed(self):
        self._patch_settings(_settings(test_mode=True, webhook_secret="whsec"), developer_mode=False)
        orig_override = frappe.conf.get("allow_mollie_test_mode")
        frappe.conf["allow_mollie_test_mode"] = 1
        try:
            self.assertTrue(verify_mollie_webhook_signature('{"id": "tr_x"}', None))
        finally:
            if orig_override is None:
                frappe.conf.pop("allow_mollie_test_mode", None)
            else:
                frappe.conf["allow_mollie_test_mode"] = orig_override

    # ------------------------------------------------------------------
    # log_webhook_security_event: should never raise
    # ------------------------------------------------------------------
    def test_log_security_event_success(self):
        log_webhook_security_event("success", {"payment": "tr_x"})

    def test_log_security_event_warning(self):
        log_webhook_security_event("warning", {"reason": "retry"})

    def test_log_security_event_failure_writes_error_log(self):
        before = frappe.db.count("Error Log")
        log_webhook_security_event("failure", {"ip": "203.0.113.1"})
        after = frappe.db.count("Error Log")
        # Exactly one Error Log must be written for a failure event (a >= check
        # would pass even if nothing was logged).
        self.assertEqual(after, before + 1)

    def test_log_security_event_unknown_type_is_noop(self):
        # Unknown event type hits no branch; must not raise.
        log_webhook_security_event("mystery", {"x": 1})
