#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for Task 9: reconcile the payment-history catch-all against
source-of-truth Sales Invoices instead of blindly re-enqueuing through the
circular `member_doc.add_invoice_to_payment_history(...)` path (which just
re-enqueues through the batch processor and always returns True, so the old
validator counted "repaired" without ever verifying a row actually landed).

The fixed `validate_and_repair_payment_history` must instead:
- find in-window submitted Sales Invoices missing from the member's
  `payment_history` child table with a single batched query (no per-invoice
  get_doc), and
- drive the real drain job (`background_jobs.drain_member_payment_history`)
  once per member (deduplicated by job_id), never call
  `add_invoice_to_payment_history` directly.
"""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPaymentHistoryReconciliation(EnhancedTestCase):
    """TDD coverage for the source-of-truth reconciliation rewrite."""

    def setUp(self):
        super().setUp()

        from verenigingen.tests.support.sepa_test_company import get_eur_test_company

        # Company whose receivable currency matches the EUR invoices these tests
        # build. Ensure the shared test item exists up front (as Administrator);
        # creating it later inside a restricted context could hit permission limits.
        self.test_company = get_eur_test_company()
        self._ensure_test_item("TEST-MEMBERSHIP")

    def _make_member_with_customer(self, suffix):
        member = self.create_test_member(
            first_name=f"Reconcile{suffix}",
            last_name="TestMember",
            email=f"reconcile.test.{suffix}@example.com",
        )
        if not member.customer:
            customer = frappe.new_doc("Customer")
            customer.customer_name = f"{member.first_name} {member.last_name}"
            customer.customer_type = "Individual"
            customer.member = member.name
            customer.save()
            member.customer = customer.name
            member.save()
            self.track_doc("Customer", customer.name)
        return member

    def _build_secured_invoice(self, customer, rate, posting_date=None):
        """Build + save a complete (v16-valid) EUR Sales Invoice for `customer`.

        Mirrors verenigingen/tests/security/test_integrated_security_payment_system.py
        ::_build_secured_invoice so this suite exercises the same field set as the
        established secured-invoice tests (company / debit_to / income account /
        cost_center / selling price list are all mandatory on a v16 Sales Invoice).
        """
        company = self.test_company
        debit_to = frappe.db.get_value(
            "Company", company, "default_receivable_account"
        ) or frappe.db.get_value(
            "Account", {"account_type": "Receivable", "company": company, "is_group": 0}, "name"
        )
        income_account = frappe.db.get_value(
            "Account", {"account_type": "Income Account", "company": company, "is_group": 0}, "name"
        )
        cost_center = frappe.db.get_value("Company", company, "cost_center") or frappe.db.get_value(
            "Cost Center", {"company": company, "is_group": 0}, "name"
        )
        price_list = frappe.db.get_value("Price List", {"selling": 1}, "name") or "Standard Selling"

        invoice = frappe.new_doc("Sales Invoice")
        invoice.customer = customer
        invoice.company = company
        invoice.currency = "EUR"
        invoice.conversion_rate = 1.0
        invoice.debit_to = debit_to
        invoice.selling_price_list = price_list
        invoice.price_list_currency = "EUR"
        invoice.plc_conversion_rate = 1.0
        invoice.ignore_pricing_rule = 1
        invoice.posting_date = posting_date or today()
        invoice.set_posting_time = 1
        invoice.due_date = add_days(invoice.posting_date, 30)
        invoice.is_membership_invoice = 1
        invoice.append(
            "items",
            {
                "item_code": "TEST-MEMBERSHIP",
                "qty": 1,
                "rate": rate,
                "income_account": income_account,
                "cost_center": cost_center,
            },
        )
        invoice.save()
        invoice.submit()
        return invoice

    def test_missing_invoice_is_detected_and_enqueued_once(self):
        """An in-window submitted invoice with no payment_history row must
        trigger exactly one deduplicated drain-job enqueue for its member."""
        member = self._make_member_with_customer("missing")
        invoice = self._build_secured_invoice(member.customer, 42.0)

        # Submitting a membership Sales Invoice auto-syncs the member's payment
        # history synchronously via the on_submit performance handler
        # (performance_event_handlers.on_member_payment_update ->
        # OptimizedMemberQueries.bulk_update_payment_history). Clear that row so
        # this invoice is a genuine gap for the reconciliation to find (mirrors
        # test_payment_history_validator.py's established _clear_history_rows
        # pattern).
        frappe.db.delete("Member Payment History", {"invoice": invoice.name})

        from verenigingen.utils import payment_history_validator

        calls = []
        with patch(
            "verenigingen.utils.payment_history_validator.frappe.enqueue",
            side_effect=lambda *a, **k: calls.append(k),
        ):
            result = payment_history_validator.validate_and_repair_payment_history()

        self.assertTrue(result["success"])

        job_ids = [k.get("job_id") for k in calls]
        expected_job_id = f"fin_history_payment_{member.name}"
        self.assertIn(expected_job_id, job_ids)
        # Enqueued exactly once for this member -- dedup by member, not per invoice.
        self.assertEqual(job_ids.count(expected_job_id), 1)

        # The call must target the real drain job, not the circular
        # add_invoice_to_payment_history re-enqueue path.
        enqueued_call = calls[job_ids.index(expected_job_id)]
        self.assertEqual(enqueued_call.get("member"), member.name)
        self.assertEqual(enqueued_call.get("customer"), member.customer)

    def test_already_reflected_invoice_is_not_reprocessed(self):
        """An invoice already reflected in payment_history must not be re-enqueued."""
        member = self._make_member_with_customer("reflected")
        invoice = self._build_secured_invoice(member.customer, 42.0)

        from verenigingen.utils.background_jobs import drain_member_payment_history

        # Drive the real drain job synchronously so payment_history genuinely
        # reflects this invoice (independent of whatever the on_submit sync
        # handler already did).
        drain_member_payment_history(member.name, member.customer)

        self.assertTrue(
            frappe.db.exists("Member Payment History", {"parent": member.name, "invoice": invoice.name}),
            "Precondition failed: invoice should be reflected in payment_history before reconciling",
        )

        from verenigingen.utils import payment_history_validator

        calls = []
        with patch(
            "verenigingen.utils.payment_history_validator.frappe.enqueue",
            side_effect=lambda *a, **k: calls.append(k),
        ):
            result = payment_history_validator.validate_and_repair_payment_history()

        self.assertTrue(result["success"])

        job_ids = [k.get("job_id") for k in calls]
        self.assertNotIn(f"fin_history_payment_{member.name}", job_ids)
