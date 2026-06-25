"""
Coverage gap-fill for verenigingen_payments/core/security/mollie_security_manager.py

Uses a REAL Mollie Settings Single doc (no mocks). The webhook secret is set
in-memory on the real testing_webhook_secret_key field with test_mode=1 (Frappe's
get_password falls back to the in-memory field value), so validate_webhook_signature
resolves it via MollieSettings.get_webhook_secret() exactly like production. The
encryption_key is the one already provisioned on the test site, so the real Fernet
cipher runs end-to-end.

Covers:
- validate_webhook_signature: valid signature, invalid signature (raises +
  security alert), missing secret (raises), valid timestamp, replay-window
  timestamp (raises).
- encrypt_sensitive_data / decrypt_sensitive_data: roundtrip, empty-string short
  circuits, non-string coercion, tampered ciphertext raises SecurityException.
- _validate_webhook_timestamp: within tolerance, outside tolerance, unparseable.
- _calculate_integrity_hash: deterministic + sensitive to field changes.
- rotate_api_keys: returns informational "not supported" payload.

SKIPPED (out of scope per task): email-alert delivery paths (live email service),
_test_api_connectivity (live Mollie HTTP), _schedule_fallback_cleanup (enqueue),
audit-log DocType insertion.

Run:
    bench --site test_site_1 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_mollie_security_manager_coverage_b1
"""

import hashlib
import hmac

import frappe
from frappe.utils import add_to_date, now_datetime

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen_payments.core.security.mollie_security_manager import (
    MollieSecurityManager,
    SecurityException,
)

WEBHOOK_SECRET = "coverage_b1_webhook_secret"


