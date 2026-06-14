"""
Live integration coverage for MollieGateway against Mollie's REAL test API.

These cover the gateway paths that genuinely require a live Mollie call and so
cannot be exercised by the unit tests: constructing the gateway from real Mollie
Settings, building a real client, and reading a real payment's status via
MollieGateway.get_payment_status / handle_webhook.

Gating: needs a Mollie TEST secret key (mollie_test_secret_key in
common_site_config.json, never committed) loaded by ensure_mollie_test_credentials().
Without it every test skips, so the module stays green in CI.

Test IBAN that yields a valid mandate: NL39RABO0300065264.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.tests.mollie_test_helper import (
    ensure_mollie_test_credentials,
)
from verenigingen.verenigingen_payments.utils.payment_gateways import MollieGateway


class TestMollieGatewayLive(EnhancedTestCase):
    """MollieGateway against the real Mollie test API (skips without a key)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.has_credentials = ensure_mollie_test_credentials()

    def setUp(self):
        super().setUp()
        if not self.has_credentials:
            self.skipTest("No Mollie test key configured (mollie_test_secret_key in site config)")
        self.gateway = MollieGateway("Default")
        self._payment_ids = []

    def _create_payment(self, amount="12.00"):
        site_url = frappe.utils.get_url()
        payment = self.gateway.client.payments.create(
            {
                "amount": {"currency": "EUR", "value": amount},
                "description": "Gateway live test payment",
                "redirectUrl": f"{site_url}/payment-return",
                "webhookUrl": f"{site_url}/api/method/ping",
                "metadata": {"test": "gateway_live"},
            }
        )
        self._payment_ids.append(payment.id)
        return payment

    def test_gateway_constructs_with_real_settings(self):
        # __init__ resolved real Mollie Settings and built a client.
        self.assertIsNotNone(self.gateway.settings)
        self.assertIsNotNone(self.gateway.client)

    def test_get_payment_status_of_fresh_payment(self):
        payment = self._create_payment()
        result = self.gateway.get_payment_status(payment.id)
        # A freshly created, unpaid payment is Open (awaiting completion).
        self.assertIn(result["status"], ("Open", "Pending"))
        self.assertIn("message", result)

    def test_get_payment_status_unknown_id_errors(self):
        result = self.gateway.get_payment_status("tr_definitely_not_real")
        self.assertEqual(result["status"], "Error")

    def test_handle_webhook_no_reference_metadata_ignored(self):
        # Real payment carries our metadata (no reference_doctype/docname), so the
        # webhook handler retrieves it from Mollie then ignores it for lack of a
        # reference document - exercising the live get() + ignore branch.
        payment = self._create_payment()
        result = self.gateway.handle_webhook({"id": payment.id})
        self.assertEqual(result["status"], "ignored")
