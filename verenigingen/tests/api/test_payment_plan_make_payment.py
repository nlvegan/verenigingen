# Copyright (c) 2026, Verenigingen
"""initiate_installment_payment: ownership, payable-state, and initiation."""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.utils.base import VereningingenTestCase


class TestPaymentPlanMakePayment(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.member = self._make_member_with_user()
        self.plan = self._make_active_plan(self.member.name)

    def _make_member_with_user(self):
        email = f"ppay-{frappe.generate_hash(length=6)}@example.com"
        member = frappe.new_doc("Member")
        member.first_name = "Pay"
        member.last_name = "Member"
        member.email = email
        member.member_since = today()
        member.save(ignore_permissions=True)
        self.track_doc("Member", member.name)
        if not frappe.db.exists("User", email):
            user = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": "Pay",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert(ignore_permissions=True)
            self.track_doc("User", user.name)
        member.db_set("user", email)
        member.db_set("email", email)
        return member

    def _make_active_plan(self, member_name):
        plan = frappe.new_doc("Payment Plan")
        plan.member = member_name
        plan.plan_type = "Equal Installments"
        plan.total_amount = 120.0
        plan.number_of_installments = 3
        plan.frequency = "Monthly"
        plan.start_date = today()
        plan.status = "Active"
        plan.reason = "test"
        plan.payment_method = "Bank Transfer"
        plan.save(ignore_permissions=True)
        self.track_doc("Payment Plan", plan.name)
        return plan

    def _spy_initiate(self):
        # Stub the gateway boundary: PaymentHook.initiate_payment returns a redirect
        # without touching Mollie. Returns the captured kwargs for assertions.
        captured = {}

        def _fake(**kwargs):
            captured.update(kwargs)
            return {
                "success": True,
                "action": "redirect",
                "payment_id": "tr_test",
                "data": {},
                "redirect_url": "https://mollie/checkout",
            }

        return captured, _fake

    def _setup_installment_status(self, plan_name, index, status, due_date=None):
        # Test-setup helper: arranges installment state directly (bypassing
        # permissions is appropriate here since we are priming fixture data,
        # not exercising the permission boundary under test).
        plan = frappe.get_doc("Payment Plan", plan_name)
        plan.installments[index].status = status
        if due_date is not None:
            plan.installments[index].due_date = due_date
        plan.save(ignore_permissions=True)

    def test_rejects_plan_not_owned_by_caller(self):
        from verenigingen.api.payment_plan_management import initiate_installment_payment

        other = self._make_member_with_user()
        with self.as_user(other.email):
            result = initiate_installment_payment(plan=self.plan.name, installment_number=1)
        self.assertFalse(result["success"])

    def test_rejects_paid_installment(self):
        from verenigingen.api.payment_plan_management import initiate_installment_payment

        # Mark installment 1 Paid directly.
        self._setup_installment_status(self.plan.name, 0, "Paid")
        with self.as_user(self.member.email):
            result = initiate_installment_payment(plan=self.plan.name, installment_number=1)
        self.assertFalse(result["success"])

    def test_happy_path_creates_intent_and_returns_redirect(self):
        from verenigingen.api import payment_plan_management as m

        captured, fake = self._spy_initiate()
        with (
            patch.object(m.PaymentHook, "initiate_payment", side_effect=fake),
            self.as_user(self.member.email),
        ):
            result = m.initiate_installment_payment(plan=self.plan.name, installment_number=1)
        self.assertTrue(result["success"], result)
        data = result.get("data") or result
        self.assertEqual(data["redirect_url"], "https://mollie/checkout")
        # Intent created for installment 1 with the installment amount.
        intent_name = data["intent"]
        self.track_doc("Payment Plan Payment", intent_name)
        intent = frappe.get_doc("Payment Plan Payment", intent_name)
        self.assertEqual(intent.installment_number, 1)
        self.assertEqual(intent.amount, 40.0)  # 120 / 3
        self.assertEqual(intent.status, "Pending")
        # description threaded (not "Donation ...")
        self.assertIn("Payment plan", captured["description"])
        self.assertNotIn("Donation", captured["description"])

    def test_overdue_installment_is_payable(self):
        from verenigingen.api import payment_plan_management as m

        self._setup_installment_status(self.plan.name, 0, "Overdue", due_date=add_days(today(), -10))

        _captured, fake = self._spy_initiate()
        with (
            patch.object(m.PaymentHook, "initiate_payment", side_effect=fake),
            self.as_user(self.member.email),
        ):
            result = m.initiate_installment_payment(plan=self.plan.name, installment_number=1)
        self.assertTrue(result["success"], result)
        self.track_doc("Payment Plan Payment", (result.get("data") or result)["intent"])
