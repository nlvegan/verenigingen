#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Coverage Tests for financial_utils.py
=====================================

Real-DB integration tests that exercise the branches not covered by
``test_financial_utils.py``:

- ``get_customer_invoices`` date-range / outstanding-only / limit branches
- ``get_outstanding_invoices`` due_date_filter branches (overdue/today/soon)
- ``get_recent_invoices``
- ``get_invoice_payment_status``
- ``get_customer_payment_summary`` (SQL aggregation + payment_ratio)
- ``get_total_outstanding_amount`` with real invoices
- ``is_customer_overdue`` / ``has_outstanding_invoices`` true paths
- cache helpers ``invalidate_customer_cache`` / ``refresh_financial_cache``

Fixtures are real submitted Sales Invoices created via the enhanced factory;
expected values are derived from the data the test itself creates.
"""

import frappe
from frappe.utils import add_days, add_months, flt, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.financial_utils import (
    get_customer_invoices,
    get_customer_payment_summary,
    get_invoice_payment_status,
    get_outstanding_invoices,
    get_recent_invoices,
    get_total_outstanding_amount,
    has_outstanding_invoices,
    invalidate_customer_cache,
    is_customer_overdue,
    refresh_financial_cache,
)


class TestFinancialUtilsCoverage(EnhancedTestCase):
    """Branch-coverage suite for financial query utilities."""

    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="Coverage",
            last_name="Financial",
            birth_date="1988-03-03",
        )
        self.customer_name = self.member.customer
        self.assertTrue(self.customer_name, "Member must have a linked customer")

    def _make_invoice(
        self,
        grand_total=100.0,
        posting_date=None,
        due_date=None,
        outstanding_amount=None,
        status=None,
    ):
        """Create a real submitted Sales Invoice and adjust ledger-derived
        fields AFTER submit via db_set.

        The factory's pre-submit kwargs for outstanding_amount/status are
        recomputed by ERPNext on submit, and a past due_date trips the
        "Due Date cannot be before Posting Date" guard. We therefore submit
        a clean unpaid invoice (outstanding == grand_total) and then override
        the persisted fields directly to model paid/overdue states, matching
        the read-only DB shape the utils query against.
        """
        inv = self.create_test_sales_invoice(
            self.customer_name,
            grand_total=grand_total,
            posting_date=posting_date or today(),
        )
        updates = {}
        if due_date is not None:
            updates["due_date"] = due_date
        if outstanding_amount is not None:
            updates["outstanding_amount"] = outstanding_amount
        if status is not None:
            updates["status"] = status
        if updates:
            for field, value in updates.items():
                frappe.db.set_value("Sales Invoice", inv.name, field, value, update_modified=False)
            inv.reload()
        return inv

    # ------------------------------------------------------------------
    # get_customer_invoices branches
    # ------------------------------------------------------------------

    def test_get_customer_invoices_returns_submitted_invoice(self):
        """A submitted invoice is returned with the default field set."""
        inv = self._make_invoice(grand_total=120.0)

        invoices = get_customer_invoices(self.customer_name)
        names = {row["name"] for row in invoices}
        self.assertIn(inv.name, names)
        # Pin the default field-set VALUES, not just key presence:
        # a fresh submitted invoice is Unpaid with outstanding == grand_total.
        row = next(r for r in invoices if r["name"] == inv.name)
        self.assertEqual(row["status"], "Unpaid")
        self.assertEqual(flt(row["outstanding_amount"]), 120.0)

    def test_get_customer_invoices_outstanding_only_filters_paid(self):
        """outstanding_only excludes invoices with zero outstanding."""
        unpaid = self._make_invoice(grand_total=200.0)
        paid = self._make_invoice(grand_total=80.0, outstanding_amount=0.0, status="Paid")

        rows = get_customer_invoices(self.customer_name, outstanding_only=True)
        names = {r["name"] for r in rows}
        self.assertIn(unpaid.name, names)
        self.assertNotIn(paid.name, names)

    def test_get_customer_invoices_date_range_between(self):
        """date_from + date_to selects the between-range branch."""
        old_inv = self._make_invoice(grand_total=50.0, posting_date=add_days(today(), -200))
        recent_inv = self._make_invoice(grand_total=60.0, posting_date=add_days(today(), -10))

        rows = get_customer_invoices(
            self.customer_name,
            date_from=add_days(today(), -30),
            date_to=today(),
        )
        names = {r["name"] for r in rows}
        self.assertIn(recent_inv.name, names)
        self.assertNotIn(old_inv.name, names)

    def test_get_customer_invoices_date_from_only(self):
        """date_from alone selects the >= branch."""
        old_inv = self._make_invoice(grand_total=50.0, posting_date=add_days(today(), -200))
        recent_inv = self._make_invoice(grand_total=60.0, posting_date=today())

        rows = get_customer_invoices(self.customer_name, date_from=add_days(today(), -30))
        names = {r["name"] for r in rows}
        self.assertIn(recent_inv.name, names)
        self.assertNotIn(old_inv.name, names)

    def test_get_customer_invoices_date_to_only(self):
        """date_to alone selects the <= branch."""
        old_inv = self._make_invoice(grand_total=50.0, posting_date=add_days(today(), -200))
        recent_inv = self._make_invoice(grand_total=60.0, posting_date=today())

        rows = get_customer_invoices(self.customer_name, date_to=add_days(today(), -100))
        names = {r["name"] for r in rows}
        self.assertIn(old_inv.name, names)
        self.assertNotIn(recent_inv.name, names)

    def test_get_customer_invoices_limit(self):
        """limit caps the number of returned rows to exactly the cap.

        The customer is fresh per-test, so with 3 invoices and limit=2 the
        result must be exactly 2 — assert equality (not <=) so a regression
        that ignored the limit would fail.
        """
        for _ in range(3):
            self._make_invoice(grand_total=10.0)

        rows = get_customer_invoices(self.customer_name, limit=2)
        self.assertEqual(len(rows), 2)

    # ------------------------------------------------------------------
    # get_outstanding_invoices due_date_filter branches
    # ------------------------------------------------------------------

    def test_get_outstanding_invoices_overdue(self):
        """due_date_filter='overdue' returns past-due unpaid invoices."""
        overdue = self._make_invoice(grand_total=100.0, due_date=add_days(today(), -5))
        future = self._make_invoice(grand_total=100.0, due_date=add_days(today(), 30))

        rows = get_outstanding_invoices(self.customer_name, due_date_filter="overdue")
        names = {r["name"] for r in rows}
        self.assertIn(overdue.name, names)
        self.assertNotIn(future.name, names)

    def test_get_outstanding_invoices_due_today(self):
        """due_date_filter='due_today' returns invoices due today."""
        due_now = self._make_invoice(grand_total=100.0, due_date=today())
        later = self._make_invoice(grand_total=100.0, due_date=add_days(today(), 10))

        rows = get_outstanding_invoices(self.customer_name, due_date_filter="due_today")
        names = {r["name"] for r in rows}
        self.assertIn(due_now.name, names)
        self.assertNotIn(later.name, names)

    def test_get_outstanding_invoices_due_soon(self):
        """due_date_filter='due_soon' returns invoices due within a month."""
        soon = self._make_invoice(grand_total=100.0, due_date=add_days(today(), 10))
        far = self._make_invoice(grand_total=100.0, due_date=add_months(today(), 3))

        rows = get_outstanding_invoices(self.customer_name, due_date_filter="due_soon")
        names = {r["name"] for r in rows}
        self.assertIn(soon.name, names)
        self.assertNotIn(far.name, names)

    # ------------------------------------------------------------------
    # get_recent_invoices
    # ------------------------------------------------------------------

    def test_get_recent_invoices_window(self):
        """Only invoices within months_back are returned."""
        recent = self._make_invoice(grand_total=70.0, posting_date=add_days(today(), -20))
        stale = self._make_invoice(grand_total=70.0, posting_date=add_months(today(), -6))

        rows = get_recent_invoices(self.customer_name, months_back=2)
        names = {r["name"] for r in rows}
        self.assertIn(recent.name, names)
        self.assertNotIn(stale.name, names)

    # ------------------------------------------------------------------
    # get_invoice_payment_status
    # ------------------------------------------------------------------

    def test_get_invoice_payment_status_unpaid(self):
        """Unpaid invoice reports is_paid False with matching amounts."""
        inv = self._make_invoice(grand_total=150.0)

        status = get_invoice_payment_status(inv.name)

        self.assertEqual(status["invoice_name"], inv.name)
        self.assertEqual(flt(status["outstanding_amount"]), 150.0)
        self.assertFalse(status["is_paid"])
        self.assertIsInstance(status["payment_entries"], list)

    def test_get_invoice_payment_status_paid(self):
        """Zero-outstanding invoice reports is_paid True."""
        inv = self._make_invoice(grand_total=90.0, outstanding_amount=0.0, status="Paid")

        status = get_invoice_payment_status(inv.name)
        self.assertTrue(status["is_paid"])
        self.assertEqual(flt(status["outstanding_amount"]), 0.0)

    def test_get_invoice_payment_status_empty_and_missing(self):
        """Empty input and non-existent invoice return empty dict."""
        self.assertEqual(get_invoice_payment_status(""), {})
        self.assertEqual(get_invoice_payment_status("NON-EXISTENT-INV"), {})

    # ------------------------------------------------------------------
    # get_customer_payment_summary
    # ------------------------------------------------------------------

    def test_get_customer_payment_summary_aggregates_invoices(self):
        """Summary aggregates invoiced/outstanding/overdue from real invoices."""
        # Two invoices: one overdue+outstanding, one fully paid
        self._make_invoice(grand_total=300.0, due_date=add_days(today(), -10))
        self._make_invoice(grand_total=200.0, outstanding_amount=0.0, status="Paid")

        summary = get_customer_payment_summary(self.customer_name)

        self.assertEqual(summary["customer_name"], self.customer_name)
        self.assertGreaterEqual(summary["total_invoices"], 2)
        self.assertGreaterEqual(flt(summary["total_invoiced"]), 500.0)
        self.assertGreaterEqual(flt(summary["outstanding_balance"]), 300.0)
        self.assertGreaterEqual(flt(summary["overdue_amount"]), 300.0)
        # payment_ratio is defined when total_invoiced > 0
        self.assertIsInstance(summary["payment_ratio"], float)

    def test_get_customer_payment_summary_no_invoices_ratio_zero(self):
        """A customer with no invoices yields zero totals and zero ratio."""
        summary = get_customer_payment_summary(self.customer_name)
        # No invoices created -> total_invoiced 0 -> payment_ratio 0 branch
        self.assertEqual(flt(summary["total_invoiced"]), 0.0)
        self.assertEqual(summary["payment_ratio"], 0)

    def test_get_customer_payment_summary_empty_input(self):
        self.assertEqual(get_customer_payment_summary(""), {})

    # ------------------------------------------------------------------
    # convenience helpers true-paths
    # ------------------------------------------------------------------

    def test_has_outstanding_invoices_true(self):
        self._make_invoice(grand_total=100.0)
        self.assertTrue(has_outstanding_invoices(self.customer_name))

    def test_get_total_outstanding_amount_sums(self):
        self._make_invoice(grand_total=100.0)
        self._make_invoice(grand_total=50.0)
        total = get_total_outstanding_amount(self.customer_name)
        self.assertGreaterEqual(total, 150.0)

    def test_is_customer_overdue_true(self):
        self._make_invoice(grand_total=100.0, due_date=add_days(today(), -3))
        self.assertTrue(is_customer_overdue(self.customer_name))

    def test_is_customer_overdue_false(self):
        # Only a future-due invoice -> not overdue
        self._make_invoice(grand_total=100.0, due_date=add_days(today(), 30))
        self.assertFalse(is_customer_overdue(self.customer_name))

    # ------------------------------------------------------------------
    # cache helpers (must not raise)
    # ------------------------------------------------------------------

    def test_invalidate_customer_cache_deletes_keys(self):
        """invalidate_customer_cache removes the per-customer keys.

        Seed the exact keys the function targets, then assert they are gone
        afterwards. This pins the key-naming contract
        (f"customer_invoices:{customer}", etc.) that a bare no-raise smoke
        test would miss.
        """
        keys = [
            f"customer_invoices:{self.customer_name}",
            f"outstanding_invoices:{self.customer_name}",
            f"payment_summary:{self.customer_name}",
        ]
        for key in keys:
            frappe.cache().set_value(key, "seeded")

        with self.assertNoErrorLog():
            invalidate_customer_cache(self.customer_name)

        for key in keys:
            self.assertIsNone(frappe.cache().get_value(key))

    def test_refresh_financial_cache_clears_pattern_keys(self):
        """refresh_financial_cache deletes keys matching the financial patterns."""
        seeded = f"customer_invoices:{self.customer_name}"
        frappe.cache().set_value(seeded, "seeded")

        with self.assertNoErrorLog():
            refresh_financial_cache()

        self.assertIsNone(frappe.cache().get_value(seeded))


if __name__ == "__main__":
    import unittest

    unittest.main()
