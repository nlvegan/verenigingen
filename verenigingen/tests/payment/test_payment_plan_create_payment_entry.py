# Copyright (c) 2026, Verenigingen
"""PaymentPlan.create_payment_entry() - #1200.

Before the fix this method never set `company` (insert() failed the same #906
way: "Source Exchange Rate is mandatory") AND its `paid_to`/`paid_from` were
resolved from fields that do not exist on "Verenigingen Settings" (they always
returned None) and, independently, were swapped relative to ERPNext's own
"Receive" convention. This file exercises the real, unmocked method against a
real EUR company fixture and asserts a submitted, correctly-accounted, balanced
Payment Entry -- not just that fields were set on an in-memory doc.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.singleton_backup import singleton_backup
from verenigingen.tests.support.invoice_payments import member_with_customer
from verenigingen.tests.support.sepa_test_company import get_eur_test_company


class TestPaymentPlanCreatePaymentEntry(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self.company = get_eur_test_company()

    def _plan(self, member_name):
        plan = frappe.new_doc("Payment Plan")
        plan.member = member_name
        plan.plan_type = "Equal Installments"
        plan.total_amount = 90.0
        plan.number_of_installments = 3
        plan.frequency = "Monthly"
        plan.start_date = today()
        plan.status = "Active"
        plan.reason = "test"
        plan.payment_method = "Bank Transfer"
        plan.save()
        self.track_doc("Payment Plan", plan.name)
        return plan

    def test_create_payment_entry_posts_balanced_receive(self):
        """create_payment_entry() creates a submitted, correctly-accounted
        "Receive" Payment Entry against the member's customer.

        paid_from must be the customer's receivable account (ERPNext's own
        convention for a Receive entry: setup_party_account_field sets
        party_account = paid_from), and paid_to the company's cash/bank
        account -- the two were swapped in the pre-fix code in addition to
        `company` never being set at all.
        """
        member = member_with_customer(self, "PlanPE")
        plan = self._plan(member.name)

        with singleton_backup("Verenigingen Settings"):
            settings = frappe.get_single("Verenigingen Settings")
            settings.company = self.company
            settings.save()

            with self.assertNoErrorLog():
                plan.create_payment_entry(30.0, "PLANPE-REF-1", today())

        payment_entries = frappe.get_all(
            "Payment Entry",
            filters={"party": member.customer, "reference_no": "PLANPE-REF-1"},
            fields=["name"],
        )
        self.assertEqual(len(payment_entries), 1, "create_payment_entry should create exactly one PE")
        pe = frappe.get_doc("Payment Entry", payment_entries[0].name)
        # Priority 6, matching DRAIN_PRIORITY_BY_DOCTYPE's "Payment Entry" tier:
        # this PE references the member's Customer as party, so it must drain
        # before the Customer/Member (tracked at their default priority) or
        # cleanup hits "Could not find Party" the same way #1200's Ponto test did.
        self.factory.track_document("Payment Entry", pe.name, priority=6)

        self.assertEqual(pe.docstatus, 1)
        self.assertEqual(pe.payment_type, "Receive")
        self.assertEqual(pe.company, self.company)
        expected_receivable = frappe.get_cached_value("Company", self.company, "default_receivable_account")
        expected_cash = frappe.get_cached_value("Company", self.company, "default_cash_account")
        self.assertEqual(pe.paid_from, expected_receivable)
        self.assertEqual(pe.paid_to, expected_cash)

        gl_rows = frappe.get_all(
            "GL Entry",
            filters={"voucher_type": "Payment Entry", "voucher_no": pe.name},
            fields=["account", "debit", "credit"],
        )
        self.assertEqual(len(gl_rows), 2, "an unallocated Receive entry posts exactly two GL rows")
        total_debit = sum(r.debit for r in gl_rows)
        total_credit = sum(r.credit for r in gl_rows)
        self.assertEqual(total_debit, total_credit, "GL rows must balance")
        self.assertEqual(total_debit, 30.0)
