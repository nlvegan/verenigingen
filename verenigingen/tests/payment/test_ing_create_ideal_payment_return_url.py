# Copyright (c) 2026, Verenigingen
"""The whitelisted create_ideal_payment must not let a caller pick the Pay.nl returnUrl (#2568).

Same class as #2513 (Mollie). Only the Pay.nl HTTP client is stubbed; the request is driven
through ``frappe.call`` (which drops arguments the endpoint does not declare, as the HTTP
handler does) so the real wrapper, its security decorator and ``create_ideal_order`` all run.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.parse import urlsplit

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.ing_return import _GET_CLIENT, _SETTINGS_PATH

ENDPOINT = "verenigingen.verenigingen_payments.ing_checkout.api.payment.create_ideal_payment"
EVIL = "https://evil.example.org/phish"


class TestCreateIdealPaymentReturnUrl(EnhancedTestCase):
    def _post(self, settings_return_url=None, **extra):
        client = MagicMock()
        order_id = f"EX-{frappe.generate_hash(length=4)}-5678-9012"
        client.create_order.return_value = {
            "id": order_id,
            "links": {"redirect": "https://connect.pay.nl/checkout/abc"},
        }
        settings = SimpleNamespace(default_return_url=settings_return_url, service_id="SL-1234-5678")
        doc = frappe.get_doc({"doctype": "ToDo", "description": "ing return url probe"}).insert()
        self.track_doc("ToDo", doc.name)
        with patch(_SETTINGS_PATH, return_value=settings), patch(_GET_CLIENT, return_value=client):
            result = frappe.call(
                ENDPOINT,
                reference_doctype="ToDo",
                reference_name=doc.name,
                amount=10.0,
                description="probe",
                **extra,
            )
        txn = frappe.db.get_value("ING Checkout Transaction", {"transaction_id": order_id}, "name")
        if txn:
            self.track_doc("ING Checkout Transaction", txn)
        self.assertTrue(result.get("success"), result)
        return client.create_order.call_args[0][0]["returnUrl"], txn

    def test_endpoint_is_whitelisted(self):
        from verenigingen.verenigingen_payments.ing_checkout.api import payment

        self.assertIn(payment.create_ideal_payment, frappe.whitelisted)

    def test_caller_supplied_return_url_never_reaches_pay_nl(self):
        sent, txn = self._post(return_url=EVIL)
        self.assertNotIn("evil.example.org", sent)
        self.assertEqual(urlsplit(sent).path, "/payment_success")
        self.assertIn("token=", sent)  # control: our own page, with its return token
        self.assertNotIn("evil.example.org", frappe.db.get_value("ING Checkout Transaction", txn, "return_url"))

    def test_without_return_url_the_default_page_is_used(self):
        sent, _txn = self._post()
        self.assertEqual(urlsplit(sent).path, "/payment_success")
        self.assertIn("token=", sent)

    def test_admin_configured_default_return_url_still_wins(self):
        sent, _txn = self._post("https://example.org/ing-back", return_url=EVIL)
        self.assertEqual(sent, "https://example.org/ing-back")
