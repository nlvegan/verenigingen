"""
#2591: `BankAPIClient.fetch_statements` reports a Timeout or ConnectionError from the
bank as a failure with a specific message, never as success.

Driven through the real method with `requests.get` replaced at the IO boundary. No
Bank Integration Settings row exists on a test site (the DocType never installs: its
module "Verenigingen Utils" is not in modules.txt, #2881), so the settings lookup is
stood in for exactly as `test_client_ip_sources.TestBankPsuIp` does, with no DDL and no
cleanup.

Lives under tests/security/ for the same reason that precedent does: the test-quality
enforcer's Tier 2 refuses `patch("frappe.db.exists")` outright (no per-site marker
exists on develop until #2838 merges), while Tier 3 accepts it with a
`# Mock justified:` reason. Move it next to the other BankAPIClient tests in
tests/payment/test_bank_integration.py once the marker lands.
"""

from unittest.mock import patch

import frappe
import requests

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen_payments.utils.bank_integration import BankAPIClient


class TestBankApiTransportFailures(VereningingenTestCase):
    def _fetch_with_transport(self, **requests_get_kwargs):
        settings = frappe._dict(api_endpoint="https://bank.invalid", account_id="ACC1", access_token="")
        with (
            # Mock justified: External Service - the bank HTTP API (requests.get) is the boundary under
            # observation; the two frappe patches only stand in for a settings row that test sites lack.
            patch("frappe.get_single", return_value=settings),  # Mock justified: no settings row on test sites
            patch("frappe.db.exists", return_value=True),  # Mock justified: same
            patch("requests.get", **requests_get_kwargs) as fake_get,  # Mock justified: External Service
        ):
            result = BankAPIClient().fetch_statements("2025-03-15")
        return result, fake_get

    def test_a_request_timeout_is_reported_as_a_timeout(self):
        result, fake_get = self._fetch_with_transport(side_effect=requests.exceptions.Timeout())
        self.assertEqual(fake_get.call_count, 1, "premise: the request was attempted")
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "Bank API request timeout - please try again later")

    def test_a_connection_error_is_reported_as_a_connection_error(self):
        result, fake_get = self._fetch_with_transport(side_effect=requests.exceptions.ConnectionError())
        self.assertEqual(fake_get.call_count, 1, "premise: the request was attempted")
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "Cannot connect to bank API - please check network connection")

    def test_a_generic_failure_takes_neither_transport_handler(self):
        """Control: an unrelated exception reaches the catch-all, so the two messages above
        really belong to their own handlers."""
        self.expectErrorLog("Bank API integration error: boom")
        result, _ = self._fetch_with_transport(side_effect=ValueError("boom"))
        self.assertFalse(result["success"])
        self.assertTrue(result["error"].startswith("Unexpected error"), result)
