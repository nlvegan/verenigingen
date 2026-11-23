"""
Coverage sweep for verenigingen_payments/mollie/api/payment_webhook.py

Targets ``_validate_webhook_signature()`` -- the STRICT HMAC-SHA256 webhook
signature validator. This is security-critical: a test that passes regardless of
the signature would be worthless, so every assertion below pins a real
accept/reject decision against a genuine HMAC computed with the configured
webhook secret (no mocking of the comparison logic).

Only true external boundaries are stubbed (the HTTP request context via the
shared ``install_fake_request`` fixture, and the Mollie Settings secret via
``mollie_settings_override``). The signature logic itself runs for real.

(``process_failed_payment()`` and its tests were deleted in #2676: dead code.)
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.api.payment_webhook import _validate_webhook_signature
from verenigingen.verenigingen_payments.mollie.tests.fixtures.webhook_fixtures import (
    install_fake_request,
    make_webhook_payload,
    mollie_settings_override,
    sign_payload,
)

SECRET = "whsec_payment_webhook_sweep_secret"


class TestValidateWebhookSignature(EnhancedTestCase):
    """Real HMAC-SHA256 validation of the STRICT _validate_webhook_signature path.

    This validator REQUIRES a signature header (unlike the lenient live path) and
    raises frappe.PermissionError on any failure. We assert the genuine
    accept/reject decision for valid, missing, unconfigured-secret, wrong-secret,
    tampered, and prefix-less-but-valid signatures.
    """

    PAYLOAD = make_webhook_payload("tr_sig_sweep_123", status="paid", amount="100.00")

    def setUp(self):
        super().setUp()
        # On a long-lived local site Mollie Settings may carry stale Account link
        # values (mollie_bank_account / clearing / fees) that no longer resolve,
        # tripping LinkValidationError when mollie_settings_override re-saves the
        # single. These fields are irrelevant to signature validation, so clear
        # them via db.set_value (no link checks). Rolled back per test by
        # EnhancedTestCase; on a fresh CI site they are already empty.
        for fieldname in (
            "mollie_bank_account",
            "mollie_clearing_account",
            "payment_processing_fees_account",
        ):
            frappe.db.set_value("Mollie Settings", "Mollie Settings", fieldname, "", update_modified=False)

    def test_valid_signature_accepted(self):
        """A correctly computed sha256=<hmac> header is accepted (no raise)."""
        sig = sign_payload(self.PAYLOAD, SECRET)
        with mollie_settings_override(test_mode=True, webhook_secret=SECRET):
            with install_fake_request(self.PAYLOAD, sig):
                # Returns None and does not raise.
                self.assertIsNone(_validate_webhook_signature())

    def test_signature_without_sha256_prefix_accepted(self):
        """A bare hex digest (no 'sha256=' prefix) that matches is still accepted.

        Exercises the else-branch that uses the header value verbatim.
        """
        full = sign_payload(self.PAYLOAD, SECRET)
        bare = full[len("sha256=") :]
        self.assertFalse(bare.startswith("sha256="))
        with mollie_settings_override(test_mode=True, webhook_secret=SECRET):
            with install_fake_request(self.PAYLOAD, bare):
                self.assertIsNone(_validate_webhook_signature())

    def test_missing_signature_header_rejected(self):
        """No X-Mollie-Signature header => hard reject (PermissionError)."""
        with mollie_settings_override(test_mode=True, webhook_secret=SECRET):
            with install_fake_request(self.PAYLOAD, signature=None):
                with self.assertRaises(frappe.PermissionError):
                    _validate_webhook_signature()

    def test_no_secret_configured_rejected(self):
        """Signature present but NO webhook secret configured => hard reject.

        Accepting a signed webhook we cannot verify would be a silent hole.
        """
        sig = sign_payload(self.PAYLOAD, SECRET)
        with mollie_settings_override(test_mode=True, webhook_secret=""):
            with install_fake_request(self.PAYLOAD, sig):
                with self.assertRaises(frappe.PermissionError):
                    _validate_webhook_signature()

    def test_wrong_secret_signature_rejected(self):
        """A signature computed with the wrong secret is rejected, not accepted."""
        wrong = sign_payload(self.PAYLOAD, "a_totally_different_secret")
        with mollie_settings_override(test_mode=True, webhook_secret=SECRET):
            with install_fake_request(self.PAYLOAD, wrong):
                with self.assertRaises(frappe.PermissionError):
                    _validate_webhook_signature()

    def test_tampered_body_rejected(self):
        """A signature valid for the original body fails once the body is tampered.

        The HMAC binds the exact bytes: flipping a single field invalidates an
        otherwise-valid header. This is the core integrity guarantee.
        """
        sig = sign_payload(self.PAYLOAD, SECRET)
        tampered = self.PAYLOAD.replace('"100.00"', '"999.00"')
        self.assertNotEqual(tampered, self.PAYLOAD)
        with mollie_settings_override(test_mode=True, webhook_secret=SECRET):
            with install_fake_request(tampered, sig):
                with self.assertRaises(frappe.PermissionError):
                    _validate_webhook_signature()

    def test_garbage_signature_rejected(self):
        """A non-hex / structurally wrong signature value is rejected."""
        with mollie_settings_override(test_mode=True, webhook_secret=SECRET):
            with install_fake_request(self.PAYLOAD, "sha256=not-a-real-digest"):
                with self.assertRaises(frappe.PermissionError):
                    _validate_webhook_signature()
