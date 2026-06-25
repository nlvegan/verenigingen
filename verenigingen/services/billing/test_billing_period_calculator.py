# -*- coding: utf-8 -*-
"""
Unit tests for verenigingen/services/billing/billing_period_calculator.py

These are PURE functions (no DB writes) so they assert EXACT dates and exercise
boundary conditions (month-end, leap years, year rollover, custom frequencies,
gap-reset logic in derive_coverage_from_invoice_data).
"""

from frappe.utils import add_days, getdate, today

from verenigingen.services.billing.billing_period_calculator import (
    calculate_billing_period,
    calculate_next_invoice_date,
    derive_coverage_from_invoice_data,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestCalculateNextInvoiceDate(EnhancedTestCase):
    REF = "2025-01-15"  # fixed reference date for determinism

    def test_daily(self):
        self.assertEqual(calculate_next_invoice_date("Daily", self.REF), getdate("2025-01-16"))

    def test_weekly(self):
        self.assertEqual(calculate_next_invoice_date("Weekly", self.REF), getdate("2025-01-22"))

    def test_monthly(self):
        self.assertEqual(calculate_next_invoice_date("Monthly", self.REF), getdate("2025-02-15"))

    def test_quarterly(self):
        self.assertEqual(calculate_next_invoice_date("Quarterly", self.REF), getdate("2025-04-15"))

    def test_semi_annual(self):
        self.assertEqual(calculate_next_invoice_date("Semi-Annual", self.REF), getdate("2025-07-15"))

    def test_annual(self):
        self.assertEqual(calculate_next_invoice_date("Annual", self.REF), getdate("2026-01-15"))

    def test_unknown_defaults_monthly(self):
        self.assertEqual(calculate_next_invoice_date("Bogus", self.REF), getdate("2025-02-15"))

    def test_default_from_date_is_today(self):
        self.assertEqual(calculate_next_invoice_date("Daily"), add_days(getdate(today()), 1))

    # ----- Custom frequency branches -----
    def test_custom_days(self):
        self.assertEqual(calculate_next_invoice_date("Custom", self.REF, 10, "Days"), getdate("2025-01-25"))

    def test_custom_weeks(self):
        self.assertEqual(calculate_next_invoice_date("Custom", self.REF, 2, "Weeks"), getdate("2025-01-29"))

    def test_custom_months(self):
        self.assertEqual(calculate_next_invoice_date("Custom", self.REF, 2, "Months"), getdate("2025-03-15"))

    def test_custom_years(self):
        self.assertEqual(calculate_next_invoice_date("Custom", self.REF, 3, "Years"), getdate("2028-01-15"))

    def test_custom_invalid_number_defaults_to_one_month(self):
        # number < 1 -> safe default 1; unit None -> Months
        self.assertEqual(calculate_next_invoice_date("Custom", self.REF, 0, None), getdate("2025-02-15"))

    def test_custom_invalid_unit_falls_back_monthly(self):
        self.assertEqual(calculate_next_invoice_date("Custom", self.REF, 5, "Decades"), getdate("2025-02-15"))


class TestCalculateBillingPeriod(EnhancedTestCase):
    def test_daily_single_day(self):
        d = getdate("2025-03-10")
        self.assertEqual(calculate_billing_period("Daily", d), (d, d))

    def test_weekly_monday_to_sunday(self):
        # 2025-03-12 is a Wednesday; week is Mon 2025-03-10 .. Sun 2025-03-16
        start, end = calculate_billing_period("Weekly", "2025-03-12")
        self.assertEqual(start, getdate("2025-03-10"))
        self.assertEqual(end, getdate("2025-03-16"))

    def test_monthly_full_month(self):
        start, end = calculate_billing_period("Monthly", "2025-03-15")
        self.assertEqual(start, getdate("2025-03-01"))
        self.assertEqual(end, getdate("2025-03-31"))

    def test_monthly_december_year_rollover(self):
        start, end = calculate_billing_period("Monthly", "2025-12-10")
        self.assertEqual(start, getdate("2025-12-01"))
        self.assertEqual(end, getdate("2025-12-31"))

    def test_monthly_february_leap_year(self):
        start, end = calculate_billing_period("Monthly", "2024-02-15")
        self.assertEqual(start, getdate("2024-02-01"))
        self.assertEqual(end, getdate("2024-02-29"))

    def test_monthly_february_non_leap_year(self):
        start, end = calculate_billing_period("Monthly", "2025-02-15")
        self.assertEqual(start, getdate("2025-02-01"))
        self.assertEqual(end, getdate("2025-02-28"))

    def test_quarterly_q1(self):
        start, end = calculate_billing_period("Quarterly", "2025-02-15")
        self.assertEqual(start, getdate("2025-01-01"))
        self.assertEqual(end, getdate("2025-03-31"))

    def test_quarterly_q2(self):
        start, end = calculate_billing_period("Quarterly", "2025-05-15")
        self.assertEqual(start, getdate("2025-04-01"))
        self.assertEqual(end, getdate("2025-06-30"))

    def test_quarterly_q4_year_end(self):
        start, end = calculate_billing_period("Quarterly", "2025-11-15")
        self.assertEqual(start, getdate("2025-10-01"))
        self.assertEqual(end, getdate("2025-12-31"))

    def test_semi_annual_h1(self):
        start, end = calculate_billing_period("Semi-Annual", "2025-03-15")
        self.assertEqual(start, getdate("2025-01-01"))
        self.assertEqual(end, getdate("2025-06-30"))

    def test_semi_annual_h2(self):
        start, end = calculate_billing_period("Semi-Annual", "2025-09-15")
        self.assertEqual(start, getdate("2025-07-01"))
        self.assertEqual(end, getdate("2025-12-31"))

    def test_semi_annual_boundary_june(self):
        # month == 6 -> H1
        start, end = calculate_billing_period("Semi-Annual", "2025-06-30")
        self.assertEqual(start, getdate("2025-01-01"))
        self.assertEqual(end, getdate("2025-06-30"))

    def test_annual(self):
        start, end = calculate_billing_period("Annual", "2025-08-20")
        self.assertEqual(start, getdate("2025-01-01"))
        self.assertEqual(end, getdate("2025-12-31"))

    def test_unknown_defaults_to_monthly(self):
        start, end = calculate_billing_period("Bogus", "2025-12-05")
        self.assertEqual(start, getdate("2025-12-01"))
        self.assertEqual(end, getdate("2025-12-31"))

    # ----- Custom -----
    def test_custom_days(self):
        start, end = calculate_billing_period("Custom", "2025-03-10", 5, "Days")
        self.assertEqual(start, getdate("2025-03-10"))
        self.assertEqual(end, getdate("2025-03-14"))  # 5 days inclusive

    def test_custom_weeks(self):
        # Wednesday 2025-03-12 -> Monday start 2025-03-10, 2 weeks -> 14 days inclusive
        start, end = calculate_billing_period("Custom", "2025-03-12", 2, "Weeks")
        self.assertEqual(start, getdate("2025-03-10"))
        self.assertEqual(end, getdate("2025-03-23"))

    def test_custom_months(self):
        start, end = calculate_billing_period("Custom", "2025-01-20", 3, "Months")
        self.assertEqual(start, getdate("2025-01-01"))
        self.assertEqual(end, getdate("2025-03-31"))

    def test_custom_years(self):
        start, end = calculate_billing_period("Custom", "2025-06-10", 2, "Years")
        self.assertEqual(start, getdate("2025-01-01"))
        self.assertEqual(end, getdate("2026-12-31"))

    def test_custom_invalid_unit_falls_back_monthly(self):
        start, end = calculate_billing_period("Custom", "2025-03-15", 1, "Decades")
        self.assertEqual(start, getdate("2025-03-01"))
        self.assertEqual(end, getdate("2025-03-31"))

    def test_custom_invalid_number_defaults(self):
        start, end = calculate_billing_period("Custom", "2025-03-15", 0, "Months")
        # number coerced to 1 -> single month
        self.assertEqual(start, getdate("2025-03-01"))
        self.assertEqual(end, getdate("2025-03-31"))


class TestDeriveCoverageFromInvoiceData(EnhancedTestCase):
    def test_requires_posting_date(self):
        with self.assertRaises(ValueError) as ctx:
            derive_coverage_from_invoice_data(None)
        self.assertIn("posting_date is required", str(ctx.exception))

    def test_invalid_posting_date_format(self):
        with self.assertRaises(ValueError) as ctx:
            derive_coverage_from_invoice_data("not-a-date")
        self.assertIn("Invalid posting_date", str(ctx.exception))

    def test_monthly_from_posting_date_no_last_invoice(self):
        # No last invoice -> coverage starts at posting date; monthly -> +1 month -1 day
        start, end = derive_coverage_from_invoice_data("2025-03-15", billing_frequency="Monthly")
        self.assertEqual(start, getdate("2025-03-15"))
        self.assertEqual(end, getdate("2025-04-14"))

    def test_daily_start_equals_end(self):
        # Daily coverage end == start; function allows equal for the derived case?
        # NOTE: final validation requires end > start, so Daily would raise. Verify behavior.
        with self.assertRaises(ValueError) as ctx:
            derive_coverage_from_invoice_data("2025-03-15", billing_frequency="Daily")
        self.assertIn("must be after start", str(ctx.exception))

    def test_weekly_coverage(self):
        start, end = derive_coverage_from_invoice_data("2025-03-15", billing_frequency="Weekly")
        self.assertEqual(start, getdate("2025-03-15"))
        self.assertEqual(end, getdate("2025-03-21"))

    def test_quarterly_coverage(self):
        start, end = derive_coverage_from_invoice_data("2025-01-01", billing_frequency="Quarterly")
        self.assertEqual(start, getdate("2025-01-01"))
        self.assertEqual(end, getdate("2025-03-31"))

    def test_annual_coverage(self):
        start, end = derive_coverage_from_invoice_data("2025-01-01", billing_frequency="Annual")
        self.assertEqual(start, getdate("2025-01-01"))
        self.assertEqual(end, getdate("2025-12-31"))

    def test_coverage_start_day_after_last_invoice(self):
        # last_invoice_date 2025-03-31, posting 2025-04-01 -> coverage starts 2025-04-01
        start, end = derive_coverage_from_invoice_data(
            "2025-04-01", last_invoice_date="2025-03-31", billing_frequency="Monthly"
        )
        self.assertEqual(start, getdate("2025-04-01"))
        self.assertEqual(end, getdate("2025-04-30"))

    def test_large_gap_resets_forward_to_posting_date(self):
        # last_invoice coverage start would be 2024-02-02, posting 2025-04-01 -> gap > 30 days
        # so coverage_start resets to posting_date. The code logs this reset intentionally.
        self.expectErrorLog("Large coverage gap detected")
        start, end = derive_coverage_from_invoice_data(
            "2025-04-01", last_invoice_date="2024-02-01", billing_frequency="Monthly"
        )
        self.assertEqual(start, getdate("2025-04-01"))
        self.assertEqual(end, getdate("2025-04-30"))

    def test_small_gap_keeps_derived_start(self):
        # last_invoice 2025-03-20 -> start 2025-03-21, posting 2025-04-01 -> gap 11 days (<30) kept
        start, end = derive_coverage_from_invoice_data(
            "2025-04-01", last_invoice_date="2025-03-20", billing_frequency="Monthly"
        )
        self.assertEqual(start, getdate("2025-03-21"))
        self.assertEqual(end, getdate("2025-04-20"))

    def test_unknown_frequency_uses_next_invoice_date(self):
        # No billing_frequency -> falls to next_invoice_date branch; coverage_end = next - 1
        start, end = derive_coverage_from_invoice_data("2025-03-01", next_invoice_date="2025-04-01")
        self.assertEqual(start, getdate("2025-03-01"))
        self.assertEqual(end, getdate("2025-03-31"))

    def test_unknown_frequency_no_next_invoice_date_monthly_fallback(self):
        start, end = derive_coverage_from_invoice_data("2025-03-01")
        self.assertEqual(start, getdate("2025-03-01"))
        self.assertEqual(end, getdate("2025-03-31"))

    def test_invalid_next_invoice_date_before_start_uses_monthly_fallback(self):
        # next_invoice_date before start -> coverage_end <= start -> monthly fallback
        start, end = derive_coverage_from_invoice_data("2025-03-01", next_invoice_date="2025-02-01")
        self.assertEqual(start, getdate("2025-03-01"))
        self.assertEqual(end, getdate("2025-03-31"))

    def test_unknown_named_frequency_logs_and_falls_back(self):
        # billing_frequency provided but not in valid list -> set to None -> monthly fallback
        self.expectErrorLog("Unknown billing frequency")
        start, end = derive_coverage_from_invoice_data("2025-03-01", billing_frequency="Fortnightly")
        self.assertEqual(start, getdate("2025-03-01"))
        self.assertEqual(end, getdate("2025-03-31"))
