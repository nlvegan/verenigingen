# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Unit tests for billing_period_calculator utilities.
Tests pure calculation logic extracted from MembershipDuesSchedule.
"""

import unittest
from datetime import date

from verenigingen.utils.billing_period_calculator import (
    calculate_billing_period,
    calculate_next_invoice_date,
)


class TestCalculateNextInvoiceDate(unittest.TestCase):
    """Test next invoice date calculations for all billing frequencies"""

    def test_daily_frequency(self):
        """Daily billing should add 1 day"""
        result = calculate_next_invoice_date("Daily", date(2025, 1, 15))
        self.assertEqual(result, date(2025, 1, 16))

    def test_weekly_frequency(self):
        """Weekly billing should add 7 days"""
        result = calculate_next_invoice_date("Weekly", date(2025, 1, 15))
        self.assertEqual(result, date(2025, 1, 22))

    def test_monthly_frequency(self):
        """Monthly billing should add 1 month"""
        result = calculate_next_invoice_date("Monthly", date(2025, 1, 15))
        self.assertEqual(result, date(2025, 2, 15))

    def test_monthly_frequency_end_of_month(self):
        """Monthly billing should handle end-of-month dates"""
        result = calculate_next_invoice_date("Monthly", date(2025, 1, 31))
        # frappe.utils.add_months handles this, should go to Feb 28 or last day
        self.assertIn(result.month, [2, 3])

    def test_quarterly_frequency(self):
        """Quarterly billing should add 3 months"""
        result = calculate_next_invoice_date("Quarterly", date(2025, 1, 15))
        self.assertEqual(result, date(2025, 4, 15))

    def test_semi_annual_frequency(self):
        """Semi-annual billing should add 6 months"""
        result = calculate_next_invoice_date("Semi-Annual", date(2025, 1, 15))
        self.assertEqual(result, date(2025, 7, 15))

    def test_annual_frequency(self):
        """Annual billing should add 1 year"""
        result = calculate_next_invoice_date("Annual", date(2025, 1, 15))
        self.assertEqual(result, date(2026, 1, 15))

    def test_custom_frequency_days(self):
        """Custom frequency with days unit"""
        result = calculate_next_invoice_date(
            "Custom", date(2025, 1, 15), custom_frequency_number=5, custom_frequency_unit="Days"
        )
        self.assertEqual(result, date(2025, 1, 20))

    def test_custom_frequency_weeks(self):
        """Custom frequency with weeks unit"""
        result = calculate_next_invoice_date(
            "Custom", date(2025, 1, 15), custom_frequency_number=2, custom_frequency_unit="Weeks"
        )
        self.assertEqual(result, date(2025, 1, 29))

    def test_custom_frequency_months(self):
        """Custom frequency with months unit"""
        result = calculate_next_invoice_date(
            "Custom", date(2025, 1, 15), custom_frequency_number=3, custom_frequency_unit="Months"
        )
        self.assertEqual(result, date(2025, 4, 15))

    def test_custom_frequency_years(self):
        """Custom frequency with years unit"""
        result = calculate_next_invoice_date(
            "Custom", date(2025, 1, 15), custom_frequency_number=2, custom_frequency_unit="Years"
        )
        self.assertEqual(result, date(2027, 1, 15))

    def test_custom_frequency_defaults(self):
        """Custom frequency should default to 1 month if parameters missing"""
        result = calculate_next_invoice_date("Custom", date(2025, 1, 15))
        self.assertEqual(result, date(2025, 2, 15))

    def test_custom_frequency_invalid_unit(self):
        """Custom frequency should fallback to monthly for invalid unit"""
        result = calculate_next_invoice_date(
            "Custom",
            date(2025, 1, 15),
            custom_frequency_number=5,
            custom_frequency_unit="InvalidUnit",
        )
        self.assertEqual(result, date(2025, 2, 15))

    def test_unknown_frequency_defaults_to_monthly(self):
        """Unknown frequency should default to monthly"""
        result = calculate_next_invoice_date("UnknownFrequency", date(2025, 1, 15))
        self.assertEqual(result, date(2025, 2, 15))

    def test_defaults_to_today_if_no_date(self):
        """Should use today if no from_date provided"""
        result = calculate_next_invoice_date("Monthly")
        self.assertIsInstance(result, date)


class TestCalculateBillingPeriod(unittest.TestCase):
    """Test billing period calculations for all frequencies"""

    def test_daily_period(self):
        """Daily period should be single day"""
        start, end = calculate_billing_period("Daily", date(2025, 1, 15))
        self.assertEqual(start, date(2025, 1, 15))
        self.assertEqual(end, date(2025, 1, 15))

    def test_weekly_period(self):
        """Weekly period should be Monday to Sunday"""
        # Jan 15, 2025 is a Wednesday
        start, end = calculate_billing_period("Weekly", date(2025, 1, 15))
        self.assertEqual(start, date(2025, 1, 13))  # Monday
        self.assertEqual(end, date(2025, 1, 19))  # Sunday

    def test_weekly_period_on_monday(self):
        """Weekly period starting on Monday"""
        start, end = calculate_billing_period("Weekly", date(2025, 1, 13))
        self.assertEqual(start, date(2025, 1, 13))  # Monday
        self.assertEqual(end, date(2025, 1, 19))  # Sunday

    def test_monthly_period(self):
        """Monthly period should be first to last day of month"""
        start, end = calculate_billing_period("Monthly", date(2025, 1, 15))
        self.assertEqual(start, date(2025, 1, 1))
        self.assertEqual(end, date(2025, 1, 31))

    def test_monthly_period_february(self):
        """Monthly period for February (non-leap year)"""
        start, end = calculate_billing_period("Monthly", date(2025, 2, 15))
        self.assertEqual(start, date(2025, 2, 1))
        self.assertEqual(end, date(2025, 2, 28))

    def test_monthly_period_december(self):
        """Monthly period for December"""
        start, end = calculate_billing_period("Monthly", date(2025, 12, 15))
        self.assertEqual(start, date(2025, 12, 1))
        self.assertEqual(end, date(2025, 12, 31))

    def test_quarterly_period_q1(self):
        """Quarterly period for Q1 (Jan-Mar)"""
        start, end = calculate_billing_period("Quarterly", date(2025, 2, 15))
        self.assertEqual(start, date(2025, 1, 1))
        self.assertEqual(end, date(2025, 3, 31))

    def test_quarterly_period_q2(self):
        """Quarterly period for Q2 (Apr-Jun)"""
        start, end = calculate_billing_period("Quarterly", date(2025, 5, 15))
        self.assertEqual(start, date(2025, 4, 1))
        self.assertEqual(end, date(2025, 6, 30))

    def test_quarterly_period_q3(self):
        """Quarterly period for Q3 (Jul-Sep)"""
        start, end = calculate_billing_period("Quarterly", date(2025, 8, 15))
        self.assertEqual(start, date(2025, 7, 1))
        self.assertEqual(end, date(2025, 9, 30))

    def test_quarterly_period_q4(self):
        """Quarterly period for Q4 (Oct-Dec)"""
        start, end = calculate_billing_period("Quarterly", date(2025, 11, 15))
        self.assertEqual(start, date(2025, 10, 1))
        self.assertEqual(end, date(2025, 12, 31))

    def test_semi_annual_period_h1(self):
        """Semi-annual period for H1 (Jan-Jun)"""
        start, end = calculate_billing_period("Semi-Annual", date(2025, 3, 15))
        self.assertEqual(start, date(2025, 1, 1))
        self.assertEqual(end, date(2025, 6, 30))

    def test_semi_annual_period_h2(self):
        """Semi-annual period for H2 (Jul-Dec)"""
        start, end = calculate_billing_period("Semi-Annual", date(2025, 9, 15))
        self.assertEqual(start, date(2025, 7, 1))
        self.assertEqual(end, date(2025, 12, 31))

    def test_annual_period(self):
        """Annual period should be Jan 1 to Dec 31"""
        start, end = calculate_billing_period("Annual", date(2025, 6, 15))
        self.assertEqual(start, date(2025, 1, 1))
        self.assertEqual(end, date(2025, 12, 31))

    def test_custom_period_days(self):
        """Custom period with days unit"""
        start, end = calculate_billing_period(
            "Custom", date(2025, 1, 15), custom_frequency_number=5, custom_frequency_unit="Days"
        )
        self.assertEqual(start, date(2025, 1, 15))
        self.assertEqual(end, date(2025, 1, 19))

    def test_custom_period_weeks(self):
        """Custom period with weeks unit"""
        start, end = calculate_billing_period(
            "Custom", date(2025, 1, 15), custom_frequency_number=2, custom_frequency_unit="Weeks"
        )
        self.assertEqual(start, date(2025, 1, 13))  # Monday of week
        self.assertEqual(end, date(2025, 1, 26))  # 2 weeks later

    def test_custom_period_months(self):
        """Custom period with months unit"""
        start, end = calculate_billing_period(
            "Custom", date(2025, 1, 15), custom_frequency_number=3, custom_frequency_unit="Months"
        )
        self.assertEqual(start, date(2025, 1, 1))
        self.assertEqual(end, date(2025, 3, 31))

    def test_custom_period_years(self):
        """Custom period with years unit"""
        start, end = calculate_billing_period(
            "Custom", date(2025, 6, 15), custom_frequency_number=2, custom_frequency_unit="Years"
        )
        self.assertEqual(start, date(2025, 1, 1))
        self.assertEqual(end, date(2026, 12, 31))

    def test_custom_period_defaults(self):
        """Custom period should default to monthly if parameters missing"""
        start, end = calculate_billing_period("Custom", date(2025, 1, 15))
        self.assertEqual(start, date(2025, 1, 1))
        self.assertEqual(end, date(2025, 1, 31))

    def test_unknown_frequency_defaults_to_monthly(self):
        """Unknown frequency should default to monthly period"""
        start, end = calculate_billing_period("UnknownFrequency", date(2025, 1, 15))
        self.assertEqual(start, date(2025, 1, 1))
        self.assertEqual(end, date(2025, 1, 31))
