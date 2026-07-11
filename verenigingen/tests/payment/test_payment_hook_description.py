# Copyright (c) 2026, Verenigingen
"""initiate_payment must forward `description` to the gateway as description_override."""

from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.hooks.payment_hook import PaymentHook


class _SpyGateway:
    """Captures the form_data handed to the gateway."""

    def __init__(self):
        self.captured = None

    def process_payment(self, ref_doc, form_data):
        self.captured = form_data
        return {"status": "redirect_required", "redirect_url": "https://x", "payment_id": "tr_1"}


class TestInitiatePaymentDescription(FrappeTestCase):
    def test_description_forwarded_as_description_override(self):
        spy = _SpyGateway()
        methods = [{"id": "mollie", "label": "Online Payment"}]
        with (
            patch.object(PaymentHook, "get_available_methods", return_value=methods),
            patch(
                "verenigingen.verenigingen_payments.hooks.payment_hook.PaymentGatewayFactory.get_gateway",
                return_value=spy,
            ),
            patch(
                "verenigingen.verenigingen_payments.hooks.payment_hook.frappe.get_doc",
                return_value=object(),
            ),
        ):
            PaymentHook.initiate_payment(
                method="mollie",
                amount=40.0,
                reference_doctype="Payment Plan Payment",
                reference_name="PPP-x",
                payer_info={"email": "a@b.nl", "name": "A B"},
                description="Payment plan PP-1 installment 2",
            )
        self.assertIsNotNone(spy.captured, "gateway was not called")
        self.assertEqual(spy.captured.get("description_override"), "Payment plan PP-1 installment 2")
