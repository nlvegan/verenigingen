# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Unit tests for ING Checkout webhook security

Tests IP validation, HMAC signature verification, fail-closed security,
and idempotency protection.
"""

import hashlib
import hmac
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.ing_checkout.utils.webhook_security import (
    INGCheckoutWebhookError,
    compute_webhook_hash,
    fetch_paynl_ip_addresses,
    get_request_ip,
    is_duplicate_webhook,
    log_webhook,
    verify_ing_checkout_webhook,
    verify_webhook_ip,
    verify_webhook_signature,
)


class TestVerifyWebhookSignature(FrappeTestCase):
    """Test HMAC-SHA256 signature verification."""

    def test_valid_signature(self):
        """Test that valid signature passes verification."""
        secret = "test_secret_key"
        payload = b'{"test": "data"}'

        # Generate valid signature
        expected_signature = hmac.new(
            secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()

        result = verify_webhook_signature(payload, expected_signature, secret)
        self.assertTrue(result)

    def test_invalid_signature(self):
        """Test that invalid signature fails verification."""
        secret = "test_secret_key"
        payload = b'{"test": "data"}'
        invalid_signature = "invalid_signature_here"

        result = verify_webhook_signature(payload, invalid_signature, secret)
        self.assertFalse(result)

    def test_missing_secret_fails(self):
        """Test that missing secret fails verification."""
        payload = b'{"test": "data"}'
        signature = "some_signature"

        result = verify_webhook_signature(payload, signature, None)
        self.assertFalse(result)

    def test_missing_signature_fails(self):
        """Test that missing signature fails verification."""
        payload = b'{"test": "data"}'
        secret = "test_secret_key"

        result = verify_webhook_signature(payload, None, secret)
        self.assertFalse(result)

    def test_case_insensitive_signature_comparison(self):
        """Test that signature comparison is case-insensitive."""
        secret = "test_secret_key"
        payload = b'{"test": "data"}'

        expected_signature = hmac.new(
            secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()

        # Test with uppercase
        result = verify_webhook_signature(payload, expected_signature.upper(), secret)
        self.assertTrue(result)


class TestIPValidation(FrappeTestCase):
    """Test IP address validation."""

    @patch("verenigingen.verenigingen_payments.ing_checkout.utils.webhook_security.fetch_paynl_ip_addresses")
    def test_valid_ip_passes(self, mock_fetch):
        """Test that valid Pay.nl IP passes validation."""
        mock_fetch.return_value = ["1.2.3.4", "5.6.7.8"]

        result = verify_webhook_ip("1.2.3.4")
        self.assertTrue(result)

    @patch("verenigingen.verenigingen_payments.ing_checkout.utils.webhook_security.fetch_paynl_ip_addresses")
    def test_invalid_ip_fails(self, mock_fetch):
        """Test that invalid IP fails validation."""
        mock_fetch.return_value = ["1.2.3.4", "5.6.7.8"]

        result = verify_webhook_ip("9.9.9.9")
        self.assertFalse(result)

    @patch("verenigingen.verenigingen_payments.ing_checkout.utils.webhook_security.fetch_paynl_ip_addresses")
    def test_empty_ip_list_returns_false(self, mock_fetch):
        """Test that empty IP list returns False (fail-closed)."""
        mock_fetch.return_value = []

        result = verify_webhook_ip("1.2.3.4")
        # Fail-closed: empty list means validation failed
        self.assertFalse(result)

    def test_empty_remote_ip_fails(self):
        """Test that empty remote IP fails validation."""
        result = verify_webhook_ip("")
        self.assertFalse(result)

    def test_none_remote_ip_fails(self):
        """Test that None remote IP fails validation."""
        result = verify_webhook_ip(None)
        self.assertFalse(result)


class TestFailClosedSecurity(FrappeTestCase):
    """Test fail-closed webhook security behavior."""

    @patch("verenigingen.verenigingen_payments.ing_checkout.utils.webhook_security.get_webhook_secret")
    @patch("verenigingen.verenigingen_payments.ing_checkout.utils.webhook_security.get_request_ip")
    @patch("verenigingen.verenigingen_payments.ing_checkout.utils.webhook_security.verify_webhook_ip")
    def test_fails_when_ip_invalid_and_no_secret(self, mock_verify_ip, mock_get_ip, mock_get_secret):
        """Test that webhook is rejected when IP invalid and no secret configured."""
        mock_get_ip.return_value = "9.9.9.9"
        mock_verify_ip.return_value = False
        mock_get_secret.return_value = None  # No secret configured

        payload = b'{"test": "data"}'

        with self.assertRaises(INGCheckoutWebhookError) as context:
            verify_ing_checkout_webhook(payload, signature=None)

        self.assertIn("security validation failed", context.exception.message.lower())

    @patch("verenigingen.verenigingen_payments.ing_checkout.utils.webhook_security.get_webhook_secret")
    @patch("verenigingen.verenigingen_payments.ing_checkout.utils.webhook_security.get_request_ip")
    @patch("verenigingen.verenigingen_payments.ing_checkout.utils.webhook_security.verify_webhook_ip")
    def test_passes_when_ip_valid(self, mock_verify_ip, mock_get_ip, mock_get_secret):
        """Test that webhook passes when IP is valid."""
        mock_get_ip.return_value = "1.2.3.4"
        mock_verify_ip.return_value = True
        mock_get_secret.return_value = None  # No secret needed

        payload = b'{"test": "data"}'

        result = verify_ing_checkout_webhook(payload, signature=None)
        self.assertTrue(result)

    @patch("verenigingen.verenigingen_payments.ing_checkout.utils.webhook_security.get_webhook_secret")
    @patch("verenigingen.verenigingen_payments.ing_checkout.utils.webhook_security.get_request_ip")
    @patch("verenigingen.verenigingen_payments.ing_checkout.utils.webhook_security.verify_webhook_ip")
    @patch("verenigingen.verenigingen_payments.ing_checkout.utils.webhook_security.verify_webhook_signature")
    def test_passes_when_signature_valid(self, mock_verify_sig, mock_verify_ip, mock_get_ip, mock_get_secret):
        """Test that webhook passes when signature is valid even if IP fails."""
        mock_get_ip.return_value = "9.9.9.9"
        mock_verify_ip.return_value = False
        mock_get_secret.return_value = "test_secret"
        mock_verify_sig.return_value = True

        payload = b'{"test": "data"}'

        result = verify_ing_checkout_webhook(payload, signature="valid_sig")
        self.assertTrue(result)

    @patch("verenigingen.verenigingen_payments.ing_checkout.utils.webhook_security.get_webhook_secret")
    @patch("verenigingen.verenigingen_payments.ing_checkout.utils.webhook_security.get_request_ip")
    @patch("verenigingen.verenigingen_payments.ing_checkout.utils.webhook_security.verify_webhook_ip")
    @patch("verenigingen.verenigingen_payments.ing_checkout.utils.webhook_security.verify_webhook_signature")
    def test_fails_when_signature_invalid(
        self, mock_verify_sig, mock_verify_ip, mock_get_ip, mock_get_secret
    ):
        """Test that webhook fails when signature is invalid."""
        mock_get_ip.return_value = "9.9.9.9"
        mock_verify_ip.return_value = False
        mock_get_secret.return_value = "test_secret"
        mock_verify_sig.return_value = False

        payload = b'{"test": "data"}'

        with self.assertRaises(INGCheckoutWebhookError) as context:
            verify_ing_checkout_webhook(payload, signature="invalid_sig")

        self.assertIn("invalid", context.exception.message.lower())


class TestIdempotency(FrappeTestCase):
    """Test webhook idempotency protection."""

    def test_compute_webhook_hash(self):
        """Test that webhook hash is computed consistently."""
        event_id = "EX-1234-5678-9012"
        payload = '{"test": "data"}'

        hash1 = compute_webhook_hash(event_id, payload)
        hash2 = compute_webhook_hash(event_id, payload)

        self.assertEqual(hash1, hash2)
        self.assertEqual(len(hash1), 64)  # SHA256 hex length

    def test_different_payloads_different_hashes(self):
        """Test that different payloads produce different hashes."""
        event_id = "EX-1234-5678-9012"

        hash1 = compute_webhook_hash(event_id, '{"test": "data1"}')
        hash2 = compute_webhook_hash(event_id, '{"test": "data2"}')

        self.assertNotEqual(hash1, hash2)

    def test_is_duplicate_webhook_not_found(self):
        """Test that webhook is not duplicate when hash not in DB."""
        with patch("frappe.db.exists", return_value=False):
            result = is_duplicate_webhook("test_event", '{"test": "data"}')
            self.assertFalse(result)

    def test_is_duplicate_webhook_found(self):
        """Test that webhook is detected as duplicate when hash exists."""
        with patch("frappe.db.exists", return_value=True):
            result = is_duplicate_webhook("test_event", '{"test": "data"}')
            self.assertTrue(result)


class TestLogWebhook(FrappeTestCase):
    """Test webhook logging functionality."""

    @patch("frappe.new_doc")
    @patch("frappe.db.exists")
    def test_log_webhook_creates_record(self, mock_exists, mock_new_doc):
        """Test that log_webhook creates a Webhook Processing Log record."""
        mock_exists.return_value = False  # Not a duplicate

        mock_log = MagicMock()
        mock_log.name = "WEBHOOK-00001"
        mock_new_doc.return_value = mock_log

        log_name = log_webhook(
            event_id="test_event_123",
            webhook_type="ing_checkout_payment",
            raw_payload='{"test": "data"}',
            status="success",
            processing_result='{"result": "ok"}',
        )

        self.assertEqual(log_name, "WEBHOOK-00001")
        mock_new_doc.assert_called_once_with("Webhook Processing Log")
        mock_log.insert.assert_called_once_with(ignore_permissions=True)

    @patch("frappe.new_doc")
    @patch("frappe.db.exists")
    def test_log_webhook_truncates_long_event_id(self, mock_exists, mock_new_doc):
        """Test that long event IDs are truncated."""
        mock_exists.return_value = False

        mock_log = MagicMock()
        mock_log.name = "WEBHOOK-00002"
        mock_new_doc.return_value = mock_log

        event_id = "X" * 200  # Very long event ID

        log_webhook(
            event_id=event_id,
            webhook_type="ing_checkout_payment",
            raw_payload='{"test": "data"}',
            status="success",
        )

        # Verify event_id was truncated
        self.assertLessEqual(len(mock_log.webhook_id), 140)

    @patch("frappe.db.exists")
    def test_log_webhook_prevents_duplicate(self, mock_exists):
        """Test that duplicate webhooks are not logged twice."""
        mock_exists.return_value = True  # Already exists

        log_name = log_webhook(
            event_id="duplicate_event",
            webhook_type="ing_checkout_payment",
            raw_payload='{"test": "data"}',
            status="success",
        )

        self.assertIsNone(log_name)  # Should return None for duplicate

    @patch("frappe.new_doc")
    @patch("frappe.db.exists")
    def test_log_webhook_handles_error(self, mock_exists, mock_new_doc):
        """Test that log_webhook handles exceptions gracefully."""
        mock_exists.return_value = False
        mock_new_doc.side_effect = Exception("Database error")

        log_name = log_webhook(
            event_id="test_event",
            webhook_type="ing_checkout_payment",
            raw_payload='{"test": "data"}',
            status="success",
        )

        self.assertIsNone(log_name)  # Should return None on error


class TestGetRequestIP(FrappeTestCase):
    """Test request IP extraction."""

    def test_get_request_ip_no_request(self):
        """Test that None is returned when no request context."""
        # Clear any existing request
        if hasattr(frappe, "request"):
            old_request = frappe.request
            frappe.request = None
            result = get_request_ip()
            frappe.request = old_request
        else:
            result = get_request_ip()
        self.assertIsNone(result)


class TestFetchPayNLIPAddresses(FrappeTestCase):
    """Test Pay.nl IP address fetching."""

    @patch("requests.get")
    def test_fetch_ip_addresses_success(self, mock_get):
        """Test successful IP address fetch from Pay.nl."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = [
            {"ipAddress": "1.2.3.4"},
            {"ipAddress": "5.6.7.8"},
        ]
        mock_get.return_value = mock_response

        # Clear cache
        from verenigingen.verenigingen_payments.ing_checkout.utils import webhook_security

        webhook_security._paynl_ip_cache = {"ips": [], "last_updated": None}

        result = fetch_paynl_ip_addresses()
        self.assertIn("1.2.3.4", result)
        self.assertIn("5.6.7.8", result)

    @patch("requests.get")
    def test_fetch_ip_addresses_network_error(self, mock_get):
        """Test handling of network error when fetching IPs."""
        mock_get.side_effect = Exception("Network error")

        # Clear cache
        from verenigingen.verenigingen_payments.ing_checkout.utils import webhook_security

        webhook_security._paynl_ip_cache = {"ips": [], "last_updated": None}

        result = fetch_paynl_ip_addresses()
        self.assertEqual(result, [])  # Should return empty list on error
