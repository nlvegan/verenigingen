# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
An iDEAL order for a Payment Plan Payment charges the row's amount, and the paid webhook is
booked only when Pay.nl reports that amount (#3076).

Driven through the real flow: ``create_ideal_payment`` (Pay.nl faked at ``payment.get_client``
and the settings, as in test_payment_amount_3023), then the real ``_maybe_finalize_payment_plan``
with a payload carrying the cents the fake order was asked to collect (or a different figure).
Member / plan / intent fixtures are borrowed from test_ing_payment_plan_webhook.
"""

import frappe
from frappe.utils import flt

from verenigingen.tests.payment import test_ing_payment_plan_webhook as _hook_tests
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen_payments.ing_checkout.api import payment as payment_api
from verenigingen.verenigingen_payments.ing_checkout.api import webhook as webhook_api
from verenigingen.verenigingen_payments.ing_checkout.tests.test_payment_amount_3023 import _Fake3023Mixin

MISMATCH_TITLE = "Payment Plan Payment Amount Mismatch"


class TestIdealPaymentPlanAmount3076(_Fake3023Mixin, VereningingenTestCase):
    _create_member = _hook_tests.TestINGPaymentPlanWebhook._create_member
    _create_plan = _hook_tests.TestINGPaymentPlanWebhook._create_plan
    _create_intent = _hook_tests.TestINGPaymentPlanWebhook._create_intent

    def setUp(self):
        super().setUp()
        self._orig_session_user = frappe.session.user
        frappe.set_user("Administrator")
        self.member = self._create_member()
        self.plan = self._create_plan(self.member.name)
        self.intent = self._create_intent(payment_id="EX-3076")
        self.row_cents = round(flt(self.intent.amount) * 100)
        self._ing3023_fake_pay_nl()

    def tearDown(self):
        frappe.set_user(self._orig_session_user)
        super().tearDown()

    def _order(self, caller_amount):
        result = payment_api.create_ideal_payment(
            "Payment Plan Payment", self.intent.name, caller_amount, "probe"
        )
        self.assertTrue(result["success"], result)
        return result["transaction_id"]

    def _paid_webhook(self, order_id, cents):
        amount = {} if cents is None else {"amount": {"value": cents, "currency": "EUR"}}
        payload = {
            "id": order_id,
            "object": {
                "reference": f"PPP:{self.intent.name}",
                "status": {"code": 100, "action": "PAID"},
                **amount,
            },
        }
        return webhook_api._maybe_finalize_payment_plan(order_id, payload)

    def _intent_status(self):
        return frappe.db.get_value("Payment Plan Payment", self.intent.name, "status")

    def _installment_status(self):
        return frappe.get_doc("Payment Plan", self.plan.name).installments[0].status

    def _mismatch_rows(self):
        return frappe.db.count("Error Log", {"method": MISMATCH_TITLE})

    def test_lower_caller_amount_orders_the_row_amount(self):
        order_id = self._order(1.0)

        self.assertEqual(self._ing3023_charged_cents(), self.row_cents)
        stored = frappe.db.get_value("ING Checkout Transaction", {"transaction_id": order_id}, "amount")
        self.assertEqual(flt(stored), flt(self.intent.amount))

    def test_higher_caller_amount_orders_the_row_amount(self):
        self._order(flt(self.intent.amount) + 50.0)

        self.assertEqual(self._ing3023_charged_cents(), self.row_cents)

    def test_ordered_amount_pays_through_the_webhook_and_books(self):
        """Control: the full flow with an underpaying caller still books the installment."""
        order_id = self._order(1.0)

        self.assertTrue(self._paid_webhook(order_id, self._ing3023_charged_cents()))

        self.assertEqual(self._intent_status(), "Paid")
        self.assertEqual(self._installment_status(), "Paid")

    def test_mismatching_paid_amount_is_flagged_not_booked(self):
        self.expectErrorLog(MISMATCH_TITLE)
        before = self._mismatch_rows()

        self.assertTrue(self._paid_webhook("EX-3076-short", self.row_cents - 1500))

        self.assertEqual(self._intent_status(), "Pending")
        self.assertEqual(self._installment_status(), "Pending")
        self.assertEqual(self._mismatch_rows(), before + 1)
        self.assertNotEqual(frappe.local.response.get("http_status_code"), 500)

    def test_overpaid_amount_is_flagged_too(self):
        self.expectErrorLog(MISMATCH_TITLE)
        before = self._mismatch_rows()

        self._paid_webhook("EX-3076-over", self.row_cents + 100)

        self.assertEqual(self._installment_status(), "Pending")
        self.assertEqual(self._mismatch_rows(), before + 1)

    def test_paid_webhook_without_an_amount_is_not_booked(self):
        self.expectErrorLog(MISMATCH_TITLE)
        before = self._mismatch_rows()

        self._paid_webhook("EX-3076-none", None)

        self.assertEqual(self._installment_status(), "Pending")
        self.assertEqual(self._mismatch_rows(), before + 1)

    def test_matching_amount_books_normally(self):
        before = self._mismatch_rows()

        self._paid_webhook("EX-3076-ok", self.row_cents)

        self.assertEqual(self._installment_status(), "Paid")
        self.assertEqual(self._mismatch_rows(), before)

    def test_unchecked_caller_still_books(self):
        """Control: the Mollie-style call (no paid_amount) is unchanged."""
        from verenigingen.verenigingen_payments.services.payment_plan_finalization import (
            finalize_payment_plan_installment,
        )

        result = finalize_payment_plan_installment(self.intent.name, payment_reference="EX-3076-m")

        self.assertEqual(result["status"], "success")
        self.assertEqual(self._installment_status(), "Paid")
