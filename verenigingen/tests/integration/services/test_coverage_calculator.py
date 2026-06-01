# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Integration tests for CoverageCalculator service.

Tests the coverage period calculation logic extracted from MembershipDuesSchedule.
Uses Enhanced Test Factory for real database operations - no mocks.

Key test scenarios:
- First invoice coverage calculation with varied membership start dates
- Mid-period membership starts (member joins Nov 15 during Q4)
- Sequential coverage building on previous invoices
- Various billing frequencies (Daily, Monthly, Quarterly, Annual)
"""

import unittest
from datetime import date

import frappe

from verenigingen.services.billing.coverage_calculator import CoverageCalculator, CoveragePeriod
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


# =============================================================================
# Test Date Constants
# =============================================================================
# These dates are chosen to test specific edge cases in coverage calculation.
# Using constants makes the test intent explicit and reduces magic strings.

# Period start dates (for testing full period coverage)
TEST_DATE_YEAR_START = "2025-01-01"      # Start of year for Annual billing tests
TEST_DATE_Q1_START = "2025-01-01"        # Q1 start for Quarterly billing tests

# Mid-period dates (for testing partial period coverage)
TEST_DATE_MID_Q1 = "2025-02-15"          # Mid-Q1 to test partial quarter coverage
TEST_DATE_MID_Q4 = "2025-11-15"          # Mid-Q4, late in year for year-end logic
TEST_DATE_MID_YEAR = "2025-06-15"        # Mid-year for Semi-Annual testing

# Late in year dates
TEST_DATE_Q4_START = "2025-10-01"        # Q4 start for late-year join tests

# Force dates for billing period tests (must be after membership start)
TEST_FORCE_DATE_DEC = date(2025, 12, 1)  # December for mid-Q4 member tests
TEST_FORCE_DATE_DEC_MID = date(2025, 12, 15)  # Mid-December


class TestCoverageCalculator(EnhancedTestCase):
    """Test the CoverageCalculator service with real database operations"""

    def setUp(self):
        """Set up test fixtures with real data"""
        super().setUp()

        # Create membership type
        self.membership_type = self.create_test_membership_type(
            membership_type_name="Coverage Test Type"
        )

        # Create member with mid-Q4 start date to test mid-period coverage
        self.member, self.schedule = self.create_test_member_with_schedule(
            first_name="Coverage",
            last_name="Test",
            membership_type_name=self.membership_type.name,
            start_date=TEST_DATE_MID_Q4,  # Nov 15 - tests mid-period join
            birth_date="1985-05-15"
        )

    # ========== Happy Path Tests ==========

    def test_first_invoice_coverage_calculation(self):
        """Test coverage calculation for first invoice (no previous coverage)"""
        # Arrange
        calculator = CoverageCalculator(self.schedule)

        # Act
        result = calculator.calculate_next_coverage_period(self.member)

        # Assert (uses OperationResult pattern)
        self.assertTrue(result.success)
        self.assertIsNotNone(result.data.start_date)
        self.assertIsNotNone(result.data.end_date)
        self.assertEqual(result.data.calculation_method, "first_invoice")
        self.assertIn("previous_coverage_end", result.data.metadata)
        self.assertIsNone(result.data.metadata["previous_coverage_end"])

    def test_mid_period_membership_start_uses_membership_date(self):
        """
        Test that members who join mid-period have coverage starting from
        their membership start date, not the billing period start.

        Scenario: Member joins Nov 15 (mid-Q4). With Annual billing,
        the billing period would be Jan 1 - Dec 31, but coverage should
        start from Nov 15 (not Jan 1) since the member wasn't a member before.
        """
        # Arrange - ensure we're using the mid-period membership (Nov 15)
        # The default setUp already creates this with start_date=TEST_DATE_MID_Q4
        calculator = CoverageCalculator(self.schedule)

        # Verify member_since was set by the factory
        expected_start = date(2025, 11, 15)  # TEST_DATE_MID_Q4 as date
        self.assertEqual(self.member.member_since, expected_start)

        # Act - calculate first invoice coverage. Pin the reference date with
        # force_date so the test is deterministic regardless of the real calendar:
        # without it the "current billing period" is derived from today(), so the
        # 2025 assertions below only hold while today() is in 2025. Dec 1, 2025 is
        # within the Annual period and after the Nov 15 join (mirrors the
        # force_date pattern used by test_force_date_override).
        result = calculator.calculate_next_coverage_period(self.member, force_date=TEST_FORCE_DATE_DEC)

        # Assert - coverage should start from membership start, not period start
        self.assertTrue(result.success)
        self.assertEqual(result.data.calculation_method, "first_invoice")

        # For Annual billing: period would be Jan 1 - Dec 31
        # But coverage should start from Nov 15 (membership start)
        self.assertEqual(result.data.start_date, expected_start)
        self.assertEqual(result.data.end_date, date(2025, 12, 31))

        # Verify metadata shows membership_start was used
        self.assertTrue(result.data.metadata.get("membership_start_used"))
        self.assertEqual(result.data.metadata.get("membership_start"), expected_start)
        self.assertEqual(result.data.metadata.get("period_start"), date(2025, 1, 1))

    def test_period_start_membership_uses_period_start(self):
        """
        Test that members who join at period start have coverage starting
        from the period start (same as their membership start).

        Scenario: Member joins Jan 1 (start of year). With Annual billing,
        coverage should start from Jan 1.
        """
        # Arrange - create a new member who joined at period start
        member_jan, schedule_jan = self.create_test_member_with_schedule(
            first_name="JanStart",
            last_name="Test",
            membership_type_name=self.membership_type.name,
            start_date=TEST_DATE_YEAR_START  # Jan 1 - period start for Annual
        )

        calculator = CoverageCalculator(schedule_jan)

        # Act - pin the reference date (see test_mid_period... for the rationale);
        # Dec 1, 2025 keeps the billing period in 2025 so the assertions are stable.
        result = calculator.calculate_next_coverage_period(member_jan, force_date=TEST_FORCE_DATE_DEC)

        # Assert - coverage starts from period start (which equals membership start)
        self.assertTrue(result.success)
        self.assertEqual(result.data.start_date, date(2025, 1, 1))
        self.assertEqual(result.data.end_date, date(2025, 12, 31))

        # Verify metadata shows membership_start was NOT used (period_start was)
        self.assertFalse(result.data.metadata.get("membership_start_used"))

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
        self.assertTrue(result.success)
        self.assertEqual(result.data.start_date, date(2025, 2, 1))  # Day after previous end
        self.assertEqual(result.data.calculation_method, "sequential")
        self.assertEqual(result.data.metadata["previous_coverage_end"], date(2025, 1, 31))

    # ========== Billing Frequency Tests ==========

    def test_daily_billing_same_start_end(self):
        """Test that daily billing allows start==end"""
        # Arrange - change schedule to daily billing
        # Use force_date AFTER membership start (Nov 15) to test valid scenario
        original_frequency = self.schedule.billing_frequency
        self.schedule.billing_frequency = "Daily"
        self.schedule.save()
        frappe.db.commit()

        try:
            calculator = CoverageCalculator(self.schedule)

            # Act - use date after membership start (TEST_DATE_MID_Q4)
            result = calculator.calculate_next_coverage_period(
                self.member, force_date=TEST_FORCE_DATE_DEC
            )

            # Assert
            self.assertTrue(result.success)
            self.assertEqual(result.data.start_date, result.data.end_date)  # Same day for daily billing
            self.assertEqual(result.data.start_date, TEST_FORCE_DATE_DEC)

        finally:
            # Restore original frequency
            self.schedule.billing_frequency = original_frequency
            self.schedule.save()
            frappe.db.commit()

    def test_quarterly_billing_coverage_span(self):
        """Test quarterly billing creates 3-month coverage from period start"""
        # Create member who started at period start (Jan 1) for full quarterly coverage
        member_q1, schedule_q1 = self.create_test_member_with_schedule(
            first_name="Quarterly",
            last_name="Test",
            membership_type_name=self.membership_type.name,
            start_date=TEST_DATE_Q1_START
        )

        # Change to Quarterly billing
        schedule_q1.billing_frequency = "Quarterly"
        schedule_q1.save()
        frappe.db.commit()

        try:
            calculator = CoverageCalculator(schedule_q1)

            # Act
            result = calculator.calculate_next_coverage_period(
                member_q1, force_date=date(2025, 1, 1)
            )

            # Assert
            self.assertTrue(result.success)
            self.assertEqual(result.data.start_date, date(2025, 1, 1))
            self.assertEqual(result.data.end_date, date(2025, 3, 31))  # 3 months (Q1)

        finally:
            # Cleanup handled by test framework
            pass

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
        self.assertTrue(result.success)
        self.assertEqual(result.data.calculation_method, "date_based")
        # Date-based calculation uses billing_period_calculator logic
        # Result should be a valid period (start before end)
        self.assertLess(result.data.start_date, result.data.end_date or result.data.start_date)

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
        """Test that force_date is used as reference for period calculation"""
        # Arrange - change to Monthly billing to test force_date more precisely
        # Use force_date AFTER membership start (Nov 15) to test valid scenario
        original_frequency = self.schedule.billing_frequency
        self.schedule.billing_frequency = "Monthly"
        self.schedule.save()
        frappe.db.commit()

        try:
            calculator = CoverageCalculator(self.schedule)

            # Act - use TEST_FORCE_DATE_DEC_MID (after membership start)
            result = calculator.calculate_next_coverage_period(
                self.member, force_date=TEST_FORCE_DATE_DEC_MID
            )

            # Assert
            self.assertTrue(result.success)
            # For Monthly billing, force_date determines the period (Dec 1-31),
            # Since membership_start (Nov 15) < period_start (Dec 1), coverage uses period_start
            self.assertEqual(result.data.start_date, date(2025, 12, 1))  # Period start
            self.assertEqual(result.data.end_date, date(2025, 12, 31))  # Period end
            self.assertEqual(result.data.metadata["force_date"], TEST_FORCE_DATE_DEC_MID)
            self.assertEqual(result.data.metadata["reference_date"], TEST_FORCE_DATE_DEC_MID)
        finally:
            # Restore original frequency
            self.schedule.billing_frequency = original_frequency
            self.schedule.save()
            frappe.db.commit()

    def test_custom_frequency_calculation(self):
        """Test coverage calculation with custom frequency from period start"""
        # Create member who started at period start (Jan 1) for full custom coverage
        member_custom, schedule_custom = self.create_test_member_with_schedule(
            first_name="CustomFreq",
            last_name="Test",
            membership_type_name=self.membership_type.name,
            start_date=TEST_DATE_YEAR_START
        )

        # Configure custom frequency (every 3 months)
        schedule_custom.billing_frequency = "Custom"
        schedule_custom.custom_frequency_number = 3
        schedule_custom.custom_frequency_unit = "Months"
        schedule_custom.save()
        frappe.db.commit()

        calculator = CoverageCalculator(schedule_custom)

        # Act
        result = calculator.calculate_next_coverage_period(
            member_custom, force_date=date(2025, 1, 1)
        )

        # Assert
        self.assertTrue(result.success)
        self.assertEqual(result.data.start_date, date(2025, 1, 1))
        self.assertEqual(result.data.end_date, date(2025, 3, 31))  # 3 months coverage


class TestShouldGenerateForCutoff(EnhancedTestCase):
    """
    Integration tests for should_generate_invoice_for_cutoff logic.

    These tests verify the critical bug fix: the method should ONLY use actual
    invoice coverage dates, NOT the next_invoice_date field.

    Key scenarios tested:
    - 0 invoices should always trigger generation (regardless of next_invoice_date)
    - Coverage dates are the sole source of truth
    - Full eligibility flow integration
    """

    def setUp(self):
        """Set up test fixtures with real data"""
        super().setUp()

        # Create membership type
        self.membership_type = self.create_test_membership_type(
            membership_type_name="Cutoff Test Type"
        )

        # Create member with mid-Q1 start to test varied coverage scenarios
        self.member, self.schedule = self.create_test_member_with_schedule(
            first_name="Cutoff",
            last_name="TestMember",
            membership_type_name=self.membership_type.name,
            start_date=TEST_DATE_MID_Q1  # Feb 15 - mid-quarter join
        )

    # ========== Core Bug Fix Tests ==========

    def test_zero_invoices_always_needs_generation(self):
        """
        CRITICAL: With 0 invoices, should_generate_invoice_for_cutoff must return True.

        This is the core bug fix - the method should not check next_invoice_date
        when there are no invoices. 0% of the period is covered.
        """
        # Arrange
        calculator = CoverageCalculator(self.schedule)

        # Verify no invoices exist
        invoice_count = frappe.db.count(
            "Sales Invoice",
            {"customer": self.member.customer, "docstatus": 1}
        )
        self.assertEqual(invoice_count, 0, "Test precondition: should have 0 invoices")

        # Act - test with various cutoff dates
        should_gen_dec = calculator.should_generate_invoice_for_cutoff(date(2025, 12, 31))
        should_gen_jan = calculator.should_generate_invoice_for_cutoff(date(2025, 1, 31))
        should_gen_future = calculator.should_generate_invoice_for_cutoff(date(2026, 6, 30))

        # Assert - all should be True since there's no coverage
        self.assertTrue(should_gen_dec, "Should generate for Dec cutoff with 0 invoices")
        self.assertTrue(should_gen_jan, "Should generate for Jan cutoff with 0 invoices")
        self.assertTrue(should_gen_future, "Should generate for future cutoff with 0 invoices")

    def test_zero_invoices_ignores_next_invoice_date(self):
        """
        CRITICAL: next_invoice_date should NOT affect decision when there are 0 invoices.

        Even if next_invoice_date is far in the future, the method should return True
        because there's no actual coverage.
        """
        # Arrange - set next_invoice_date to far future
        self.schedule.next_invoice_date = date(2026, 12, 31)
        self.schedule.save()
        frappe.db.commit()

        calculator = CoverageCalculator(self.schedule)
        cutoff_date = date(2025, 12, 31)  # Before next_invoice_date

        # Verify setup
        self.assertIsNotNone(self.schedule.next_invoice_date)
        self.assertGreater(self.schedule.next_invoice_date, cutoff_date)

        # Act
        should_generate = calculator.should_generate_invoice_for_cutoff(cutoff_date)

        # Assert - must be True despite next_invoice_date being after cutoff
        self.assertTrue(
            should_generate,
            "Should generate invoice even when next_invoice_date is after cutoff, "
            "because there are 0 invoices (no coverage)"
        )

    def test_coverage_is_sole_source_of_truth(self):
        """
        Test that actual invoice coverage dates are the only factor in the decision.

        next_invoice_date is a scheduling hint that can become stale - it should
        not be used to determine if coverage exists.
        """
        # Arrange - create invoice with specific coverage
        from verenigingen.services.billing.invoice_generator import InvoiceGenerator

        generator = InvoiceGenerator(self.schedule)
        result = generator.generate_invoice(
            coverage_start=date(2025, 1, 1),
            coverage_end=date(2025, 3, 31),  # Covers Q1
            member_doc=self.member
        )
        self.assertTrue(result.success)
        frappe.db.commit()

        # Set next_invoice_date to something completely different (stale data)
        self.schedule.next_invoice_date = date(2024, 1, 1)  # In the past
        self.schedule.save()
        frappe.db.commit()

        calculator = CoverageCalculator(self.schedule)

        # Act & Assert - decisions should be based on coverage, not next_invoice_date
        # Cutoff in Q1 - covered
        self.assertFalse(
            calculator.should_generate_invoice_for_cutoff(date(2025, 2, 28)),
            "Should NOT generate - coverage extends past Feb cutoff"
        )
        # Cutoff at end of Q1 - covered
        self.assertFalse(
            calculator.should_generate_invoice_for_cutoff(date(2025, 3, 31)),
            "Should NOT generate - coverage extends to Mar 31"
        )
        # Cutoff in Q2 - NOT covered
        self.assertTrue(
            calculator.should_generate_invoice_for_cutoff(date(2025, 4, 30)),
            "Should generate - coverage ends before Apr cutoff"
        )

    # ========== Boundary Tests ==========

    def test_coverage_exactly_at_cutoff(self):
        """Test when coverage end date equals cutoff date exactly"""
        # Arrange
        from verenigingen.services.billing.invoice_generator import InvoiceGenerator

        generator = InvoiceGenerator(self.schedule)
        result = generator.generate_invoice(
            coverage_start=date(2025, 1, 1),
            coverage_end=date(2025, 6, 30),
            member_doc=self.member
        )
        self.assertTrue(result.success)
        frappe.db.commit()

        calculator = CoverageCalculator(self.schedule)

        # Act - cutoff exactly at coverage end
        should_generate = calculator.should_generate_invoice_for_cutoff(date(2025, 6, 30))

        # Assert - coverage_end >= cutoff means no generation needed
        # (coverage_end < cutoff triggers generation)
        self.assertFalse(should_generate, "Should NOT generate when coverage reaches cutoff exactly")

    def test_coverage_one_day_before_cutoff(self):
        """Test when coverage ends one day before cutoff"""
        # Arrange
        from verenigingen.services.billing.invoice_generator import InvoiceGenerator

        generator = InvoiceGenerator(self.schedule)
        result = generator.generate_invoice(
            coverage_start=date(2025, 1, 1),
            coverage_end=date(2025, 6, 29),  # One day before cutoff
            member_doc=self.member
        )
        self.assertTrue(result.success)
        frappe.db.commit()

        calculator = CoverageCalculator(self.schedule)

        # Act
        should_generate = calculator.should_generate_invoice_for_cutoff(date(2025, 6, 30))

        # Assert - coverage ends before cutoff, needs generation
        self.assertTrue(should_generate, "Should generate when coverage ends before cutoff")


class TestEligibilityFlowIntegration(EnhancedTestCase):
    """
    Integration tests for the full eligibility flow from API to coverage check.

    Tests the complete path: check_member_dues_status -> get_eligible_schedules_for_period
    -> should_generate_for_cutoff_period -> should_generate_invoice_for_cutoff

    Uses varied membership start dates to test realistic scenarios.
    """

    def setUp(self):
        """Set up test fixtures"""
        super().setUp()

        # Create membership type
        self.membership_type = self.create_test_membership_type(
            membership_type_name="Eligibility Test Type"
        )

        # Create multiple test members with varied start dates to simulate real scenarios
        # - Member 0: Period start (Jan 1)
        # - Member 1: Mid-quarter (Feb 15)
        # - Member 2: Late in year (Oct 1)
        self.members = []
        self.schedules = []
        start_dates = [TEST_DATE_YEAR_START, TEST_DATE_MID_Q1, TEST_DATE_Q4_START]

        for i, start_date in enumerate(start_dates):
            member, schedule = self.create_test_member_with_schedule(
                first_name=f"Eligibility{i}",
                last_name="TestMember",
                membership_type_name=self.membership_type.name,
                start_date=start_date
            )

            self.members.append(member)
            self.schedules.append(schedule)

        frappe.db.commit()

    def test_members_with_zero_invoices_are_eligible(self):
        """
        Test that members with 0 invoices appear in eligible_schedules list.

        This verifies the full flow from get_eligible_schedules_for_period.
        """
        from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import (
            get_eligible_schedules_for_period,
        )

        # Arrange - verify all members have 0 invoices
        for member in self.members:
            invoice_count = frappe.db.count(
                "Sales Invoice",
                {"customer": member.customer, "docstatus": 1}
            )
            self.assertEqual(invoice_count, 0)

        # Act
        result = get_eligible_schedules_for_period(
            cutoff_date=date(2025, 12, 31),
            test_mode=False,
            include_details=True
        )

        # Assert - all our test schedules should be eligible
        eligible_schedule_names = result["eligible_schedules"]
        for schedule in self.schedules:
            self.assertIn(
                schedule.name,
                eligible_schedule_names,
                f"Schedule {schedule.name} should be eligible (member has 0 invoices)"
            )

        # Verify they're not incorrectly filtered
        already_covered = result["filtered_members"].get("already_covered", [])
        for schedule in self.schedules:
            schedule_names_in_covered = [m["schedule"] for m in already_covered]
            self.assertNotIn(
                schedule.name,
                schedule_names_in_covered,
                f"Schedule {schedule.name} should NOT be in already_covered"
            )

    def test_members_with_sufficient_coverage_are_filtered(self):
        """
        Test that members with coverage through cutoff are correctly filtered.
        """
        from verenigingen.services.billing.invoice_generator import InvoiceGenerator
        from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import (
            get_eligible_schedules_for_period,
        )

        # Arrange - give first member coverage through cutoff
        cutoff = date(2025, 12, 31)
        covered_schedule = self.schedules[0]
        covered_member = self.members[0]

        generator = InvoiceGenerator(covered_schedule)
        result = generator.generate_invoice(
            coverage_start=date(2025, 1, 1),
            coverage_end=cutoff,
            member_doc=covered_member
        )
        self.assertTrue(result.success)
        frappe.db.commit()

        # Act
        eligibility_result = get_eligible_schedules_for_period(
            cutoff_date=cutoff,
            test_mode=False,
            include_details=True
        )

        # Assert - covered member should be filtered, others should be eligible
        self.assertNotIn(
            covered_schedule.name,
            eligibility_result["eligible_schedules"],
            "Member with sufficient coverage should NOT be eligible"
        )

        # Other schedules (with 0 invoices) should still be eligible
        for schedule in self.schedules[1:]:
            self.assertIn(
                schedule.name,
                eligibility_result["eligible_schedules"],
                f"Schedule {schedule.name} with 0 invoices should be eligible"
            )

    def test_partial_coverage_triggers_eligibility(self):
        """
        Test that members with partial coverage (doesn't reach cutoff) are eligible.
        """
        from verenigingen.services.billing.invoice_generator import InvoiceGenerator
        from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import (
            get_eligible_schedules_for_period,
        )

        # Arrange - give first member partial coverage
        partial_schedule = self.schedules[0]
        partial_member = self.members[0]

        generator = InvoiceGenerator(partial_schedule)
        result = generator.generate_invoice(
            coverage_start=date(2025, 1, 1),
            coverage_end=date(2025, 6, 30),  # Only covers first half of year
            member_doc=partial_member
        )
        self.assertTrue(result.success)
        frappe.db.commit()

        # Act - check with cutoff at end of year
        eligibility_result = get_eligible_schedules_for_period(
            cutoff_date=date(2025, 12, 31),
            test_mode=False,
            include_details=True
        )

        # Assert - member with partial coverage should be eligible
        self.assertIn(
            partial_schedule.name,
            eligibility_result["eligible_schedules"],
            "Member with partial coverage should be eligible for additional invoices"
        )
