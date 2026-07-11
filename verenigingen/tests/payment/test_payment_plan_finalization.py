# Copyright (c) 2026, Verenigingen
"""Gateway-agnostic installment finalizer (shared by Mollie + Pay.nl)."""

import frappe
from frappe.utils import today

from verenigingen.tests.utils.base import VereningingenTestCase


class TestPaymentPlanFinalization(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.member = self._create_member()
        self.plan = self._create_plan(self.member.name)

    def _create_member(self):
        m = frappe.new_doc("Member")
        m.first_name = "Fin"
        m.last_name = "Member"
        m.email = f"fin-{frappe.generate_hash(length=6)}@example.com"
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

    def _create_intent(self, installment_number=1, amount=40.0, payment_id="ref_1"):
        intent = frappe.get_doc(
            {
                "doctype": "Payment Plan Payment",
                "payment_plan": self.plan.name,
                "installment_number": installment_number,
                "amount": amount,
                "currency": "EUR",
                "member": self.member.name,
                "gateway": "Pay.nl",
                "status": "Pending",
                "payment_id": payment_id,
            }
        ).insert(ignore_permissions=True)
        self.track_doc("Payment Plan Payment", intent.name)
        return intent

    def test_paid_finalizes_installment_and_intent(self):
        from verenigingen.verenigingen_payments.services.payment_plan_finalization import (
            finalize_payment_plan_installment,
        )

        intent = self._create_intent(payment_id="ref_paid")
        result = finalize_payment_plan_installment(intent.name, payment_reference="ref_paid", status="paid")
        self.assertEqual(result["status"], "success")
        intent.reload()
        self.assertEqual(intent.status, "Paid")
        plan = frappe.get_doc("Payment Plan", self.plan.name)
        self.assertEqual(plan.installments[0].status, "Paid")

    def test_duplicate_is_skipped(self):
        from verenigingen.verenigingen_payments.services.payment_plan_finalization import (
            finalize_payment_plan_installment,
        )

        intent = self._create_intent(payment_id="ref_dup")
        finalize_payment_plan_installment(intent.name, payment_reference="ref_dup", status="paid")
        result = finalize_payment_plan_installment(intent.name, payment_reference="ref_dup", status="paid")
        self.assertEqual(result["status"], "skipped")

    def test_failed_leaves_installment_payable(self):
        from verenigingen.verenigingen_payments.services.payment_plan_finalization import (
            finalize_payment_plan_installment,
        )

        intent = self._create_intent(payment_id="ref_fail")
        result = finalize_payment_plan_installment(intent.name, payment_reference="ref_fail", status="failed")
        self.assertEqual(result["status"], "skipped")
        intent.reload()
        self.assertEqual(intent.status, "Failed")
        plan = frappe.get_doc("Payment Plan", self.plan.name)
        self.assertEqual(plan.installments[0].status, "Pending")
