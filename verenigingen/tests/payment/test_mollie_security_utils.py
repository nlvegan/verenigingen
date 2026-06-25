"""
Unit tests for Mollie security utilities.

Target: verenigingen/verenigingen_payments/mollie/utils/security.py

These are SECURITY tests. The reject paths (forged signature, bad origin,
missing secret in live mode) are the load-bearing assertions and must be
real, not mocked.
"""

import hashlib
import hmac
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from verenigingen.verenigingen_payments.mollie.exceptions import MollieSecurityError
from verenigingen.verenigingen_payments.mollie.utils.security import (
    APISecurityManager,
    WebhookSecurityManager,
    validate_mollie_webhook_request,
)

SECURITY_MODULE = "verenigingen.verenigingen_payments.mollie.utils.security"


def _sign(payload: str, secret: str) -> str:
    """Compute the expected HMAC-SHA256 hexdigest exactly as production does."""
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _canonical(data: dict) -> str:
    """Serialize dict payload the same way production does."""
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def _make_manager(settings):
    """Build a WebhookSecurityManager without touching frappe.get_single.

    __init__ calls _load_security_settings -> frappe.get_single. We patch
    that out and then overwrite .settings with the exact dict shape we want.
    """
    with patch(f"{SECURITY_MODULE}.frappe.get_single", return_value=MagicMock()):
        mgr = WebhookSecurityManager()
    mgr.settings = settings
    return mgr


class TestWebhookSignatureValidation(unittest.TestCase):
    """validate_webhook_signature - the core security gate."""

    SECRET = "super-secret-webhook-key"

    def _full_settings(self, **overrides):
        base = {
            "webhook_secret": self.SECRET,
            "verify_ssl": True,
            "allowed_ips": [],
            "signature_validation": True,
        }
        base.update(overrides)
        return base

    def test_signature_validation_disabled_returns_true(self):
        """Fail-open ONLY when explicitly disabled via setting (intentional)."""
        mgr = _make_manager(self._full_settings(signature_validation=False))
        with patch(f"{SECURITY_MODULE}.frappe.log_error"):
            result = mgr.validate_webhook_signature({"id": "tr_x"}, {})
        self.assertTrue(result)

    def test_no_secret_test_mode_returns_true(self):
        """No webhook secret + test_mode -> skip (returns True)."""
        mgr = _make_manager(self._full_settings(webhook_secret=None))
        fake_settings = SimpleNamespace(test_mode=1)
        with patch(f"{SECURITY_MODULE}.frappe.get_single", return_value=fake_settings):
            result = mgr.validate_webhook_signature({"id": "tr_x"}, {})
        self.assertTrue(result)

    def test_no_secret_live_mode_raises(self):
        """No webhook secret + live mode -> hard reject."""
        mgr = _make_manager(self._full_settings(webhook_secret=None))
        fake_settings = SimpleNamespace(test_mode=0)
        with patch(f"{SECURITY_MODULE}.frappe.get_single", return_value=fake_settings):
            with self.assertRaises(MollieSecurityError):
                mgr.validate_webhook_signature({"id": "tr_x"}, {})

    def test_secret_present_missing_header_raises(self):
        """Secret configured but no signature header -> reject."""
        mgr = _make_manager(self._full_settings())
        with self.assertRaises(MollieSecurityError) as ctx:
            mgr.validate_webhook_signature({"id": "tr_x"}, {})
        self.assertIn("Missing webhook signature header", str(ctx.exception))

    def test_correct_signature_returns_true(self):
        """A correctly computed signature is accepted."""
        mgr = _make_manager(self._full_settings())
        data = {"id": "tr_abc", "amount": "10.00", "z": 1}
        sig = _sign(_canonical(data), self.SECRET)
        result = mgr.validate_webhook_signature(data, {"X-Mollie-Signature": sig})
        self.assertTrue(result)

    def test_forged_signature_rejected(self):
        """KEY SECURITY ASSERTION: a forged signature must be rejected."""
        mgr = _make_manager(self._full_settings())
        data = {"id": "tr_abc", "amount": "10.00"}
        forged = "0" * 64  # plausible-length but wrong hex
        result = mgr.validate_webhook_signature(data, {"X-Mollie-Signature": forged})
        self.assertFalse(result)

    def test_signature_for_different_payload_rejected(self):
        """A valid signature over OTHER data must not validate this payload."""
        mgr = _make_manager(self._full_settings())
        other_sig = _sign(_canonical({"id": "tr_other"}), self.SECRET)
        result = mgr.validate_webhook_signature(
            {"id": "tr_abc"}, {"X-Mollie-Signature": other_sig}
        )
        self.assertFalse(result)

    def test_signature_with_wrong_secret_rejected(self):
        """Signature computed with the wrong secret must be rejected."""
        mgr = _make_manager(self._full_settings())
        data = {"id": "tr_abc"}
        wrong = _sign(_canonical(data), "attacker-guessed-secret")
        result = mgr.validate_webhook_signature(data, {"X-Mollie-Signature": wrong})
        self.assertFalse(result)

    def test_uppercase_header_accepted(self):
        mgr = _make_manager(self._full_settings())
        data = {"id": "tr_h"}
        sig = _sign(_canonical(data), self.SECRET)
        self.assertTrue(mgr.validate_webhook_signature(data, {"X-Mollie-Signature": sig}))

    def test_lowercase_header_accepted(self):
        mgr = _make_manager(self._full_settings())
        data = {"id": "tr_h"}
        sig = _sign(_canonical(data), self.SECRET)
        self.assertTrue(mgr.validate_webhook_signature(data, {"x-mollie-signature": sig}))

    def test_non_dict_payload_uses_str(self):
        """Non-dict request_data is signed via str(request_data)."""
        mgr = _make_manager(self._full_settings())
        raw = "id=tr_raw&status=paid"
        sig = _sign(str(raw), self.SECRET)
        self.assertTrue(mgr.validate_webhook_signature(raw, {"X-Mollie-Signature": sig}))

    def test_non_dict_payload_wrong_sig_rejected(self):
        mgr = _make_manager(self._full_settings())
        raw = "id=tr_raw&status=paid"
        self.assertFalse(mgr.validate_webhook_signature(raw, {"X-Mollie-Signature": "deadbeef"}))


