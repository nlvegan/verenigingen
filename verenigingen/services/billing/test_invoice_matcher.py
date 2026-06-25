# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Integration tests for verenigingen/services/billing/invoice_matcher.py

Covers find_matching_invoice (and the SDK-payment wrapper) against REAL
membership Sales Invoices created via the test factory:

    - payment_date type coercion (datetime -> date, raw date, invalid type ValueError)
    - member-without-customer early return
    - SQL coverage matching: exact_coverage (payment within coverage period) vs
      within_buffer (payment in the 3-month buffer outside coverage)
    - amount tolerance: a payment more than 1 cent off does NOT match the SQL path
    - no-match path (no eligible invoice)
    - find_matching_invoice_for_payment SDK wrapper: dict payment, missing amount,
      missing date, and InvoiceMatchResult.to_dict / .found semantics

These exercise money-path correctness: WHICH invoice a payment is reconciled
against, and the match_type classification that downstream reconciliation relies on.
"""

from datetime import date, datetime

import frappe

from verenigingen.services.billing.invoice_matcher import (
    InvoiceMatchResult,
    find_matching_invoice,
    find_matching_invoice_for_payment,
    get_invoice_matcher,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestInvoiceMatcher(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="Matcher", last_name="Test", birth_date="1980-03-03")
        self.customer_doc = self.link_member_to_customer(self.member)
        self.member.reload()

    # ------------------------------------------------------------------
    # Helper: create a submitted membership Sales Invoice with coverage dates
    # ------------------------------------------------------------------
    def _make_membership_invoice(self, amount, coverage_start, coverage_end, outstanding=None):
        invoice = self.create_test_sales_invoice(
            customer=self.member.customer,
            grand_total=amount,
            is_membership_invoice=1,
        )
        # The matcher reads coverage dates + outstanding directly from the DB via SQL,
        # so set them with db_set (invoice is already submitted by the factory).
        frappe.db.set_value(
            "Sales Invoice",
            invoice.name,
            {
                "custom_coverage_start_date": coverage_start,
                "custom_coverage_end_date": coverage_end,
                "grand_total": amount,
                "outstanding_amount": outstanding if outstanding is not None else amount,
            },
            update_modified=False,
        )
        frappe.db.commit()
        return invoice.name

    # ------------------------------------------------------------------
    # payment_date type coercion
    # ------------------------------------------------------------------
    def test_invalid_payment_date_type_raises_valueerror(self):
        with self.assertRaises(ValueError) as ctx:
            find_matching_invoice(self.member.name, "2025-01-01", 25.0)
        self.assertIn("payment_date must be date or datetime", str(ctx.exception))

    def test_datetime_payment_date_is_accepted(self):
        """A datetime payment_date is coerced to its .date() and matches a covering invoice."""
        inv = self._make_membership_invoice(25.0, date(2025, 1, 1), date(2025, 1, 31))
        result = find_matching_invoice(
            self.member.name, datetime(2025, 1, 15, 14, 30), 25.0, check_overlap=False
        )
        self.assertEqual(result.invoice_name, inv)
        self.assertEqual(result.match_type, "exact_coverage")

    # ------------------------------------------------------------------
    # member without customer
    # ------------------------------------------------------------------
    def test_member_without_customer_returns_warning(self):
        bare_member = self.create_test_member(
            first_name="NoCust", last_name="Matcher", birth_date="1990-01-01"
        )
        # Ensure no customer link (created members may auto-link); clear it.
        frappe.db.set_value("Member", bare_member.name, "customer", None, update_modified=False)
        frappe.db.commit()
        result = find_matching_invoice(bare_member.name, date(2025, 1, 1), 10.0)
        self.assertFalse(result.found)
        self.assertIsNone(result.invoice_name)
        self.assertEqual(result.overlap_warning, "Member has no linked customer")

    # ------------------------------------------------------------------
    # SQL coverage matching: exact vs buffer
    # ------------------------------------------------------------------
    def test_exact_coverage_match(self):
        """Payment date INSIDE the coverage period -> match_type exact_coverage."""
        inv = self._make_membership_invoice(33.33, date(2025, 6, 1), date(2025, 6, 30))
        result = find_matching_invoice(self.member.name, date(2025, 6, 10), 33.33, check_overlap=False)
        self.assertEqual(result.invoice_name, inv)
        self.assertEqual(result.match_type, "exact_coverage")
        self.assertAlmostEqual(result.invoice_amount, 33.33, places=2)
        self.assertAlmostEqual(result.outstanding_amount, 33.33, places=2)
        self.assertEqual(result.coverage_start, date(2025, 6, 1))
        self.assertEqual(result.coverage_end, date(2025, 6, 30))

    def test_within_buffer_match(self):
        """Payment date OUTSIDE coverage but within the 3-month buffer -> within_buffer."""
        inv = self._make_membership_invoice(15.0, date(2025, 6, 1), date(2025, 6, 30))
        # Payment 2 months AFTER coverage end -> outside coverage, inside +3mo buffer.
        result = find_matching_invoice(self.member.name, date(2025, 8, 15), 15.0, check_overlap=False)
        self.assertEqual(result.invoice_name, inv)
        self.assertEqual(result.match_type, "within_buffer")

    def test_payment_outside_buffer_no_sql_match(self):
        """A payment more than 3 months outside the coverage period does not SQL-match.

        (calculated-coverage strategy 2 may still run; assert the SQL strategy did
        not produce an exact/buffer match for this far-out payment by checking that
        if any match comes back it is the calculated type, not exact/within_buffer.)"""
        self._make_membership_invoice(40.0, date(2025, 6, 1), date(2025, 6, 30))
        result = find_matching_invoice(self.member.name, date(2026, 6, 1), 40.0, check_overlap=False)
        self.assertNotIn(result.match_type, ("exact_coverage", "within_buffer"))

    def test_amount_mismatch_beyond_tolerance_no_sql_match(self):
        """A grand_total off by more than the 1-cent tolerance fails the SQL amount filter."""
        self._make_membership_invoice(20.00, date(2025, 6, 1), date(2025, 6, 30))
        result = find_matching_invoice(self.member.name, date(2025, 6, 10), 20.50, check_overlap=False)
        # 50 cents off -> the exact/buffer SQL strategy must not match.
        self.assertNotIn(result.match_type, ("exact_coverage", "within_buffer"))

    def test_no_invoice_returns_empty_result(self):
        """A member with a customer but no matching invoice -> empty result."""
        result = find_matching_invoice(self.member.name, date(2024, 1, 1), 99.99, check_overlap=False)
        self.assertFalse(result.found)
        self.assertIsNone(result.invoice_name)
        self.assertIsNone(result.match_type)

    # ------------------------------------------------------------------
    # find_matching_invoice_for_payment (SDK wrapper)
    # ------------------------------------------------------------------
    def test_sdk_payment_dict_matches(self):
        inv = self._make_membership_invoice(12.5, date(2025, 3, 1), date(2025, 3, 31))
        sdk_payment = {
            "amount": {"value": "12.50", "currency": "EUR"},
            "paidAt": "2025-03-15T10:00:00Z",
        }
        result = find_matching_invoice_for_payment(sdk_payment, self.member.name, check_overlap=False)
        self.assertEqual(result.invoice_name, inv)
        self.assertEqual(result.match_type, "exact_coverage")

    def test_sdk_payment_missing_amount(self):
        result = find_matching_invoice_for_payment({"paidAt": "2025-03-15T10:00:00Z"}, self.member.name)
        self.assertFalse(result.found)
        self.assertEqual(result.overlap_warning, "Payment has no amount")

    def test_sdk_payment_missing_date(self):
        result = find_matching_invoice_for_payment(
            {"amount": {"value": "12.50", "currency": "EUR"}}, self.member.name
        )
        self.assertFalse(result.found)
        self.assertEqual(result.overlap_warning, "Payment has no date")

    def test_sdk_payment_falls_back_to_created_at(self):
        """When paidAt is absent, createdAt is used for the payment date."""
        inv = self._make_membership_invoice(8.0, date(2025, 4, 1), date(2025, 4, 30))
        sdk_payment = {
            "amount": {"value": "8.00", "currency": "EUR"},
            "createdAt": "2025-04-10T08:00:00Z",
        }
        result = find_matching_invoice_for_payment(sdk_payment, self.member.name, check_overlap=False)
        self.assertEqual(result.invoice_name, inv)

    # ------------------------------------------------------------------
    # InvoiceMatchResult dataclass behavior
    # ------------------------------------------------------------------
    def test_match_result_to_dict_and_found(self):
        result = InvoiceMatchResult(
            invoice_name="SINV-X",
            match_type="exact_coverage",
            invoice_amount=10.0,
            outstanding_amount=10.0,
            coverage_start=date(2025, 1, 1),
            coverage_end=date(2025, 1, 31),
        )
        self.assertTrue(result.found)
        d = result.to_dict()
        self.assertEqual(d["invoice_name"], "SINV-X")
        self.assertEqual(d["coverage_start"], "2025-01-01")
        self.assertEqual(d["coverage_end"], "2025-01-31")
        self.assertTrue(d["found"])

    def test_empty_match_result_not_found(self):
        result = InvoiceMatchResult(invoice_name=None, match_type=None)
        self.assertFalse(result.found)
        self.assertFalse(result.to_dict()["found"])

    def test_service_wrapper_delegates(self):
        """get_invoice_matcher() returns a service whose find_matching_invoice delegates
        to the module function and yields the same match."""
        inv = self._make_membership_invoice(5.0, date(2025, 7, 1), date(2025, 7, 31))
        service = get_invoice_matcher()
        result = service.find_matching_invoice(self.member.name, date(2025, 7, 10), 5.0, check_overlap=False)
        self.assertEqual(result.invoice_name, inv)