class TestMollieSecurityManager(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.settings = self._get_settings_with_secret()
        self.manager = MollieSecurityManager(self.settings)

    def _get_settings_with_secret(self):
        """Load the real Mollie Settings Single and set an in-memory webhook secret.

        Sets test_mode + the real testing_webhook_secret_key field so
        get_webhook_secret() resolves it. get_password() returns the in-memory
        field value when present, so no DB write is required and nothing leaks
        past this test.
        """
        settings = frappe.get_single("Mollie Settings")
        settings.test_mode = 1
        settings.set("testing_webhook_secret_key", WEBHOOK_SECRET)
        return settings

    def _sign(self, payload: str, secret: str = WEBHOOK_SECRET) -> str:
        return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()

    # ---- webhook signature ----

    def test_valid_signature_accepted(self):
        payload = '{"id":"tr_valid"}'
        with self.assertNoErrorLog():
            self.assertTrue(self.manager.validate_webhook_signature(payload, self._sign(payload)))

    def test_invalid_signature_raises(self):
        payload = '{"id":"tr_bad"}'
        # Invalid signature path writes a critical security alert (Error Log) by design.
        self.expectErrorLog("Mollie Security Alert")
        with self.assertRaises(SecurityException):
            self.manager.validate_webhook_signature(payload, "deadbeef" * 8)

    def test_signature_with_wrong_secret_raises(self):
        payload = '{"id":"tr_wrong_secret"}'
        self.expectErrorLog("Mollie Security Alert")
        with self.assertRaises(SecurityException):
            self.manager.validate_webhook_signature(payload, self._sign(payload, "the_wrong_secret"))

    def test_missing_secret_fails_closed(self):
        # With no webhook secret configured the manager's own guard must fire and
        # fail closed with SecurityException (get_webhook_secret() returns None
        # gracefully via raise_exception=False, so the guard — not a framework
        # error — is what's exercised here).
        payload = '{"id":"tr_no_secret"}'
        settings = frappe.get_single("Mollie Settings")
        settings.test_mode = 1
        settings.set("testing_webhook_secret_key", None)  # unset -> get_webhook_secret() returns None
        manager = MollieSecurityManager(settings)
        self.expectErrorLog("Mollie Security")
        with self.assertRaises(SecurityException):
            manager.validate_webhook_signature(payload, "anything")

    def test_valid_signature_with_fresh_timestamp(self):
        payload = '{"id":"tr_ts"}'
        ts = str(now_datetime())
        with self.assertNoErrorLog():
            self.assertTrue(self.manager.validate_webhook_signature(payload, self._sign(payload), ts))

    def test_stale_timestamp_raises_replay(self):
        payload = '{"id":"tr_replay"}'
        stale = str(add_to_date(now_datetime(), seconds=-3600))
        self.expectErrorLog("Mollie Security Alert")
        with self.assertRaises(SecurityException):
            self.manager.validate_webhook_signature(payload, self._sign(payload), stale)

    # ---- encryption ----

    def test_encrypt_decrypt_roundtrip(self):
        plaintext = "sensitive-iban-NL91ABNA0417164300"
        with self.assertNoErrorLog():
            encrypted = self.manager.encrypt_sensitive_data(plaintext)
            self.assertNotEqual(encrypted, plaintext)
            self.assertEqual(self.manager.decrypt_sensitive_data(encrypted), plaintext)

    def test_encrypt_empty_returns_empty(self):
        self.assertEqual(self.manager.encrypt_sensitive_data(""), "")

    def test_decrypt_empty_returns_empty(self):
        self.assertEqual(self.manager.decrypt_sensitive_data(""), "")

    def test_encrypt_coerces_non_string(self):
        with self.assertNoErrorLog():
            encrypted = self.manager.encrypt_sensitive_data(12345)
            self.assertEqual(self.manager.decrypt_sensitive_data(encrypted), "12345")

    def test_decrypt_tampered_ciphertext_raises(self):
        encrypted = self.manager.encrypt_sensitive_data("payload")
        tampered = encrypted[:-4] + "XXXX"
        # Decryption failure logs an error by design.
        self.expectErrorLog("Mollie Security")
        with self.assertRaises(SecurityException):
            self.manager.decrypt_sensitive_data(tampered)

    # ---- timestamp validation ----

    def test_timestamp_within_tolerance(self):
        self.assertTrue(self.manager._validate_webhook_timestamp(str(now_datetime())))

    def test_timestamp_outside_tolerance(self):
        old = str(add_to_date(now_datetime(), seconds=-3600))
        self.assertFalse(self.manager._validate_webhook_timestamp(old))

    def test_timestamp_within_custom_tolerance(self):
        ts = str(add_to_date(now_datetime(), seconds=-100))
        self.assertTrue(self.manager._validate_webhook_timestamp(ts, tolerance_seconds=300))
        self.assertFalse(self.manager._validate_webhook_timestamp(ts, tolerance_seconds=50))

    def test_unparseable_timestamp_returns_false(self):
        self.expectErrorLog("Mollie Security")
        self.assertFalse(self.manager._validate_webhook_timestamp("not-a-timestamp"))

    # ---- integrity hash ----

    def test_integrity_hash_is_deterministic(self):
        log = frappe._dict(
            action="TEST_ACTION", status="success", details="d", timestamp="2024-01-01", user="x@y.z"
        )
        h1 = self.manager._calculate_integrity_hash(log)
        h2 = self.manager._calculate_integrity_hash(log)
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)  # sha256 hex

    def test_integrity_hash_changes_with_field(self):
        base = frappe._dict(
            action="A", status="success", details="d", timestamp="2024-01-01", user="x@y.z"
        )
        changed = frappe._dict(
            action="A", status="FAILED", details="d", timestamp="2024-01-01", user="x@y.z"
        )
        self.assertNotEqual(
            self.manager._calculate_integrity_hash(base),
            self.manager._calculate_integrity_hash(changed),
        )

    # ---- rotate_api_keys ----

    def test_rotate_api_keys_returns_info(self):
        # rotate_api_keys() writes a "skipped" audit log; in test context the
        # secure audit-log insert can't resolve a request and is swallowed-and-logged
        # by design (best-effort audit trail), so allow that Error Log row.
        self.expectErrorLog("Mollie Security Audit")
        result = self.manager.rotate_api_keys()
        self.assertEqual(result["status"], "info")
        # Exactly the 4 fixed manual-rotation steps.
        self.assertEqual(len(result["manual_process"]), 4)
