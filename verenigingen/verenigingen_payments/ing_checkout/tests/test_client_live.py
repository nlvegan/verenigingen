# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt
"""
Live integration coverage for PayNLClient against Pay.nl's REAL sandbox API.

Analogous to mollie/tests/test_subscription_service_live.py: the sibling
test_client.py / test_api.py suites exercise the client with mocked HTTP
responses; this module verifies the real HTTP + Basic-Auth + response-handling
stack end-to-end against Pay.nl's sandbox.

Gating: the suite needs the Pay.nl sandbox credentials. They are read from site
config (``paynl_test_service_id`` / ``paynl_test_token_code`` /
``paynl_test_api_token`` in common_site_config.json, never committed) by
ensure_ing_checkout_test_credentials(). When they are absent — e.g. CI without
the credentials — every test skips, so the module stays green.

SCOPE / WHAT IS NOT COVERED HERE
--------------------------------
Unlike the Mollie sandbox (which permits the full customer -> mandate ->
subscription lifecycle), the Pay.nl sandbox *service* behind these credentials
only grants access to the read-only Service:GetConfig endpoint. Verified against
the live sandbox on 2026-06-12:
  - Service:GetConfig (test_connection)          -> 200 OK
  - directdebits/mandates  create (valid body)   -> 403 Access denied
  - directdebits/mandates  list                  -> 403 Access denied
  - orders (TGU, connect.pay.nl) create          -> 403 Forbidden (web-server level)
So a live mandate/order lifecycle cannot be reproduced from here. Those paths
stay covered by the mocked unit suites; see the handoff note for what Pay.nl
would need to enable for live lifecycle coverage.
"""

from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.ing_checkout.client import PayNLClient, get_client
from verenigingen.verenigingen_payments.ing_checkout.tests.fixtures.ing_checkout_test_helper import (
    ensure_ing_checkout_test_credentials,
)
from verenigingen.verenigingen_payments.ing_checkout.tests.test_client import MockSettings

_SKIP_MSG = "No Pay.nl sandbox credentials configured (paynl_test_* in site config)"


class TestPayNLClientLive(FrappeTestCase):
    """PayNLClient against the real Pay.nl sandbox (skips without credentials)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Commits the sandbox credentials into ING Checkout Settings once for the class.
        cls.has_credentials = ensure_ing_checkout_test_credentials()

    def setUp(self):
        super().setUp()
        if not self.has_credentials:
            self.skipTest(_SKIP_MSG)

    def test_test_connection_succeeds_against_sandbox(self):
        """test_connection authenticates and reads the service config from the real
        sandbox — exercises Basic-Auth header construction, the GMS base URL and
        the services/config serviceId-as-query-param contract end-to-end."""
        client = get_client()

        result = client.test_connection()

        self.assertTrue(result["success"], msg=result.get("message"))
        # The sandbox returns the configured service's real name.
        self.assertTrue(result.get("service_name"))
        self.assertNotEqual(result["service_name"], "Unknown")

    def test_get_client_uses_configured_sandbox_credentials(self):
        """get_client() builds a client whose credentials come from the (now
        test-populated) ING Checkout Settings singleton, in sandbox mode."""
        client = get_client()

        credentials = client.settings.get_api_credentials()

        self.assertTrue(credentials["sandbox_mode"])
        self.assertTrue(credentials["service_id"].startswith("SL-"))
        self.assertTrue(credentials["token_code"].startswith("AT-"))
        self.assertTrue(credentials["api_token"])

    def test_invalid_credentials_rejected_by_live_api(self):
        """A client carrying a real service_id but a bogus token is rejected by the
        real sandbox — proves the success above is genuine auth, not a happy-path
        stub. test_connection() catches the auth error and reports failure."""
        good = get_client().settings.get_api_credentials()
        bad_settings = MockSettings(
            service_id=good["service_id"],
            token_code=good["token_code"],
            api_token="bogus_token_that_will_not_authenticate",
        )
        client = PayNLClient(settings=bad_settings)

        result = client.test_connection()

        self.assertFalse(result["success"])
        self.assertIn("failed", result["message"].lower())
