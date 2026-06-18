# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Additional branch coverage for ING Checkout webhook_security.py.

Complements test_webhook_security.py by hitting branches it does not:
- get_request_ip: X-Forwarded-For (multi-IP), X-Real-IP, remote_addr fallback.
- fetch_paynl_ip_addresses: fresh cache hit (no HTTP), dict {"ipAddresses": [...]}
  and {"data": [...]} response shapes.
- verify_ing_checkout_webhook: secret configured but no signature AND IP not
  validated -> "Missing webhook signature".
"""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from verenigingen.verenigingen_payments.ing_checkout.utils import webhook_security
from verenigingen.verenigingen_payments.ing_checkout.utils.webhook_security import (
    INGCheckoutWebhookError,
    fetch_paynl_ip_addresses,
    get_request_ip,
    verify_ing_checkout_webhook,
)


def _fake_request(headers=None, remote_addr=None):
    """Build a minimal request-like object exposing .headers.get and .remote_addr."""
    headers = headers or {}
    return SimpleNamespace(
        headers=SimpleNamespace(get=lambda key, default=None: headers.get(key, default)),
        remote_addr=remote_addr,
    )


class TestGetRequestIPBranches(FrappeTestCase):
    def _with_request(self, req):
        """Patch frappe.request for the duration of one assertion."""
        import frappe

        return patch.object(frappe, "request", req)

    def test_x_forwarded_for_takes_first_ip(self):
        req = _fake_request(headers={"X-Forwarded-For": "203.0.113.5, 10.0.0.1, 10.0.0.2"})
        with self._with_request(req):
            self.assertEqual(get_request_ip(), "203.0.113.5")

    def test_x_real_ip_used_when_no_forwarded(self):
        req = _fake_request(headers={"X-Real-IP": "198.51.100.9"})
        with self._with_request(req):
            self.assertEqual(get_request_ip(), "198.51.100.9")

    def test_remote_addr_fallback(self):
        req = _fake_request(headers={}, remote_addr="192.0.2.7")
        with self._with_request(req):
            self.assertEqual(get_request_ip(), "192.0.2.7")

    def test_forwarded_for_preferred_over_real_ip(self):
        req = _fake_request(headers={"X-Forwarded-For": "203.0.113.5", "X-Real-IP": "198.51.100.9"})
        with self._with_request(req):
            self.assertEqual(get_request_ip(), "203.0.113.5")


class TestFetchIPAddressesBranches(FrappeTestCase):
    def setUp(self):
        super().setUp()
        # Reset cache before each test.
        webhook_security._paynl_ip_cache = {"ips": [], "last_updated": None}
        self.addCleanup(
            lambda: setattr(webhook_security, "_paynl_ip_cache", {"ips": [], "last_updated": None})
        )

    def test_fresh_cache_short_circuits_without_http(self):
        webhook_security._paynl_ip_cache = {
            "ips": ["1.1.1.1"],
            "last_updated": now_datetime() - timedelta(minutes=10),  # < 1h old
        }
        with patch("requests.get") as mock_get:
            result = fetch_paynl_ip_addresses()
            self.assertEqual(result, ["1.1.1.1"])
            mock_get.assert_not_called()  # cache hit avoids the HTTP call

    def test_stale_cache_triggers_refetch(self):
        webhook_security._paynl_ip_cache = {
            "ips": ["old.ip"],
            "last_updated": now_datetime() - timedelta(hours=2),  # expired
        }
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = [{"ipAddress": "2.2.2.2"}]
        with patch("requests.get", return_value=resp) as mock_get:
            result = fetch_paynl_ip_addresses()
            mock_get.assert_called_once()
            self.assertEqual(result, ["2.2.2.2"])

    def test_dict_ipaddresses_shape(self):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"ipAddresses": ["3.3.3.3", "4.4.4.4"]}
        with patch("requests.get", return_value=resp):
            result = fetch_paynl_ip_addresses()
            self.assertEqual(result, ["3.3.3.3", "4.4.4.4"])

    def test_dict_data_shape(self):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"data": [{"ipAddress": "5.5.5.5"}, {"ipAddress": "6.6.6.6"}]}
        with patch("requests.get", return_value=resp):
            result = fetch_paynl_ip_addresses()
            self.assertEqual(result, ["5.5.5.5", "6.6.6.6"])


class TestVerifyWebhookMissingSignatureBranch(FrappeTestCase):
    @patch("verenigingen.verenigingen_payments.ing_checkout.utils.webhook_security.get_webhook_secret")
    @patch("verenigingen.verenigingen_payments.ing_checkout.utils.webhook_security.get_request_ip")
    @patch("verenigingen.verenigingen_payments.ing_checkout.utils.webhook_security.verify_webhook_ip")
    def test_missing_signature_with_secret_and_unvalidated_ip(
        self, mock_verify_ip, mock_get_ip, mock_get_secret
    ):
        """Secret configured, no signature, IP not validated -> Missing signature error."""
        mock_get_ip.return_value = "9.9.9.9"
        mock_verify_ip.return_value = False
        mock_get_secret.return_value = "configured_secret"

        with self.assertRaises(INGCheckoutWebhookError) as ctx:
            verify_ing_checkout_webhook(b'{"x": 1}', signature=None)
        self.assertIn("missing", ctx.exception.message.lower())
