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

        # Create membership type first
        self.membership_type = self.create_test_membership_type(
            membership_type_name="Coverage Test Type"
        )

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
        # Use a start date that results in a future renewal date so status = Active
        # (Membership with past renewal_date would be "Expired" and skip schedule creation)
        self.membership = self.create_test_membership(
            member_name=self.member.name,
            membership_type_name=self.membership_type.name,
            start_date="2025-01-01"  # Renewal = 2026-01-01, status = Active
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
        """Test that force_date is used as reference for period calculation"""
        # Arrange - change to Monthly billing to test force_date more precisely
        original_frequency = self.schedule.billing_frequency
        self.schedule.billing_frequency = "Monthly"
        self.schedule.save()
        frappe.db.commit()

        try:
            calculator = CoverageCalculator(self.schedule)
            force_date = date(2025, 6, 15)

            # Act
            result = calculator.calculate_next_coverage_period(self.member, force_date=force_date)

            # Assert
            self.assertTrue(result.is_valid())
            # For Monthly billing, force_date determines the period (June 1-30),
            # but coverage starts from period_start, not the exact force_date
            # (unless membership_start is later, in which case it uses that)
            self.assertEqual(result.start_date, date(2025, 6, 1))  # Period start
            self.assertEqual(result.end_date, date(2025, 6, 30))  # Period end
            self.assertEqual(result.metadata["force_date"], force_date)
            self.assertEqual(result.metadata["reference_date"], force_date)
        finally:
            # Restore original frequency
            self.schedule.billing_frequency = original_frequency
            self.schedule.save()
            frappe.db.commit()

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

        # Create membership type first
        self.membership_type = self.create_test_membership_type(
            membership_type_name="Cutoff Test Type"
        )

        # Create real test member
        self.member = self.create_test_member(
            first_name="Cutoff", last_name="TestMember", birth_date="1990-01-01"
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
        # Use a start date that results in a future renewal date so status = Active
        # (Membership with past renewal_date would be "Expired" and skip schedule creation)
        self.membership = self.create_test_membership(
            member_name=self.member.name,
            membership_type_name=self.membership_type.name,
            start_date="2025-01-01"  # Renewal = 2026-01-01, status = Active
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

        self.member.reload()

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
    """

    def setUp(self):
        """Set up test fixtures"""
        super().setUp()

        # Create membership type first
        self.membership_type = self.create_test_membership_type(
            membership_type_name="Eligibility Test Type"
        )

        # Create multiple test members to simulate real scenario
        self.members = []
        self.schedules = []

        for i in range(3):
            member = self.create_test_member(
                first_name=f"Eligibility{i}", last_name="TestMember", birth_date="1990-01-01"
            )

            customer = frappe.new_doc("Customer")
            customer.customer_name = f"{member.first_name} {member.last_name}"
            customer.customer_type = "Individual"
            customer.insert()

            member.customer = customer.name
            member.save()

            # Use a start date that results in a future renewal date so status = Active
            # (Membership with past renewal_date would be "Expired" and skip schedule creation)
            membership = self.create_test_membership(
                member_name=member.name,
                membership_type_name=self.membership_type.name,
                start_date="2025-01-01"  # Renewal = 2026-01-01, status = Active
            )

            schedules = frappe.get_all(
                "Membership Dues Schedule",
                filters={"member": member.name, "status": "Active"},
                limit=1,
            )
            if schedules:
                schedule = frappe.get_doc("Membership Dues Schedule", schedules[0].name)
                self.schedules.append(schedule)

            self.members.append(member)

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
