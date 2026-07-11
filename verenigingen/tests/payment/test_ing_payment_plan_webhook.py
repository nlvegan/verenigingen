# Copyright (c) 2026, Verenigingen
"""Pay.nl webhook -> payment-plan installment finalization."""

import frappe
from frappe.utils import today

from verenigingen.tests.utils.base import VereningingenTestCase


def _order_payload(order_id, intent_name, status_code=100):
    return {
        "id": order_id,
        "object": {
            "reference": f"PPP:{intent_name}",
            "status": {"code": status_code, "action": "PAID" if status_code == 100 else "OTHER"},
            "amount": {"value": 4000, "currency": "EUR"},
        },
    }


class TestINGPaymentPlanWebhook(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        # authenticate_webhook() calls frappe.set_user() for the rest of the
        # request; save/restore so it doesn't leak into other tests or disturb
        # track_doc cleanup (which runs as the original test session user).
        self._orig_session_user = frappe.session.user
        self.member = self._create_member()
        self.plan = self._create_plan(self.member.name)

    def tearDown(self):
        frappe.set_user(self._orig_session_user)
        super().tearDown()

    def _create_member(self):
        m = frappe.new_doc("Member")
        m.first_name = "IngHook"
        m.last_name = "Member"
        m.email = f"inghook-{frappe.generate_hash(length=6)}@example.com"
        m.member_since = today()
        m.save(ignore_permissions=True)
        self.track_doc("Member", m.name)
        return m

    def _create_plan(self, member_name):
        p = frappe.new_doc("Payment Plan")
        p.member = member_name
        p.plan_type = "Equal Installments"
        p.total_amount = 120.0
        p.number_of_installments = 3
        p.frequency = "Monthly"
        p.start_date = today()
        p.status = "Active"
        p.reason = "test"
        p.payment_method = "Bank Transfer"
        p.save(ignore_permissions=True)
        self.track_doc("Payment Plan", p.name)
        return p

    def _create_intent(self, payment_id="EX-hook"):
        intent = frappe.get_doc(
            {
                "doctype": "Payment Plan Payment",
                "payment_plan": self.plan.name,
                "installment_number": 1,
                "amount": 40.0,
                "currency": "EUR",
                "member": self.member.name,
                "gateway": "Pay.nl",
                "status": "Pending",
                "payment_id": payment_id,
            }
        ).insert(ignore_permissions=True)
        self.track_doc("Payment Plan Payment", intent.name)
        return intent

    def test_paid_webhook_finalizes_installment(self):
        from verenigingen.verenigingen_payments.ing_checkout.api.webhook import (
            _maybe_finalize_payment_plan,
        )

        intent = self._create_intent(payment_id="EX-paid")
        handled = _maybe_finalize_payment_plan("EX-paid", _order_payload("EX-paid", intent.name, 100))
        self.assertTrue(handled)  # dispatch consumed the webhook
        intent.reload()
        self.assertEqual(intent.status, "Paid")
        plan = frappe.get_doc("Payment Plan", self.plan.name)
        self.assertEqual(plan.installments[0].status, "Paid")

    def test_non_plan_reference_not_handled(self):
        from verenigingen.verenigingen_payments.ing_checkout.api.webhook import (
            _maybe_finalize_payment_plan,
        )

        payload = {
            "id": "EX-si",
            "object": {
                "reference": "SINV:ACC-SINV-2025-00001",
                "status": {"code": 100},
                "amount": {"value": 100, "currency": "EUR"},
            },
        }
        self.assertFalse(_maybe_finalize_payment_plan("EX-si", payload))

    def test_failed_webhook_leaves_installment_payable(self):
        from verenigingen.verenigingen_payments.ing_checkout.api.webhook import (
            _maybe_finalize_payment_plan,
        )

        intent = self._create_intent(payment_id="EX-fail")
        handled = _maybe_finalize_payment_plan("EX-fail", _order_payload("EX-fail", intent.name, -63))
        self.assertTrue(handled)
        intent.reload()
        self.assertEqual(intent.status, "Failed")
        plan = frappe.get_doc("Payment Plan", self.plan.name)
        self.assertEqual(plan.installments[0].status, "Pending")
