#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Additional Coverage Tests for payment_utils.py
==============================================

Complements ``test_payment_utils.py`` (which exercises the empty/guard paths)
by populating REAL submitted Payment Entries / Sales Invoices / Payment Entry
References so the SQL-aggregation, JOIN, year-filter, allocation, DISTINCT-year
and cache branches are actually executed with non-empty data and asserted with
meaningful values.

Production module under test:
    verenigingen.verenigingen_payments.utils.payment_utils

Fixtures are built with the EnhancedTestCase factory's ``create_test_payment_entry``
helper (which wires valid GL paid_to/paid_from accounts) against a EUR company
from ``get_eur_test_company``. All inserts/submits happen in setUp or in
``_make_*`` factory-prefixed helpers (never in test bodies) per the local
test-quality-enforcer rules. EnhancedTestCase auto-rolls back.
"""

from datetime import datetime

import frappe
from frappe.utils import flt

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.verenigingen_payments.utils.payment_utils import (
    get_customer_payments_summary,
    get_last_payment_date,
    get_payment_allocation_status,
    get_payment_history_for_customer,
    get_payment_references_for_invoice,
    get_payment_years_for_customer,
    get_total_payments_for_year,
    get_unreconciled_payments,
    has_payments,
    invalidate_payment_cache,
    refresh_payment_cache,
)


class TestPaymentUtilsCoverage(EnhancedTestCase):
    """Populated-data coverage for payment_utils query helpers."""

    def setUp(self):
        super().setUp()
        self.company = get_eur_test_company()

        # A member auto-creates and links a Customer (member.customer).
        self.member = self.create_test_member(
            first_name="Cover",
            last_name="Payer",
            email="cover.payer@test.invalid",
            birth_date="1985-05-05",
        )
        self.customer_name = self.member.customer

        # Two submitted Payment Entries for THIS customer:
        #  - PE A: 40.00, posting today, fully unallocated -> drives summary,
        #    history, unreconciled, allocation-status, years.
        #  - PE B: 60.00, posting a prior year, fully unallocated -> drives the
        #    DISTINCT-YEAR and year-filter branches.
        self.current_year = datetime.now().year
        self.prior_year = self.current_year - 1

        self.pe_current = self._make_submitted_payment(
            amount=40.0,
            posting_date=f"{self.current_year}-06-15",
            reference_no="COVER-PE-CUR",
        )
        self.pe_prior = self._make_submitted_payment(
            amount=60.0,
            posting_date=f"{self.prior_year}-03-10",
            reference_no="COVER-PE-PRIOR",
        )

    # ------------------------------------------------------------------ #
    # factory-prefixed helpers (insert/submit allowed here, not in tests) #
    # ------------------------------------------------------------------ #
    def _make_submitted_payment(self, amount, posting_date, reference_no, party=None):
        """Create + submit a Receive Payment Entry for the test customer."""
        return self.create_test_payment_entry(
            company=self.company,
            party_type="Customer",
            party=party or self.customer_name,
            paid_amount=amount,
            received_amount=amount,
            posting_date=posting_date,
            reference_no=reference_no,
            mode_of_payment="Bank Transfer",
            submit=True,
        )

    def _make_submitted_invoice(self, amount):
        """Create + submit a Sales Invoice for the test customer (EUR company)."""
        item_code = "Cover Payment Coverage Item"
        if not frappe.db.exists("Item", item_code):
            item = frappe.get_doc(
                {
                    "doctype": "Item",
                    "item_code": item_code,
                    "item_name": item_code,
                    "item_group": "Services",
                    "stock_uom": "Nos",
                    "is_stock_item": 0,
                    "is_sales_item": 1,
                }
            )
            item.insert(ignore_permissions=True)
            self._track_test_document("Item", item.name, priority=2)

        invoice = self.create_test_sales_invoice(
            customer=self.customer_name,
            company=self.company,
            items=[{"item_code": item_code, "qty": 1, "rate": float(amount)}],
        )
        invoice.submit()
        return invoice

    def _make_payment_against_invoice(self, invoice, allocated):
        """Submit a Receive PE that allocates ``allocated`` to ``invoice``."""
        return self.create_test_payment_entry(
            company=self.company,
            party_type="Customer",
            party=self.customer_name,
            paid_amount=allocated,
            received_amount=allocated,
            posting_date=invoice.posting_date,
            reference_no="COVER-PE-ALLOC",
            mode_of_payment="Bank Transfer",
            references=[
                {
                    "reference_doctype": "Sales Invoice",
                    "reference_name": invoice.name,
                    "allocated_amount": allocated,
                }
            ],
            submit=True,
        )

    # ------------------------------------------------------------------ #
    # get_customer_payments_summary — SQL aggregation                     #
    # ------------------------------------------------------------------ #
    def test_summary_aggregates_real_payments(self):
        """SUM/COUNT/AVG/MAX/MIN over the two submitted payments."""
        summary = get_customer_payments_summary(self.customer_name)

        self.assertEqual(summary["payment_count"], 2)
        self.assertAlmostEqual(summary["total_amount"], 100.0, places=2)
        self.assertAlmostEqual(summary["average_payment"], 50.0, places=2)
        # MAX posting date is in the current year, MIN in the prior year.
        self.assertEqual(str(summary["last_payment_date"]), f"{self.current_year}-06-15")
        self.assertEqual(str(summary["first_payment_date"]), f"{self.prior_year}-03-10")

    def test_summary_year_filter_restricts_to_that_year(self):
        """year= path: only the current-year 40.00 payment is aggregated."""
        summary = get_customer_payments_summary(self.customer_name, year=self.current_year)

        self.assertEqual(summary["payment_count"], 1)
        self.assertAlmostEqual(summary["total_amount"], 40.0, places=2)
        self.assertEqual(summary["period_filter"]["year"], self.current_year)
        # MIN == MAX since only one payment falls in-year.
        self.assertEqual(str(summary["last_payment_date"]), f"{self.current_year}-06-15")

    def test_summary_year_out_of_range_returns_empty(self):
        """Year < 1900 hits the range-guard early return ({})."""
        self.assertEqual(get_customer_payments_summary(self.customer_name, year=1850), {})
        self.assertEqual(get_customer_payments_summary(self.customer_name, year=2200), {})

    def test_summary_year_non_numeric_returns_empty(self):
        """Non-int year hits the ValueError/TypeError except branch ({})."""
        self.assertEqual(get_customer_payments_summary(self.customer_name, year="abc"), {})

    def test_summary_year_as_numeric_string_is_parsed(self):
        """int(year) parses a numeric string; current-year filter still works."""
        summary = get_customer_payments_summary(self.customer_name, year=str(self.current_year))
        self.assertEqual(summary["payment_count"], 1)
        self.assertAlmostEqual(summary["total_amount"], 40.0, places=2)

    def test_summary_date_from_to_range(self):
        """date_from+date_to BETWEEN branch picks only the current-year payment."""
        summary = get_customer_payments_summary(
            self.customer_name,
            date_from=f"{self.current_year}-01-01",
            date_to=f"{self.current_year}-12-31",
        )
        self.assertEqual(summary["payment_count"], 1)
        self.assertAlmostEqual(summary["total_amount"], 40.0, places=2)

    # ------------------------------------------------------------------ #
    # get_payment_history_for_customer — year-filter branch               #
    # ------------------------------------------------------------------ #
    def test_history_returns_both_payments_ordered_desc(self):
        history = get_payment_history_for_customer(self.customer_name)
        names = [row["name"] for row in history]
        self.assertIn(self.pe_current.name, names)
        self.assertIn(self.pe_prior.name, names)
        # Ordered posting_date desc => current-year payment first.
        self.assertEqual(history[0]["name"], self.pe_current.name)

    def test_history_year_filter_returns_only_in_year(self):
        history = get_payment_history_for_customer(self.customer_name, year=self.prior_year)
        names = [row["name"] for row in history]
        self.assertIn(self.pe_prior.name, names)
        self.assertNotIn(self.pe_current.name, names)

    # ------------------------------------------------------------------ #
    # get_payment_references_for_invoice — JOIN vs simple branch          #
    # ------------------------------------------------------------------ #
    def test_references_with_payment_details_join(self):
        """include_payment_details=True exercises the LEFT JOIN + pe.* fields."""
        invoice = self._make_submitted_invoice(amount=30.0)
        pe = self._make_payment_against_invoice(invoice, allocated=30.0)

        refs = get_payment_references_for_invoice("Sales Invoice", invoice.name)
        self.assertEqual(len(refs), 1)
        ref = refs[0]
        self.assertEqual(ref["payment_entry"], pe.name)
        self.assertAlmostEqual(flt(ref["allocated_amount"]), 30.0, places=2)
        # Joined Payment Entry columns must be populated.
        self.assertEqual(ref["party"], self.customer_name)
        self.assertEqual(str(ref["mode_of_payment"]), "Bank Transfer")
        self.assertIsNotNone(ref["posting_date"])

    def test_references_without_payment_details_simple(self):
        """include_payment_details=False uses get_all without the joined PE cols."""
        invoice = self._make_submitted_invoice(amount=20.0)
        self._make_payment_against_invoice(invoice, allocated=20.0)

        refs = get_payment_references_for_invoice(
            "Sales Invoice", invoice.name, include_payment_details=False
        )
        self.assertEqual(len(refs), 1)
        ref = refs[0]
        self.assertAlmostEqual(flt(ref["allocated_amount"]), 20.0, places=2)
        # The simple branch returns only the reference fields, not pe.party.
        self.assertNotIn("party", ref)
        self.assertEqual(ref["reference_name"], invoice.name)

    # ------------------------------------------------------------------ #
    # get_unreconciled_payments — filters                                 #
    # ------------------------------------------------------------------ #
    def test_unreconciled_lists_unallocated_payment(self):
        """The fully-unallocated 40.00 PE shows up for its customer."""
        rows = get_unreconciled_payments(customer=self.customer_name)
        names = [r["name"] for r in rows]
        self.assertIn(self.pe_current.name, names)
        match = next(r for r in rows if r["name"] == self.pe_current.name)
        self.assertGreater(flt(match["unallocated_amount"]), 0)

    def test_unreconciled_party_type_filter(self):
        rows = get_unreconciled_payments(party_type="Customer", customer=self.customer_name)
        self.assertTrue(all(r["party_type"] == "Customer" for r in rows))
        self.assertIn(self.pe_current.name, [r["name"] for r in rows])

    def test_unreconciled_minimum_amount_filter_excludes(self):
        """minimum_amount above the unallocated value excludes the payment."""
        rows = get_unreconciled_payments(customer=self.customer_name, minimum_amount=1000.0)
        self.assertNotIn(self.pe_current.name, [r["name"] for r in rows])

    def test_unreconciled_date_from_filter(self):
        """date_from in the future excludes the (past-dated) payments."""
        rows = get_unreconciled_payments(
            customer=self.customer_name, date_from=f"{self.current_year + 5}-01-01"
        )
        self.assertEqual(rows, [])

    # ------------------------------------------------------------------ #
    # get_payment_allocation_status — reference aggregation / threshold   #
    # ------------------------------------------------------------------ #
    def test_allocation_status_fully_allocated(self):
        """A PE whose allocation consumes the full amount is fully_allocated."""
        invoice = self._make_submitted_invoice(amount=25.0)
        pe = self._make_payment_against_invoice(invoice, allocated=25.0)

        status = get_payment_allocation_status(pe.name)
        self.assertEqual(status["payment_entry"], pe.name)
        self.assertEqual(status["allocation_count"], 1)
        self.assertAlmostEqual(status["allocated_amount"], 25.0, places=2)
        self.assertAlmostEqual(status["unallocated_amount"], 0.0, places=2)
        self.assertTrue(status["fully_allocated"])
        self.assertEqual(status["party"], self.customer_name)

    def test_allocation_status_unallocated(self):
        """A reference-less PE has zero allocations and is NOT fully_allocated."""
        status = get_payment_allocation_status(self.pe_current.name)
        self.assertEqual(status["allocation_count"], 0)
        self.assertEqual(status["allocations"], [])
        self.assertAlmostEqual(status["allocated_amount"], 0.0, places=2)
        self.assertGreater(status["unallocated_amount"], 0)
        self.assertFalse(status["fully_allocated"])

    # ------------------------------------------------------------------ #
    # get_payment_years_for_customer — DISTINCT YEAR ordering + int cast  #
    # ------------------------------------------------------------------ #
    def test_payment_years_distinct_desc(self):
        years = get_payment_years_for_customer(self.customer_name)
        self.assertEqual(years, [self.current_year, self.prior_year])
        self.assertTrue(all(isinstance(y, int) for y in years))

    # ------------------------------------------------------------------ #
    # convenience wrappers (populated)                                    #
    # ------------------------------------------------------------------ #
    def test_has_payments_true_when_populated(self):
        self.assertTrue(has_payments(self.customer_name))

    def test_last_payment_date_returns_latest(self):
        last = get_last_payment_date(self.customer_name)
        self.assertEqual(str(last), f"{self.current_year}-06-15")

    def test_total_payments_for_year(self):
        total = get_total_payments_for_year(self.customer_name, self.current_year)
        self.assertAlmostEqual(total, 40.0, places=2)
        prior_total = get_total_payments_for_year(self.customer_name, self.prior_year)
        self.assertAlmostEqual(prior_total, 60.0, places=2)

    # ------------------------------------------------------------------ #
    # cache helpers — happy path must not raise; errors swallowed         #
    # ------------------------------------------------------------------ #
    def test_invalidate_payment_cache_deletes_keys(self):
        """Pre-seed the three cache keys, then assert invalidate clears them."""
        cache = frappe.cache()
        keys = [
            f"payment_summary:{self.customer_name}",
            f"payment_history:{self.customer_name}",
            f"payment_years:{self.customer_name}",
        ]
        for key in keys:
            cache.set_value(key, "sentinel")
            self.assertEqual(cache.get_value(key), "sentinel")

        # Should not raise.
        invalidate_payment_cache(self.customer_name)

        for key in keys:
            self.assertIsNone(cache.get_value(key))

    def test_refresh_payment_cache_clears_matching_keys(self):
        """refresh_payment_cache walks the payment_* patterns and deletes matches."""
        cache = frappe.cache()
        summary_key = f"payment_summary:{self.customer_name}"
        history_key = f"payment_history:{self.customer_name}"
        unrelated_key = f"some_other_cache:{self.customer_name}"
        cache.set_value(summary_key, "x")
        cache.set_value(history_key, "y")
        cache.set_value(unrelated_key, "z")

        refresh_payment_cache()

        # Payment-pattern keys are cleared; an unrelated key is left untouched.
        self.assertIsNone(cache.get_value(summary_key))
        self.assertIsNone(cache.get_value(history_key))
        self.assertEqual(cache.get_value(unrelated_key), "z")


if __name__ == "__main__":
    import unittest

    unittest.main()
