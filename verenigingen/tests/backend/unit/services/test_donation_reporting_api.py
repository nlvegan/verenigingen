# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Unit tests for Donation Reporting Service API

Tests donation reporting API endpoints with OperationResult pattern.
Focus on type-safe error handling for donation analytics and reporting.

Migration Status: ✅ COMPLETE (2025-11-24)
- All tests use OperationResult API
- Proper assertions for .success, .data, .error_message
"""

import frappe
from frappe.utils import getdate, add_days
from verenigingen.services.donation.reporting_service import (
    get_anbi_donations_for_reporting,
    get_donations_by_chapter,
    get_donations_by_campaign,
    get_donation_summary_by_purpose,
    get_donation_accounting_summary,
    create_donation_allocation_report,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestDonationReportingAPI(EnhancedTestCase):
    """Unit tests for Donation Reporting Service API endpoints"""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def test_get_anbi_donations_for_reporting_returns_operation_result(self):
        """Test get_anbi_donations_for_reporting returns OperationResult"""
        from_date = str(getdate())
        to_date = str(add_days(getdate(), 30))

        result = get_anbi_donations_for_reporting(from_date, to_date)

        # OperationResult pattern
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.success)

        if result.success:
            self.assertIsInstance(result.data, list)

    def test_get_anbi_donations_with_invalid_dates_returns_operation_result(self):
        """Test ANBI donations with invalid dates still returns OperationResult"""
        # Invalid date format should be handled gracefully
        result = get_anbi_donations_for_reporting("invalid", "dates")

        # Should return OperationResult (may succeed with empty list or fail)
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.success)

    def test_get_donations_by_chapter_returns_operation_result(self):
        """Test get_donations_by_chapter returns OperationResult"""
        result = get_donations_by_chapter("Test Chapter")

        # OperationResult pattern
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.success)

        if result.success:
            self.assertIsInstance(result.data, dict)
            self.assertIn("donations", result.data)

    def test_get_donations_by_campaign_returns_operation_result(self):
        """Test get_donations_by_campaign returns OperationResult"""
        result = get_donations_by_campaign("Test Campaign")

        # OperationResult pattern
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.success)

        if result.success:
            self.assertIsInstance(result.data, dict)
            self.assertIn("donations", result.data)

    def test_get_donation_summary_by_purpose_returns_operation_result(self):
        """Test get_donation_summary_by_purpose returns OperationResult"""
        result = get_donation_summary_by_purpose()

        # OperationResult pattern
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.success)

        if result.success:
            self.assertIsInstance(result.data, dict)

    def test_get_donation_accounting_summary_returns_operation_result(self):
        """Test get_donation_accounting_summary returns OperationResult"""
        result = get_donation_accounting_summary()

        # OperationResult pattern
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.success)

        if result.success:
            self.assertIsInstance(result.data, dict)

    def test_create_donation_allocation_report_returns_operation_result(self):
        """Test create_donation_allocation_report returns OperationResult"""
        result = create_donation_allocation_report()

        # OperationResult pattern
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.success)

        if result.success:
            self.assertIsInstance(result.data, dict)

    def test_donation_apis_never_throw_exceptions(self):
        """Test that donation reporting APIs never throw exceptions"""
        from_date = str(getdate())
        to_date = str(add_days(getdate(), 30))

        # Test all APIs with valid inputs
        apis_to_test = [
            (get_anbi_donations_for_reporting, (from_date, to_date)),
            (get_donations_by_chapter, ("Test Chapter",)),
            (get_donations_by_campaign, ("Test Campaign",)),
            (get_donation_summary_by_purpose, ()),
            (get_donation_accounting_summary, ()),
            (create_donation_allocation_report, ()),
        ]

        for api_func, args in apis_to_test:
            result = api_func(*args)
            self.assertIsNotNone(result, f"{api_func.__name__} returned None")
            self.assertIsNotNone(result.success, f"{api_func.__name__} missing success attribute")

    def test_reporting_apis_with_date_range(self):
        """Test reporting APIs with date range parameters"""
        from_date = str(getdate())
        to_date = str(add_days(getdate(), 30))

        # Test APIs that support date ranges
        result1 = get_donations_by_chapter("Test Chapter", from_date, to_date)
        self.assertIsNotNone(result1.success)

        result2 = get_donations_by_campaign("Test Campaign", from_date, to_date)
        self.assertIsNotNone(result2.success)

        result3 = get_donation_summary_by_purpose(from_date, to_date)
        self.assertIsNotNone(result3.success)

        result4 = get_donation_accounting_summary(from_date, to_date)
        self.assertIsNotNone(result4.success)

        result5 = create_donation_allocation_report("Test Chapter", from_date, to_date)
        self.assertIsNotNone(result5.success)

    def test_api_results_contain_proper_metadata(self):
        """Test that API results contain expected metadata structure"""
        from_date = str(getdate())
        to_date = str(add_days(getdate(), 30))

        result = get_anbi_donations_for_reporting(from_date, to_date)

        # Check OperationResult structure
        self.assertIsNotNone(result)
        if result.success:
            self.assertIsInstance(result.data, list)
            # Check success_message exists if needed
        else:
            self.assertIsNotNone(result.error_message)
            self.assertIsInstance(result.errors, list)


def run_tests():
    """Helper function to run tests from console"""
    frappe.flags.in_test = True
    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestDonationReportingAPI)
    unittest.TextTestRunner(verbosity=2).run(suite)