class TestCalculateSignature(unittest.TestCase):
    def test_matches_hand_computed(self):
        mgr = _make_manager({})
        payload = '{"a":1,"b":2}'
        secret = "k3y"
        expected = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        self.assertEqual(mgr._calculate_signature(payload, secret), expected)

    def test_deterministic(self):
        mgr = _make_manager({})
        a = mgr._calculate_signature("p", "s")
        b = mgr._calculate_signature("p", "s")
        self.assertEqual(a, b)
        self.assertEqual(len(a), 64)  # sha256 hexdigest length


class TestWebhookOriginValidation(unittest.TestCase):
    def _settings(self, allowed_ips):
        return {
            "webhook_secret": "x",
            "verify_ssl": True,
            "allowed_ips": allowed_ips,
            "signature_validation": True,
        }

    def test_no_allowed_ips_returns_true(self):
        mgr = _make_manager(self._settings([]))
        self.assertTrue(mgr.validate_webhook_origin({"X-Forwarded-For": "1.2.3.4"}))

    def test_client_ip_in_list_returns_true(self):
        mgr = _make_manager(self._settings(["1.2.3.4", "5.6.7.8"]))
        self.assertTrue(mgr.validate_webhook_origin({"X-Forwarded-For": "5.6.7.8"}))

    def test_client_ip_not_in_list_returns_false(self):
        mgr = _make_manager(self._settings(["1.2.3.4"]))
        self.assertFalse(mgr.validate_webhook_origin({"X-Forwarded-For": "9.9.9.9"}))

    def test_cidr_match_returns_true(self):
        mgr = _make_manager(self._settings(["10.0.0.0/8"]))
        self.assertTrue(mgr.validate_webhook_origin({"X-Forwarded-For": "10.1.2.3"}))

    def test_cidr_no_match_returns_false(self):
        mgr = _make_manager(self._settings(["10.0.0.0/8"]))
        self.assertFalse(mgr.validate_webhook_origin({"X-Forwarded-For": "192.168.1.1"}))

    def test_could_not_determine_ip_returns_false(self):
        mgr = _make_manager(self._settings(["1.2.3.4"]))
        with patch(f"{SECURITY_MODULE}.frappe.log_error"):
            self.assertFalse(mgr.validate_webhook_origin({}))


