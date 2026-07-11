# Copyright (c) 2026, Verenigingen
"""Pay page get_context: ownership gating + next payable installment."""

import frappe
from frappe.utils import today

from verenigingen.tests.utils.base import VereningingenTestCase


class TestPagePaymentPlanPay(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.member = self._create_member()
        self.plan = self._create_plan(self.member.name)

    def _create_member(self):
        email = f"pp-{frappe.generate_hash(length=6)}@example.com"
        m = frappe.new_doc("Member")
        m.first_name = "Pp"
        m.last_name = "Member"
        m.email = email
        m.member_since = today()
        m.save(ignore_permissions=True)
        self.track_doc("Member", m.name)
        if not frappe.db.exists("User", email):
            u = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": "Pp",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert(ignore_permissions=True)
            self.track_doc("User", u.name)
        m.db_set("user", email)
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

    def test_owner_sees_next_installment(self):
        from verenigingen.templates.pages import payment_plan_pay

        frappe.form_dict = frappe._dict({"plan": self.plan.name})
        with self.as_user(self.member.email):
            ctx = frappe._dict()
            payment_plan_pay.get_context(ctx)
        self.assertEqual(ctx.plan.name, self.plan.name)
        self.assertIsNotNone(ctx.installment)
        self.assertEqual(ctx.installment["installment_number"], 1)

    def test_non_owner_denied(self):
        from verenigingen.templates.pages import payment_plan_pay

        other = self._create_member()
        frappe.form_dict = frappe._dict({"plan": self.plan.name})
        with self.as_user(other.email):
            ctx = frappe._dict()
            payment_plan_pay.get_context(ctx)
        self.assertTrue(ctx.get("no_access"))

    def test_page_lists_enabled_online_methods(self):
        from unittest.mock import patch

        from verenigingen.templates.pages import payment_plan_pay

        both = [
            {"id": "mollie", "label": "Online payment"},
            {"id": "ing_ideal", "label": "iDEAL via ING/Pay.nl"},
        ]
        frappe.form_dict = frappe._dict({"plan": self.plan.name})
        with (
            patch.object(payment_plan_pay.PaymentHook, "get_available_methods", return_value=both),
            self.as_user(self.member.email),
        ):
            ctx = frappe._dict()
            payment_plan_pay.get_context(ctx)
        ids = {m["id"] for m in ctx.payment_methods}
        self.assertIn("ing_ideal", ids)
        self.assertIn("mollie", ids)
