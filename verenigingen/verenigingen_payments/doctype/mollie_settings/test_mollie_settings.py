# Copyright (c) 2025, Verenigingen and Contributors
# See license.txt

from datetime import datetime

import frappe
from dateutil.relativedelta import relativedelta
from freezegun import freeze_time

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMollieSettings(EnhancedTestCase):
    """Test Mollie Settings business logic validation"""

    def test_mollie_settings_validation(self):
        """Test basic Mollie settings validation"""
        # This test validates the enhanced test framework is working
        # Mollie Settings specific business logic tests can be added here
        self.assertTrue(True)  # Placeholder for actual business logic tests

    @freeze_time("2025-11-04 10:00:00")
    def test_quarterly_payment_date_calculation(self):
        """Test quarterly payment date calculation (1,4,7,10)"""
        # Frozen at: November 4, 2025

        settings = frappe.get_single("Mollie Settings")
        settings.quarterly_yearly_payment_months = "1,4,7,10"
        settings.payment_day_of_month = 25

        # Should return January 25, 2026 (2 months ahead)
        result = settings.get_next_payment_date_for_scheduled_months(min_months_ahead=2)

        self.assertEqual(result, "2026-01-25")

        # Verify it's the correct month
        result_date = datetime.strptime(result, "%Y-%m-%d").date()
        self.assertEqual(result_date.month, 1)  # January
        self.assertEqual(result_date.day, 25)

    @freeze_time("2025-11-04 10:00:00")
    def test_yearly_payment_date_calculation(self):
        """Test yearly payment date calculation (single month)"""
        # Frozen at: November 4, 2025

        settings = frappe.get_single("Mollie Settings")
        settings.quarterly_yearly_payment_months = "9"  # September only
        settings.payment_day_of_month = 25

        # Should return September 25, 2026 (10 months ahead, skipping Sep 2025)
        result = settings.get_next_payment_date_for_scheduled_months(min_months_ahead=2)

        self.assertEqual(result, "2026-09-25")

        # Verify it's at least 2 months ahead
        result_date = datetime.strptime(result, "%Y-%m-%d").date()
        today = datetime(2025, 11, 4).date()
        min_date = today + relativedelta(months=2)
        self.assertGreaterEqual(result_date, min_date)

    @freeze_time("2025-11-04 10:00:00")
    def test_custom_payment_day_of_month(self):
        """Test payment date calculation with custom payment day"""
        # Frozen at: November 4, 2025

        settings = frappe.get_single("Mollie Settings")
        settings.quarterly_yearly_payment_months = "1,4,7,10"
        settings.payment_day_of_month = 15  # Custom day: 15th instead of 25th

        # Should return January 15, 2026 (2 months ahead)
        result = settings.get_next_payment_date_for_scheduled_months(min_months_ahead=2)

        self.assertEqual(result, "2026-01-15")

        # Verify it's the correct day
        result_date = datetime.strptime(result, "%Y-%m-%d").date()
        self.assertEqual(result_date.day, 15)

    @freeze_time("2025-11-04 10:00:00")
    def test_payment_date_with_invalid_months(self):
        """Test payment date calculation with invalid month values"""
        # Frozen at: November 4, 2025

        settings = frappe.get_single("Mollie Settings")
        settings.payment_day_of_month = 25

        # Test with invalid months (should filter to valid 1,4,7,10)
        settings.quarterly_yearly_payment_months = "1,4,7,10,13,0,-5"
        result = settings.get_next_payment_date_for_scheduled_months(min_months_ahead=2)

        # Should still work with the valid months
        self.assertEqual(result, "2026-01-25")

        # Test with no valid months
        settings.quarterly_yearly_payment_months = "13,14,15"
        result = settings.get_next_payment_date_for_scheduled_months(min_months_ahead=2)
        self.assertIsNone(result)

        # Test with empty string
        settings.quarterly_yearly_payment_months = ""
        result = settings.get_next_payment_date_for_scheduled_months(min_months_ahead=2)
        self.assertIsNone(result)

        # Test with None
        settings.quarterly_yearly_payment_months = None
        result = settings.get_next_payment_date_for_scheduled_months(min_months_ahead=2)
        self.assertIsNone(result)