class TestGetClientIP(unittest.TestCase):
    def setUp(self):
        self.mgr = _make_manager({})

    def test_first_of_comma_separated_xff(self):
        ip = self.mgr._get_client_ip({"X-Forwarded-For": "203.0.113.1, 10.0.0.1, 10.0.0.2"})
        self.assertEqual(ip, "203.0.113.1")

    def test_falls_through_header_list(self):
        # No X-Forwarded-For; should pick X-Real-IP
        ip = self.mgr._get_client_ip({"X-Real-IP": "198.51.100.7"})
        self.assertEqual(ip, "198.51.100.7")

    def test_cloudflare_header(self):
        ip = self.mgr._get_client_ip({"CF-Connecting-IP": "198.51.100.9"})
        self.assertEqual(ip, "198.51.100.9")

    def test_remote_addr_fallback(self):
        ip = self.mgr._get_client_ip({"REMOTE_ADDR": "127.0.0.1"})
        self.assertEqual(ip, "127.0.0.1")

    def test_lowercase_header_lookup(self):
        ip = self.mgr._get_client_ip({"x-real-ip": "203.0.113.5"})
        self.assertEqual(ip, "203.0.113.5")

    def test_no_ip_returns_none(self):
        self.assertIsNone(self.mgr._get_client_ip({"User-Agent": "x"}))


class TestIPMatches(unittest.TestCase):
    def setUp(self):
        self.mgr = _make_manager({})

    def test_exact_match(self):
        self.assertTrue(self.mgr._ip_matches("1.2.3.4", "1.2.3.4"))

    def test_exact_no_match(self):
        self.assertFalse(self.mgr._ip_matches("1.2.3.4", "1.2.3.5"))

    def test_cidr_match(self):
        self.assertTrue(self.mgr._ip_matches("172.16.5.5", "172.16.0.0/12"))

    def test_cidr_no_match(self):
        self.assertFalse(self.mgr._ip_matches("10.0.0.1", "172.16.0.0/12"))

    def test_invalid_cidr_falls_back_to_string_compare(self):
        # "not-an-ip/24" raises in ip_network -> falls back to string equality
        self.assertFalse(self.mgr._ip_matches("1.2.3.4", "not-an-ip/24"))
        self.assertTrue(self.mgr._ip_matches("not-an-ip/24", "not-an-ip/24"))


class TestLogSecurityEvent(unittest.TestCase):
    def setUp(self):
        self.mgr = _make_manager({})

    def test_error_severity_calls_log_error(self):
        with patch(f"{SECURITY_MODULE}.frappe.log_error") as log_error, \
             patch(f"{SECURITY_MODULE}.frappe.logger") as logger:
            self.mgr.log_security_event("breach", {"k": "v"}, severity="error")
        log_error.assert_called_once()
        logger.assert_not_called()

    def test_warning_severity_calls_logger_warning(self):
        fake_logger = MagicMock()
        with patch(f"{SECURITY_MODULE}.frappe.logger", return_value=fake_logger), \
             patch(f"{SECURITY_MODULE}.frappe.log_error") as log_error:
            self.mgr.log_security_event("suspicious", {"k": "v"}, severity="warning")
        fake_logger.warning.assert_called_once()
        log_error.assert_not_called()

    def test_info_severity_calls_logger_info(self):
        fake_logger = MagicMock()
        with patch(f"{SECURITY_MODULE}.frappe.logger", return_value=fake_logger):
            self.mgr.log_security_event("ok", {"k": "v"}, severity="info")
        fake_logger.info.assert_called_once()

    def test_does_not_raise(self):
        fake_logger = MagicMock()
        with patch(f"{SECURITY_MODULE}.frappe.logger", return_value=fake_logger):
            # Should not raise even with non-serializable detail (default=str)
            self.mgr.log_security_event("ok", {"obj": object()}, severity="info")


class TestAPISecurityManagerValidateApiKey(unittest.TestCase):
    def test_test_key_valid(self):
        r = APISecurityManager.validate_api_key("test_abc123")
        self.assertTrue(r["valid"])
        self.assertEqual(r["environment"], "test")
        self.assertEqual(r["key_type"], "test")

    def test_live_key_valid(self):
        r = APISecurityManager.validate_api_key("live_abc123")
        self.assertTrue(r["valid"])
        self.assertEqual(r["environment"], "live")

    def test_empty_invalid(self):
        r = APISecurityManager.validate_api_key("")
        self.assertFalse(r["valid"])
        self.assertEqual(r["error"], "API key is required")

    def test_bogus_format_invalid(self):
        r = APISecurityManager.validate_api_key("bogus_key")
        self.assertFalse(r["valid"])
        self.assertIn("Invalid API key format", r["error"])


