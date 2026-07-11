# Copyright (c) 2026, Verenigingen
"""create_ideal_order core: reference-agnostic order creation for Payment Plan Payment."""

from unittest.mock import patch

import frappe
from frappe.utils import today

from verenigingen.tests.utils.base import VereningingenTestCase


class TestINGCreateIdealOrder(VereningingenTestCase):
    def _setup_ing_settings(self):
        s = frappe.get_single("ING Checkout Settings")
        s.enabled = 1
        s.sandbox_mode = 1
        s.service_id = "SL-0000-0000"
        s.token_code = "AT-0000-0000"
        s.api_token = "test-token"
        s.flags.ignore_validate = True
        s.save(ignore_permissions=True)

    def _create_intent(self):
        intent = frappe.get_doc(
            {
                "doctype": "Payment Plan Payment",
                "installment_number": 1,
                "amount": 40.0,
                "currency": "EUR",
                "status": "Pending",
            }
        ).insert(ignore_permissions=True, ignore_mandatory=True, ignore_links=True)
        self.track_doc("Payment Plan Payment", intent.name)
        return intent

    def test_core_creates_order_with_ppp_reference(self):
        from verenigingen.verenigingen_payments.ing_checkout.api import payment as ing_payment

        self._setup_ing_settings()
        intent = self._create_intent()

        fake_response = {"id": "EX-1234-5678", "links": {"redirect": "https://pay.nl/checkout/EX-1234-5678"}}
        with patch.object(ing_payment, "get_client") as get_client:
            get_client.return_value.create_order.return_value = fake_response
            result = ing_payment.create_ideal_order(
                reference_doctype="Payment Plan Payment",
                reference_name=intent.name,
                amount=40.0,
                description="Payment plan installment",
            )
            # Reference passed to Pay.nl uses the PPP code.
            order_data = get_client.return_value.create_order.call_args[0][0]
            self.assertEqual(order_data["reference"], f"PPP:{intent.name}")

        self.assertTrue(result["success"])
        self.assertEqual(result["transaction_id"], "EX-1234-5678")
        self.assertEqual(result["redirect_url"], "https://pay.nl/checkout/EX-1234-5678")
        # An ING Checkout Transaction now references the intent.
        txn = frappe.get_all(
            "ING Checkout Transaction",
            filters={"transaction_id": "EX-1234-5678"},
            fields=["reference_doctype", "reference_name"],
        )
        self.assertEqual(txn[0].reference_doctype, "Payment Plan Payment")
        self.assertEqual(txn[0].reference_name, intent.name)
        self.track_doc(
            "ING Checkout Transaction",
            frappe.db.get_value("ING Checkout Transaction", {"transaction_id": "EX-1234-5678"}, "name"),
        )
