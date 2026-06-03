# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Integration tests for cutoff date calculations and coverage-based eligibility.

These tests specifically target the bugs fixed in:
1. Quarterly cutoff date calculation (year in past)
2. Stale next_invoice_date overriding coverage data
3. Timing check blocking generation for coverage gaps

Tests all billing frequencies (Monthly, Quarterly, Yearly) to catch regression.
"""

import unittest
from datetime import date
from unittest.mock import Mock, patch

import frappe
from frappe.utils import add_days, add_months, getdate, today

from verenigingen.services.billing.coverage_calculator import CoverageCalculator
from verenigingen.services.billing.eligibility_checker import EligibilityChecker
from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import (
    calculate_cutoff_date_for_period,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestCutoffDateCalculations(EnhancedTestCase):
    """Test cutoff date calculations for all billing frequencies"""

    def setUp(self):
        """Set up test fixtures"""
        super().setUp()

        # Verenigingen Settings.creation_user is a mandatory field that is empty on
        # a freshly reset test site, which makes any full .save() of the Single
        # raise MandatoryError. Populate it (via set_single_value to bypass the
        # mandatory check) so the settings-toggling saves below succeed.
        if not frappe.db.get_single_value("Verenigingen Settings", "creation_user"):
            frappe.db.set_single_value("Verenigingen Settings", "creation_user", "Administrator")

        # Store original settings
        self.settings = frappe.get_single("Verenigingen Settings")
        self.original_cutoff_freq = self.settings.billing_cutoff_frequency
        self.original_book_year_start = getattr(self.settings, "book_year_start_month", 1)

    def tearDown(self):
        """Restore original settings"""
        self.settings.billing_cutoff_frequency = self.original_cutoff_freq
        self.settings.book_year_start_month = self.original_book_year_start
        self.settings.save()
        frappe.db.commit()
        super().tearDown()

    # ========== Monthly Cutoff Tests ==========

    def test_monthly_cutoff_end_of_month(self):
        """Test monthly cutoff returns end of current month"""
        # Arrange
        self.settings.billing_cutoff_frequency = "Monthly"
        self.settings.save()
        frappe.db.commit()

        # Mock today as mid-month
        with patch("verenigingen.services.billing.bulk_invoice_generation_service.today") as mock_today:
            mock_today.return_value = "2025-11-15"

            # Act
            cutoff = calculate_cutoff_date_for_period()

            # Assert
            self.assertEqual(cutoff, date(2025, 11, 30))

    def test_monthly_cutoff_december(self):
        """Test monthly cutoff handles December correctly (year rollover)"""
        # Arrange
        self.settings.billing_cutoff_frequency = "Monthly"
        self.settings.save()
        frappe.db.commit()

        # Mock today as December
        with patch("verenigingen.services.billing.bulk_invoice_generation_service.today") as mock_today:
            mock_today.return_value = "2025-12-15"

            # Act
            cutoff = calculate_cutoff_date_for_period()

            # Assert
            self.assertEqual(cutoff, date(2025, 12, 31))

    # ========== Quarterly Cutoff Tests (Bug Fix Validation) ==========

    def test_quarterly_cutoff_q4_not_year_in_past(self):
        """
        BUG FIX TEST: Quarterly cutoff should return current year, not previous year.

        Previous bug: When in November (Q4), quarter end is December 31.
        The logic incorrectly set quarter_end_year = today.year - 1 (2024)
        because quarter_end_month (12) > today.month (11).

        Fix: Quarter end in future months should use current year.
        """
        # Arrange
        self.settings.billing_cutoff_frequency = "Quarterly"
        self.settings.book_year_start_month = 1  # Jan 1 book year start
        self.settings.save()
        frappe.db.commit()

        # Mock today as November (Q4, but before quarter end)
        with patch("verenigingen.services.billing.bulk_invoice_generation_service.today") as mock_today:
            mock_today.return_value = "2025-11-15"

            # Act
            cutoff = calculate_cutoff_date_for_period()

            # Assert - should be end of Q4 2025, NOT 2024!
            self.assertEqual(cutoff, date(2025, 12, 31),
                           "Quarterly cutoff should use current year when quarter ends later in current year")

    def test_quarterly_cutoff_q1(self):
        """Test quarterly cutoff for Q1 (Jan-Mar)"""
        # Arrange
        self.settings.billing_cutoff_frequency = "Quarterly"
        self.settings.book_year_start_month = 1
        self.settings.save()
        frappe.db.commit()

        # Mock today as January (Q1)
        with patch("verenigingen.services.billing.bulk_invoice_generation_service.today") as mock_today:
            mock_today.return_value = "2025-01-15"

            # Act
            cutoff = calculate_cutoff_date_for_period()

            # Assert
            self.assertEqual(cutoff, date(2025, 3, 31))

    def test_quarterly_cutoff_q2(self):
        """Test quarterly cutoff for Q2 (Apr-Jun)"""
        # Arrange
        self.settings.billing_cutoff_frequency = "Quarterly"
        self.settings.book_year_start_month = 1
        self.settings.save()
        frappe.db.commit()

        # Mock today as May (Q2)
        with patch("verenigingen.services.billing.bulk_invoice_generation_service.today") as mock_today:
            mock_today.return_value = "2025-05-15"

            # Act
            cutoff = calculate_cutoff_date_for_period()

            # Assert
            self.assertEqual(cutoff, date(2025, 6, 30))

    def test_quarterly_cutoff_q3(self):
        """Test quarterly cutoff for Q3 (Jul-Sep)"""
        # Arrange
        self.settings.billing_cutoff_frequency = "Quarterly"
        self.settings.book_year_start_month = 1
        self.settings.save()
        frappe.db.commit()

        # Mock today as August (Q3)
        with patch("verenigingen.services.billing.bulk_invoice_generation_service.today") as mock_today:
            mock_today.return_value = "2025-08-15"

            # Act
            cutoff = calculate_cutoff_date_for_period()

            # Assert
            self.assertEqual(cutoff, date(2025, 9, 30))

    def test_quarterly_cutoff_fiscal_year_offset(self):
        """Test quarterly cutoff with non-calendar fiscal year (e.g., starts April 1)"""
        # Arrange - fiscal year starts April 1
        self.settings.billing_cutoff_frequency = "Quarterly"
        self.settings.book_year_start_month = 4  # April
        self.settings.save()
        frappe.db.commit()

        # Mock today as May (Q1 of fiscal year)
        with patch("verenigingen.services.billing.bulk_invoice_generation_service.today") as mock_today:
            mock_today.return_value = "2025-05-15"

            # Act
            cutoff = calculate_cutoff_date_for_period()

            # Assert - Q1 ends June 30
            self.assertEqual(cutoff, date(2025, 6, 30))

    # ========== Yearly Cutoff Tests ==========

    def test_yearly_cutoff_calendar_year(self):
        """Test yearly cutoff for calendar year (Jan 1 - Dec 31)"""
        # Arrange
        self.settings.billing_cutoff_frequency = "Yearly"
        self.settings.book_year_start_month = 1
        self.settings.book_year_start_day = 1
        self.settings.book_year_end_month = 12
        self.settings.book_year_end_day = 31
        self.settings.save()
        frappe.db.commit()

        # Mock today as mid-year
        with patch("verenigingen.services.billing.bulk_invoice_generation_service.today") as mock_today:
            mock_today.return_value = "2025-06-15"

            # Act
            cutoff = calculate_cutoff_date_for_period()

            # Assert - for a calendar-year book year (Jan 1 - Dec 31) the end month
            # (12) does NOT precede the start month (1), so the book year ends in the
            # same calendar year it started. With today in 2025 the cutoff is the end
            # of the current book year: 2025-12-31.
            self.assertEqual(cutoff, date(2025, 12, 31))

    def test_yearly_cutoff_fiscal_year(self):
        """Test yearly cutoff for fiscal year (Apr 1 - Mar 31)"""
        # Arrange - fiscal year Apr 1 to Mar 31
        self.settings.billing_cutoff_frequency = "Yearly"
        self.settings.book_year_start_month = 4  # April
        self.settings.book_year_start_day = 1
        self.settings.book_year_end_month = 3  # March
        self.settings.book_year_end_day = 31
        self.settings.save()
        frappe.db.commit()

        # Mock today as May (in current fiscal year)
        with patch("verenigingen.services.billing.bulk_invoice_generation_service.today") as mock_today:
            mock_today.return_value = "2025-05-15"

            # Act
            cutoff = calculate_cutoff_date_for_period()

            # Assert - fiscal year ends Mar 31, 2026
            self.assertEqual(cutoff, date(2026, 3, 31))


class TestCoverageBasedEligibility(EnhancedTestCase):
    """Test coverage-based eligibility logic (stale next_invoice_date bug fixes)"""

    def setUp(self):
        """Set up test fixtures with real member and schedule"""
        super().setUp()

        # Create test member with customer
        self.member = self.create_test_member(
            first_name="Eligibility", last_name="Test", birth_date="1985-05-15"
        )

        # Reuse the Customer auto-created by create_test_member. Creating a second
        # Customer with the same name collides on the Customer PRIMARY key
        # (DuplicateEntryError). link_member_to_customer is idempotent.
        self.customer_doc = self.link_member_to_customer(self.member)

        # Create membership and schedule (use Monthly Membership which exists)
        self.membership = self.create_test_membership(
            member_name=self.member.name, membership_type_name="Monthly Membership"
        )

        schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": self.member.name, "status": "Active"},
            limit=1,
        )
        if schedules:
            self.schedule = frappe.get_doc("Membership Dues Schedule", schedules[0].name)
        else:
            frappe.throw("No schedule was created with membership")

    # ========== Stale next_invoice_date Bug Tests ==========

    def test_should_generate_with_coverage_gap_ignores_future_next_invoice_date(self):
        """
        BUG FIX TEST: Coverage gap should trigger generation even if next_invoice_date is in future.

        Previous bug: If latest_coverage_end < cutoff BUT next_invoice_date was in the future,
        the OR condition would return True but then get blocked by timing checks.

        Fix: Prioritize actual coverage data over stale next_invoice_date field.
        """
        # Arrange - create invoice covering through Sept 30
        from verenigingen.services.billing.invoice_generator import InvoiceGenerator

        generator = InvoiceGenerator(self.schedule)
        result = generator.generate_invoice(
            coverage_start=date(2025, 7, 1),
            coverage_end=date(2025, 9, 30),
            member_doc=self.member
        )
        self.assertTrue(result.success)
        frappe.db.commit()

        # Set next_invoice_date to future (stale from cancelled invoice)
        self.schedule.next_invoice_date = date(2026, 1, 31)
        self.schedule.save()
        frappe.db.commit()

        # Act - check if should generate for end of year
        calculator = CoverageCalculator(self.schedule)
        cutoff = date(2025, 12, 31)

        should_generate = calculator.should_generate_invoice_for_cutoff(cutoff)

        # Assert - should generate because coverage gap exists (Sept 30 < Dec 31)
        # even though next_invoice_date is in future (Jan 31, 2026)
        self.assertTrue(should_generate,
                       "Should generate when coverage gap exists, ignoring future next_invoice_date")

    def test_should_not_generate_when_coverage_extends_past_cutoff(self):
        """Test that generation is blocked when coverage already extends past cutoff"""
        # Arrange - create invoice covering through end of year
        from verenigingen.services.billing.invoice_generator import InvoiceGenerator

        generator = InvoiceGenerator(self.schedule)
        result = generator.generate_invoice(
            coverage_start=date(2025, 10, 1),
            coverage_end=date(2025, 12, 31),
            member_doc=self.member
        )
        self.assertTrue(result.success)
        frappe.db.commit()

        # Set next_invoice_date to past (to test prioritization)
        self.schedule.next_invoice_date = date(2025, 11, 1)
        self.schedule.save()
        frappe.db.commit()

        # Act
        calculator = CoverageCalculator(self.schedule)
        cutoff = date(2025, 12, 31)

        should_generate = calculator.should_generate_invoice_for_cutoff(cutoff)

        # Assert - should NOT generate because coverage extends through cutoff
        self.assertFalse(should_generate,
                        "Should not generate when coverage extends through cutoff, even if next_invoice_date is past")

    def test_first_invoice_generation_with_no_coverage_and_no_next_date(self):
        """Test that first invoice generation works when no coverage and no next_invoice_date"""
        # Arrange - no invoices created yet, clear next_invoice_date
        self.schedule.next_invoice_date = None
        self.schedule.save()
        frappe.db.commit()

        calculator = CoverageCalculator(self.schedule)
        cutoff = date(2025, 12, 31)

        # Act
        should_generate = calculator.should_generate_invoice_for_cutoff(cutoff)

        # Assert - should generate for first invoice when no next_invoice_date set
        self.assertTrue(should_generate,
                       "Should generate first invoice when no coverage and no next_invoice_date")

    def test_first_invoice_with_overdue_next_date(self):
        """Test that first invoice generates when next_invoice_date is overdue"""
        # Arrange - set next_invoice_date to past
        self.schedule.next_invoice_date = date(2025, 1, 1)
        self.schedule.save()
        frappe.db.commit()

        calculator = CoverageCalculator(self.schedule)
        cutoff = date(2025, 12, 31)

        # Act - mock today as after next_invoice_date
        with patch("verenigingen.services.billing.coverage_calculator.today") as mock_today:
            mock_today.return_value = "2025-11-15"

            should_generate = calculator.should_generate_invoice_for_cutoff(cutoff)

        # Assert - should generate because next_invoice_date is overdue
        self.assertTrue(should_generate,
                       "Should generate first invoice when next_invoice_date is overdue")


class TestTimingCheckWithCoverageGaps(EnhancedTestCase):
    """Test timing check logic with coverage gaps"""

    def setUp(self):
        """Set up test fixtures"""
        super().setUp()

        # Create test member with customer
        self.member = self.create_test_member(
            first_name="Timing", last_name="Test", birth_date="1985-05-15"
        )

        # Reuse the Customer auto-created by create_test_member. Creating a second
        # Customer with the same name collides on the Customer PRIMARY key
        # (DuplicateEntryError). link_member_to_customer is idempotent.
        self.customer_doc = self.link_member_to_customer(self.member)

        # Create membership and schedule (use Monthly Membership which exists)
        self.membership = self.create_test_membership(
            member_name=self.member.name, membership_type_name="Monthly Membership"
        )

        schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": self.member.name, "status": "Active"},
            limit=1,
        )
        if schedules:
            self.schedule = frappe.get_doc("Membership Dues Schedule", schedules[0].name)
        else:
            frappe.throw("No schedule was created with membership")

    # ========== Timing Check Bug Tests ==========

    def test_timing_check_allows_generation_with_coverage_gap(self):
        """
        BUG FIX TEST: Timing check should allow generation when coverage gap exists.

        Previous bug: check_schedule_timing() would block generation if next_invoice_date
        was in the future, even when latest_coverage_end was in the past (gap).

        Fix: If coverage ended in the past, generate immediately regardless of next_invoice_date.
        """
        # Arrange - create invoice with coverage ending in past
        from verenigingen.services.billing.invoice_generator import InvoiceGenerator

        generator = InvoiceGenerator(self.schedule)
        result = generator.generate_invoice(
            coverage_start=date(2025, 7, 1),
            coverage_end=date(2025, 9, 30),
            member_doc=self.member
        )
        self.assertTrue(result.success)
        frappe.db.commit()

        # Set next_invoice_date to future and invoice_days_before to 30
        self.schedule.next_invoice_date = date(2026, 1, 31)
        self.schedule.invoice_days_before = 30
        self.schedule.save()
        frappe.db.commit()

        # Mock today as November (after coverage gap)
        with patch("verenigingen.services.billing.eligibility_checker.today") as mock_today:
            mock_today.return_value = "2025-11-15"

            # Act
            checker = EligibilityChecker(self.schedule)
            timing_result = checker.check_schedule_timing()

            # Assert - should allow generation because coverage gap exists
            self.assertTrue(timing_result.can_generate,
                          f"Should allow generation with coverage gap, but got: {timing_result.reason}")
            self.assertIn("gap", timing_result.reason.lower(),
                         "Reason should mention coverage gap")

    def test_timing_check_blocks_early_generation_without_gap(self):
        """Test that timing check blocks generation when it's too early and no gap exists"""
        # Arrange - create invoice with coverage extending into future
        from verenigingen.services.billing.invoice_generator import InvoiceGenerator

        generator = InvoiceGenerator(self.schedule)
        result = generator.generate_invoice(
            coverage_start=date(2025, 10, 1),
            coverage_end=date(2025, 12, 31),
            member_doc=self.member
        )
        self.assertTrue(result.success)
        frappe.db.commit()

        # Set next_invoice_date to future and invoice_days_before to 30
        self.schedule.next_invoice_date = date(2026, 1, 31)
        self.schedule.invoice_days_before = 30
        self.schedule.save()
        frappe.db.commit()

        # Mock today as November (before 30-day window)
        with patch("verenigingen.services.billing.eligibility_checker.today") as mock_today:
            mock_today.return_value = "2025-11-15"

            # Act
            checker = EligibilityChecker(self.schedule)
            timing_result = checker.check_schedule_timing()

            # Assert - should block because it's too early and no gap exists
            self.assertFalse(timing_result.can_generate,
                           "Should block early generation when coverage extends into future")
            self.assertIn("too early", timing_result.reason.lower(),
                         "Reason should mention timing")

    def test_timing_check_allows_generation_within_window(self):
        """Test that timing check allows generation within invoice_days_before window"""
        # Arrange - create invoice with coverage extending into future
        from verenigingen.services.billing.invoice_generator import InvoiceGenerator

        generator = InvoiceGenerator(self.schedule)
        result = generator.generate_invoice(
            coverage_start=date(2025, 10, 1),
            coverage_end=date(2025, 12, 31),
            member_doc=self.member
        )
        self.assertTrue(result.success)
        frappe.db.commit()

        # Set next_invoice_date and invoice_days_before
        self.schedule.next_invoice_date = date(2026, 1, 31)
        self.schedule.invoice_days_before = 30
        self.schedule.save()
        frappe.db.commit()

        # Mock today as within 30-day window (Jan 1, 2026 = 30 days before Jan 31)
        with patch("verenigingen.services.billing.eligibility_checker.today") as mock_today:
            mock_today.return_value = "2026-01-02"

            # Act
            checker = EligibilityChecker(self.schedule)
            timing_result = checker.check_schedule_timing()

            # Assert - should allow generation within window
            self.assertTrue(timing_result.can_generate,
                          f"Should allow generation within invoice_days_before window, but got: {timing_result.reason}")
