# Copyright (c) 2026, Verenigingen
"""ING Checkout wired into PaymentHook (ing_ideal method)."""

from unittest.mock import patch

import frappe

from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.hooks.payment_hook import PaymentHook


class TestPaymentHookING(FrappeTestCase):
    def test_ing_ideal_listed_when_enabled(self):
        with patch(
            "verenigingen.verenigingen_payments.hooks.payment_hook.PaymentHook._get_ing_config",
            return_value={"available": True},
        ):
            methods = PaymentHook.get_available_methods()
        self.assertTrue(any(m["id"] == "ing_ideal" for m in methods))

    def test_ing_ideal_absent_when_disabled(self):
        with patch(
            "verenigingen.verenigingen_payments.hooks.payment_hook.PaymentHook._get_ing_config",
            return_value={"available": False},
        ):
            methods = PaymentHook.get_available_methods()
        self.assertFalse(any(m["id"] == "ing_ideal" for m in methods))

    def test_initiate_ing_ideal_normalizes_redirect(self):
        methods = [{"id": "ing_ideal", "label": "iDEAL via ING/Pay.nl"}]
        with (
            patch.object(PaymentHook, "get_available_methods", return_value=methods),
            patch(
                "verenigingen.verenigingen_payments.hooks.payment_hook.frappe.get_doc",
                return_value=frappe._dict(doctype="Payment Plan Payment", name="PPP-x"),
            ),
            patch(
                "verenigingen.verenigingen_payments.ing_checkout.api.payment.create_ideal_order",
                return_value={"success": True, "transaction_id": "EX-1", "redirect_url": "https://pay.nl/x"},
            ),
        ):
            result = PaymentHook.initiate_payment(
                method="ing_ideal",
                amount=40.0,
                reference_doctype="Payment Plan Payment",
                reference_name="PPP-x",
                payer_info={"email": "a@b.nl", "name": "A B"},
                description="Payment plan installment",
            )
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "redirect")
        self.assertEqual(result["data"]["url"], "https://pay.nl/x")
        self.assertEqual(result["payment_id"], "EX-1")

    def test_initiate_ing_ideal_surfaces_order_failure(self):
        """Regression (A3 phase 2 final review): create_ideal_order() catches
        errors internally and returns {"success": False, "message": ...} with
        no redirect_url/transaction_id. INGCheckoutGateway must surface that
        as a failure instead of normalizing it into a fake redirect with a
        null url (which previously reported "payment started" for a payment
        that never started).
        """
        methods = [{"id": "ing_ideal", "label": "iDEAL via ING/Pay.nl"}]
        with (
            patch.object(PaymentHook, "get_available_methods", return_value=methods),
            patch(
                "verenigingen.verenigingen_payments.hooks.payment_hook.frappe.get_doc",
                return_value=frappe._dict(doctype="Payment Plan Payment", name="PPP-x"),
            ),
            patch(
                "verenigingen.verenigingen_payments.ing_checkout.api.payment.create_ideal_order",
                return_value={"success": False, "message": "boom"},
            ),
        ):
            result = PaymentHook.initiate_payment(
                method="ing_ideal",
                amount=40.0,
                reference_doctype="Payment Plan Payment",
                reference_name="PPP-x",
                payer_info={"email": "a@b.nl", "name": "A B"},
                description="Payment plan installment",
            )
        self.assertFalse(result["success"])
        self.assertNotEqual(result.get("action"), "redirect")
        self.assertIsNone((result.get("data") or {}).get("url"))
