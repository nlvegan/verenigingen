"""
Tests for verify_mollie_webhook_signature — signature verification is optional.

Standard Mollie Payments API webhooks are UNSIGNED: the request body carries
only an opaque resource id and no X-Mollie-Signature header (signed webhooks
exist only for Mollie Connect / next-gen webhooks). The trust anchor is that
the webhook handler re-fetches authoritative state from the Mollie API by id.

Regression (audit T2.1, 2026-05-17): the verifier hard-raised on a missing
signature header whenever a webhook secret was configured, which rejected
every genuine live webhook. A missing signature must be accepted; a present
signature must still be verified.
"""

import hashlib
import hmac
import unittest
from unittest.mock import patch

from verenigingen.verenigingen_payments.utils import webhook_security
from verenigingen.verenigingen_payments.utils.webhook_security import (
    WebhookAuthenticationError,
    verify_mollie_webhook_signature,
)


class _FakeMollieSettings:
    """Minimal stand-in for the Mollie Settings single doctype."""

    test_mode = 0  # live mode — exercises the live-webhook code path

    def __init__(self, secret):
        self._secret = secret

    def get_webhook_secret(self):
        return self._secret


class TestMollieWebhookSignatureOptional(unittest.TestCase):
    """Signature verification must not reject unsigned Mollie webhooks."""

    def _verify(self, payload, header, secret="live_secret_xyz"):
        # Mock justified: Infrastructure — Mollie Settings is configuration
        # retrieval, not the signature-verification logic under test. The
        # fake is used by both verify_mollie_webhook_signature and
        # _validate_test_mode_safety (both call frappe.get_single).
        with patch.object(
            webhook_security.frappe, "get_single", return_value=_FakeMollieSettings(secret)
        ):
            return verify_mollie_webhook_signature(payload, header)

    def test_missing_signature_header_is_accepted(self):
        """An unsigned webhook (no X-Mollie-Signature header) is accepted."""
        self.assertTrue(self._verify('{"id": "tr_test"}', None))

    def test_missing_signature_accepted_even_without_secret(self):
        """An unsigned webhook is accepted even when no secret is configured —
        there is nothing to verify against and Mollie does not sign these."""
        self.assertTrue(self._verify('{"id": "tr_test"}', None, secret=None))

    def test_valid_signature_still_verified(self):
        """A correct signature, when present, still passes verification."""
        payload = '{"id": "tr_test"}'
        secret = "live_secret_xyz"
        sig = "sha256=" + hmac.new(
            secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        self.assertTrue(self._verify(payload, sig, secret))

    def test_invalid_signature_still_rejected(self):
        """An incorrect signature, when present, is still rejected."""
        with self.assertRaises(WebhookAuthenticationError):
            self._verify('{"id": "tr_test"}', "sha256=deadbeef")


if __name__ == "__main__":
    unittest.main()
