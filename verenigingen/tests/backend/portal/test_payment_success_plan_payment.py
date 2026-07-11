# Copyright (c) 2026, Verenigingen
"""payment-success must accept a Payment Plan Payment docname."""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase


class TestPaymentSuccessPlanPayment(VereningingenTestCase):
    def _create_test_payment_plan_payment(self):
        """Factory helper: create a Payment Plan Payment for testing."""
        intent = frappe.get_doc(
            {
                "doctype": "Payment Plan Payment",
                "installment_number": 1,
                "amount": 40.0,
                "currency": "EUR",
                "status": "Paid",
                "paid": 1,
                "payment_id": "tr_ok",
            }
        )
        intent.insert(ignore_permissions=True, ignore_mandatory=True, ignore_links=True)
        self.track_doc("Payment Plan Payment", intent.name)
        return intent

    def test_payment_plan_payment_is_allowed_doctype(self):
        from verenigingen.templates.pages.payment_success import ALLOWED_PAYMENT_DOCTYPES

        self.assertIn("Payment Plan Payment", ALLOWED_PAYMENT_DOCTYPES)

    def test_get_context_renders_for_plan_payment(self):
        from verenigingen.templates.pages import payment_success

        intent = self._create_test_payment_plan_payment()

        frappe.form_dict = frappe._dict({"doctype": "Payment Plan Payment", "docname": intent.name})
        context = frappe._dict()
        payment_success.get_context(context)
        # Must NOT be the "invalid document type" error path.
        self.assertNotIn("Invalid document type", str(context.get("error") or ""))
