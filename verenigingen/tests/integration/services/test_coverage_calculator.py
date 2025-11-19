# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Integration tests for CoverageCalculator service.

Tests the coverage period calculation logic extracted from MembershipDuesSchedule.
Uses Enhanced Test Factory for real database operations - no mocks.
"""

import unittest
from datetime import date

import frappe

from verenigingen.services.billing.coverage_calculator import CoverageCalculator, CoveragePeriodResult
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestCoverageCalculator(EnhancedTestCase):
    """Test the CoverageCalculator service with real database operations"""

    def setUp(self):
        """Set up test fixtures with real data"""
        super().setUp()

        # Create real test member
        self.member = self.create_test_member(
            first_name="Coverage", last_name="Test", birth_date="1985-05-15"
        )

        # Create customer and link to member
        self.customer_doc = frappe.new_doc("Customer")
        self.customer_doc.customer_name = f"{self.member.first_name} {self.member.last_name}"
        self.customer_doc.customer_type = "Individual"
        self.customer_doc.insert()

        self.member.customer = self.customer_doc.name
        self.member.save()
        self.member.reload()

        # Create membership (which also creates dues schedule automatically)
        self.membership = self.create_test_membership(
            member_name=self.member.name, membership_type_name="Regular Member"
        )

        # Get the automatically created dues schedule
        schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": self.member.name, "status": "Active"},
            limit=1,
        )
        if schedules:
            self.schedule = frappe.get_doc("Membership Dues Schedule", schedules[0].name)
        else:
            frappe.throw("No schedule was created with membership")

        # Reload member to ensure we have latest data
        self.member.reload()

    # ========== Happy Path Tests ==========

    def test_first_invoice_coverage_calculation(self):
        """Test coverage calculation for first invoice (no previous coverage)"""
        # Arrange
        calculator = CoverageCalculator(self.schedule)

        # Act
        result = calculator.calculate_next_coverage_period(self.member)

        # Assert
        self.assertTrue(result.is_valid())
        self.assertIsNotNone(result.start_date)
        self.assertIsNotNone(result.end_date)
        self.assertEqual(result.calculation_method, "first_invoice")
        self.assertIn("previous_coverage_end", result.metadata)
        self.assertIsNone(result.metadata["previous_coverage_end"])

    def test_sequential_coverage_builds_on_previous(self):
        """Test that sequential coverage starts day after previous invoice"""
        # Arrange - create first invoice with coverage dates
        from verenigingen.services.billing.invoice_generator import InvoiceGenerator

        generator = InvoiceGenerator(self.schedule)
        first_result = generator.generate_invoice(
            coverage_start=date(2025, 1, 1),
            coverage_end=date(2025, 1, 31),
            member_doc=self.member
        )
        self.assertTrue(first_result.success)
        frappe.db.commit()  # Ensure invoice is visible to queries

        # Act - calculate next coverage period
        calculator = CoverageCalculator(self.schedule)
        result = calculator.calculate_next_coverage_period(self.member)

        # Assert
        self.assertTrue(result.is_valid())
        self.assertEqual(result.start_date, date(2025, 2, 1))  # Day after previous end
        self.assertEqual(result.calculation_method, "sequential")
        self.assertEqual(result.metadata["previous_coverage_end"], date(2025, 1, 31))

    # ========== Billing Frequency Tests ==========

    def test_daily_billing_same_start_end(self):
        """Test that daily billing allows start==end"""
        # Arrange - change schedule to daily billing
        original_frequency = self.schedule.billing_frequency
        self.schedule.billing_frequency = "Daily"
        self.schedule.save()
        frappe.db.commit()

        try:
            calculator = CoverageCalculator(self.schedule)

            # Act
            result = calculator.calculate_next_coverage_period(self.member, force_date=date(2025, 3, 15))

            # Assert
            self.assertTrue(result.is_valid())
            self.assertEqual(result.start_date, result.end_date)  # Same day for daily billing
            self.assertEqual(result.start_date, date(2025, 3, 15))

        finally:
            # Restore original frequency
            self.schedule.billing_frequency = original_frequency
            self.schedule.save()
            frappe.db.commit()

    def test_quarterly_billing_coverage_span(self):
        """Test quarterly billing creates 3-month coverage"""
        # Arrange
        original_frequency = self.schedule.billing_frequency
        self.schedule.billing_frequency = "Quarterly"
        self.schedule.save()
        frappe.db.commit()

        try:
            calculator = CoverageCalculator(self.schedule)

            # Act
            result = calculator.calculate_next_coverage_period(self.member, force_date=date(2025, 1, 1))

            # Assert
            self.assertTrue(result.is_valid())
            self.assertEqual(result.start_date, date(2025, 1, 1))
            self.assertEqual(result.end_date, date(2025, 3, 31))  # 3 months (Q1)

        finally:
            self.schedule.billing_frequency = original_frequency
            self.schedule.save()
            frappe.db.commit()

    # ========== Date-Based Fallback Tests ==========

    def test_date_based_fallback_when_sequential_disabled(self):
        """Test fallback to date-based calculation when sequential is disabled"""
        # Arrange
        calculator = CoverageCalculator(self.schedule)

        # Act - explicitly disable sequential
        result = calculator.calculate_next_coverage_period(
            self.member,
            force_date=date(2025, 3, 15),
            use_sequential=False
        )

        # Assert
        self.assertTrue(result.is_valid())
        self.assertEqual(result.calculation_method, "date_based")
        # Date-based calculation uses billing_period_calculator logic
        # Result should be a valid period (start before end)
        self.assertLess(result.start_date, result.end_date or result.start_date)

    # ========== Database Query Tests ==========

    def test_get_latest_coverage_end_date_no_invoices(self):
        """Test latest coverage query when no invoices exist"""
        # Arrange
        calculator = CoverageCalculator(self.schedule)

        # Act
        latest_end = calculator.get_latest_coverage_end_date(self.member)

        # Assert
        self.assertIsNone(latest_end)

    def test_get_latest_coverage_end_date_with_invoice(self):
        """Test latest coverage query returns correct date"""
        # Arrange - create invoice with coverage dates
        from verenigingen.services.billing.invoice_generator import InvoiceGenerator

        generator = InvoiceGenerator(self.schedule)
        result = generator.generate_invoice(
            coverage_start=date(2025, 1, 1),
            coverage_end=date(2025, 1, 31),
            member_doc=self.member
        )
        self.assertTrue(result.success)
        frappe.db.commit()

        # Act
        calculator = CoverageCalculator(self.schedule)
        latest_end = calculator.get_latest_coverage_end_date(self.member)

        # Assert
        self.assertEqual(latest_end, date(2025, 1, 31))

    # ========== Cutoff Date Tests ==========

    def test_should_generate_for_cutoff_no_previous_coverage(self):
        """Test cutoff logic when no previous coverage exists"""
        # Arrange
        calculator = CoverageCalculator(self.schedule)
        cutoff_date = date(2025, 12, 31)

        # Act
        should_generate = calculator.should_generate_invoice_for_cutoff(cutoff_date)

        # Assert
        self.assertTrue(should_generate)  # No coverage, should generate

    def test_should_generate_for_cutoff_coverage_sufficient(self):
        """Test cutoff logic when coverage already extends past cutoff"""
        # Arrange - create invoice covering through cutoff
        from verenigingen.services.billing.invoice_generator import InvoiceGenerator

        generator = InvoiceGenerator(self.schedule)
        result = generator.generate_invoice(
            coverage_start=date(2025, 1, 1),
            coverage_end=date(2025, 12, 31),
            member_doc=self.member
        )
        self.assertTrue(result.success)
        frappe.db.commit()

        # Act
        calculator = CoverageCalculator(self.schedule)
        should_generate = calculator.should_generate_invoice_for_cutoff(date(2025, 6, 30))

        # Assert
        self.assertFalse(should_generate)  # Coverage extends past cutoff

    def test_should_generate_for_cutoff_coverage_insufficient(self):
        """Test cutoff logic when coverage doesn't reach cutoff"""
        # Arrange - create invoice with limited coverage
        from verenigingen.services.billing.invoice_generator import InvoiceGenerator

        generator = InvoiceGenerator(self.schedule)
        result = generator.generate_invoice(
            coverage_start=date(2025, 1, 1),
            coverage_end=date(2025, 1, 31),
            member_doc=self.member
        )
        self.assertTrue(result.success)
        frappe.db.commit()

        # Act
        calculator = CoverageCalculator(self.schedule)
        should_generate = calculator.should_generate_invoice_for_cutoff(date(2025, 12, 31))

        # Assert
        self.assertTrue(should_generate)  # Coverage doesn't reach cutoff

    # ========== Validation Tests ==========

    def test_force_date_override(self):
        """Test that force_date overrides default date logic"""
        # Arrange
        calculator = CoverageCalculator(self.schedule)
        force_date = date(2025, 6, 15)

        # Act
        result = calculator.calculate_next_coverage_period(self.member, force_date=force_date)

        # Assert
        self.assertTrue(result.is_valid())
        self.assertEqual(result.start_date, force_date)
        self.assertEqual(result.metadata["force_date"], force_date)

    def test_custom_frequency_calculation(self):
        """Test coverage calculation with custom frequency"""
        # Arrange - set custom frequency (every 3 months)
        original_frequency = self.schedule.billing_frequency
        self.schedule.billing_frequency = "Custom"
        self.schedule.custom_frequency_number = 3
        self.schedule.custom_frequency_unit = "Months"
        self.schedule.save()
        frappe.db.commit()

        try:
            calculator = CoverageCalculator(self.schedule)

            # Act
            result = calculator.calculate_next_coverage_period(self.member, force_date=date(2025, 1, 1))

            # Assert
            self.assertTrue(result.is_valid())
            self.assertEqual(result.start_date, date(2025, 1, 1))
            self.assertEqual(result.end_date, date(2025, 3, 31))  # 3 months coverage

        finally:
            self.schedule.billing_frequency = original_frequency
            self.schedule.save()
            frappe.db.commit()