class TestMaskApiKey(unittest.TestCase):
    def test_empty_masked(self):
        self.assertEqual(APISecurityManager.mask_api_key(""), "***")

    def test_short_masked(self):
        self.assertEqual(APISecurityManager.mask_api_key("abc123"), "***")

    def test_long_masked_shows_first_and_last_four(self):
        self.assertEqual(APISecurityManager.mask_api_key("test_1234567890abcd"), "test...abcd")


class TestValidateWebhookUrl(unittest.TestCase):
    def test_empty_invalid(self):
        r = APISecurityManager.validate_webhook_url("")
        self.assertFalse(r["valid"])

    def test_non_localhost_http_invalid(self):
        r = APISecurityManager.validate_webhook_url("http://example.com/webhook")
        self.assertFalse(r["valid"])
        self.assertIn("HTTPS", r["error"])

    def test_http_localhost_valid(self):
        r = APISecurityManager.validate_webhook_url("http://localhost:8000/x")
        self.assertTrue(r["valid"])
        self.assertFalse(r["secure"])

    def test_http_127_valid(self):
        r = APISecurityManager.validate_webhook_url("http://127.0.0.1/x")
        self.assertTrue(r["valid"])

    def test_https_valid_and_secure(self):
        r = APISecurityManager.validate_webhook_url("https://example.com/webhook")
        self.assertTrue(r["valid"])
        self.assertTrue(r["secure"])

    def test_malformed_url_invalid(self):
        # Has https scheme (so passes the HTTPS gate) but host has illegal char
        r = APISecurityManager.validate_webhook_url("https://exa mple.com/webhook")
        self.assertFalse(r["valid"])
        self.assertIn("Invalid webhook URL format", r["error"])

    def test_https_with_port_valid(self):
        r = APISecurityManager.validate_webhook_url("https://example.com:8443/hook")
        self.assertTrue(r["valid"])


class TestValidateMollieWebhookRequest(unittest.TestCase):
    SECRET = "module-func-secret"

    def _fake_settings_object(self):
        """A fake Mollie Settings used by _load_security_settings."""
        obj = MagicMock()
        obj.get_password.return_value = self.SECRET
        # _load_security_settings now resolves the secret via get_webhook_secret()
        # (the test-mode-aware accessor) rather than a phantom webhook_secret field.
        obj.get_webhook_secret.return_value = self.SECRET
        # .get(field, default) mimic: verify_ssl, allowed_webhook_ips, enable_signature_validation
        defaults = {
            "verify_ssl": True,
            "allowed_webhook_ips": "",  # no IP restriction
            "enable_signature_validation": True,
        }
        obj.get.side_effect = lambda field, default=None: defaults.get(field, default)
        obj.test_mode = 0
        return obj

    def test_valid_request_returns_true(self):
        data = {"id": "tr_valid"}
        sig = _sign(_canonical(data), self.SECRET)
        fake = self._fake_settings_object()
        with patch(f"{SECURITY_MODULE}.frappe.get_single", return_value=fake), \
             patch(f"{SECURITY_MODULE}.frappe.logger", return_value=MagicMock()), \
             patch(f"{SECURITY_MODULE}.frappe.session", SimpleNamespace(user="Administrator")):
            result = validate_mollie_webhook_request(data, {"X-Mollie-Signature": sig})
        self.assertTrue(result)

    def test_invalid_signature_raises(self):
        data = {"id": "tr_valid"}
        fake = self._fake_settings_object()
        with patch(f"{SECURITY_MODULE}.frappe.get_single", return_value=fake):
            with self.assertRaises(MollieSecurityError):
                validate_mollie_webhook_request(data, {"X-Mollie-Signature": "wrong"})

    def test_bad_origin_raises(self):
        data = {"id": "tr_valid"}
        sig = _sign(_canonical(data), self.SECRET)
        fake = self._fake_settings_object()
        # Restrict IPs to one that won't match the request's IP
        fake.get.side_effect = lambda field, default=None: {
            "verify_ssl": True,
            "allowed_webhook_ips": "10.0.0.1",
            "enable_signature_validation": True,
        }.get(field, default)
        with patch(f"{SECURITY_MODULE}.frappe.get_single", return_value=fake), \
             patch(f"{SECURITY_MODULE}.frappe.log_error"):
            with self.assertRaises(MollieSecurityError) as ctx:
                validate_mollie_webhook_request(
                    data, {"X-Mollie-Signature": sig, "X-Forwarded-For": "9.9.9.9"}
                )
        self.assertIn("origin not allowed", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
