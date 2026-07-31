# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Integration tests for EligibilityChecker service.

Tests the eligibility determination logic extracted from MembershipDuesSchedule.
Uses Enhanced Test Factory for real database operations - no mocks.
"""

import unittest
from datetime import date

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.services.billing.coverage_calculator import CoverageCalculator
from verenigingen.services.billing.eligibility_checker import EligibilityChecker, EligibilityResult
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestCutoffIsCappedAtOnePeriodAhead(EnhancedTestCase):
    """
    The cutoff comparison is now the ONLY thing deciding when to generate, so it has to
    hold on its own when billing_cutoff_frequency is coarser than a member's billing
    frequency.

    billing_cutoff_frequency is a single global setting. Set to Quarterly, it asks for a
    Monthly member to be covered through quarter end - three periods - and because the
    bulk generator emits one invoice per schedule per run, that came out as one extra
    invoice per run rather than three at once. Capping the cutoff at one period ahead of
    today bounds it without changing anything when the cutoff is at or finer than the
    member's own frequency.

    cutoff_date is passed explicitly rather than read from settings, so these tests do
    not depend on today's position in the quarter.
    """

    def setUp(self):
        super().setUp()
        self.membership_type = self.create_test_membership_type(
            membership_type_name="Timing Anchor Type", amount=10.0, contribution_mode="Fixed Amount"
        )
        self.member, self.schedule = self.create_test_member_with_schedule(
            first_name="TimingAnchor",
            last_name="Member",
            membership_type_name=self.membership_type.name,
            start_date=today(),
        )
        self.schedule.billing_frequency = "Monthly"
        self.schedule.save()
        frappe.db.commit()
        self.member.reload()

    def _seed_coverage(self, coverage_start, coverage_end):
        from verenigingen.services.billing.invoice_generator import InvoiceGenerator

        result = InvoiceGenerator(self.schedule).generate_invoice(
            coverage_start=coverage_start, coverage_end=coverage_end, member_doc=self.member
        )
        self.assertTrue(result.success, getattr(result, "error_message", None))
        # get_latest_coverage_end_date only sees SUBMITTED invoices, so a draft would
        # make these tests vacuous in both directions.
        self.assertEqual(frappe.db.get_value("Sales Invoice", result.data.name, "docstatus"), 1)
        frappe.db.commit()

    def test_coarse_cutoff_does_not_bill_a_member_already_covered_a_period_ahead(self):
        """A Monthly member covered 45 days out must not be generated again."""
        self._seed_coverage(add_days(getdate(today()), -15), add_days(getdate(today()), 45))

        calculator = CoverageCalculator(self.schedule)

        self.assertFalse(
            calculator.should_generate_invoice_for_cutoff(add_days(getdate(today()), 120)),
            "a coarse cutoff billed a member whose coverage already runs a period ahead",
        )

    def test_coarse_cutoff_still_bills_a_member_whose_coverage_is_about_to_lapse(self):
        """The cap must not stop legitimate generation, or billing halts entirely."""
        self._seed_coverage(add_days(getdate(today()), -28), add_days(getdate(today()), 2))

        calculator = CoverageCalculator(self.schedule)

        self.assertTrue(
            calculator.should_generate_invoice_for_cutoff(add_days(getdate(today()), 120)),
            "member about to lapse was not billed",
        )

    def test_member_with_no_coverage_is_always_billed(self):
        """A member with no invoices needs one regardless of the cap."""
        calculator = CoverageCalculator(self.schedule)

        self.assertTrue(calculator.should_generate_invoice_for_cutoff(add_days(getdate(today()), 120)))

    def test_the_cap_scales_with_the_billing_frequency(self):
        """
        The cap must be one of the MEMBER'S periods, not a hardcoded month.

        Replacing _one_period_ahead_of_today() with add_days(today(), 30) leaves every
        other test in this class green, so without this case the docstring's central
        claim - that the cap uses the same period arithmetic as the sequence - is
        unpinned. A Quarterly member covered 60 days out is still inside one period and
        must remain billable.
        """
        self.schedule.billing_frequency = "Quarterly"
        self.schedule.save()
        frappe.db.commit()
        self._seed_coverage(add_days(getdate(today()), -30), add_days(getdate(today()), 60))

        calculator = CoverageCalculator(self.schedule)

        self.assertTrue(
            calculator.should_generate_invoice_for_cutoff(add_days(getdate(today()), 365)),
            "a 30-day cap was applied to a Quarterly member",
        )


class TestEligibilityIgnoresNextInvoiceDate(EnhancedTestCase):
    """
    Eligibility must not consider next_invoice_date. Nothing else pins this, and
    re-adding a timing gate is a two-line change that breaks no other test.

    The field is derived from the POSTING date, so it drifts out of step with coverage:
    on the live site 431 schedules carry a next_invoice_date 83 days LATER than their
    coverage actually lapsed. Under the old guard those members were billed only because
    a different branch short-circuited first.
    """

    def setUp(self):
        super().setUp()
        self.membership_type = self.create_test_membership_type(
            membership_type_name="Ignores NID Type", amount=10.0, contribution_mode="Fixed Amount"
        )
        self.member, self.schedule = self.create_test_member_with_schedule(
            first_name="IgnoresNID",
            last_name="Member",
            membership_type_name=self.membership_type.name,
            start_date=today(),
        )
        self.schedule.billing_frequency = "Monthly"
        self.schedule.save()
        frappe.db.commit()
        self.member.reload()

    def test_lapsed_coverage_is_billable_despite_a_far_future_next_invoice_date(self):
        """The veg11 shape: coverage lapsed 90 days ago, next_invoice_date 83 days out."""
        from verenigingen.services.billing.invoice_generator import InvoiceGenerator

        result = InvoiceGenerator(self.schedule).generate_invoice(
            coverage_start=add_days(getdate(today()), -120),
            coverage_end=add_days(getdate(today()), -90),
            member_doc=self.member,
        )
        self.assertTrue(result.success, getattr(result, "error_message", None))
        frappe.db.commit()

        self.schedule.next_invoice_date = add_days(getdate(today()), 83)
        self.schedule.invoice_days_before = 30
        self.schedule.save()
        frappe.db.commit()

        can_generate, reason = self.schedule.can_generate_invoice()

        self.assertTrue(can_generate, f"a lapsed member was blocked by next_invoice_date: {reason}")


class TestEligibilityChecker(EnhancedTestCase):
    """Test the EligibilityChecker service with real database operations"""

    def setUp(self):
        """Set up test fixtures with real data"""
        super().setUp()

        # Generate unique name per test run to avoid Customer duplicate key errors
        import time
        timestamp = str(int(time.time() * 1000))  # Millisecond precision

        # Create real test member with unique name
        self.member = self.create_test_member(
            first_name=f"Eligibility{timestamp}",
            last_name="Test",
            birth_date="1985-05-15"
        )

        # Reuse the Customer auto-created by create_test_member. Creating a second
        # Customer with the same customer_name collides on the Customer PRIMARY key
        # (DuplicateEntryError). link_member_to_customer is idempotent.
        self.customer_doc = self.link_member_to_customer(self.member)

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

    def test_fresh_schedule_eligible(self):
        """Test that a fresh schedule with no previous invoices is eligible"""
        # Arrange
        checker = EligibilityChecker(self.schedule)

        # Act
        result = checker.check_eligibility(self.member)

        # Assert
        self.assertTrue(result.can_generate)
        self.assertEqual(result.category, "valid")
        self.assertEqual(result.reason, "Can generate invoice")

    def test_result_object_to_dict(self):
        """Test that EligibilityResult converts to dict correctly"""
        # Arrange
        result = EligibilityResult(
            True,
            "Test reason",
            "valid",
            test_metadata="test_value"
        )

        # Act
        result_dict = result.to_dict()

        # Assert
        self.assertTrue(result_dict["can_generate"])
        self.assertEqual(result_dict["reason"], "Test reason")
        self.assertEqual(result_dict["category"], "valid")
        self.assertEqual(result_dict["test_metadata"], "test_value")

    # ========== System Checks Tests ==========

    def test_template_schedule_blocked(self):
        """Test that template schedules cannot generate invoices"""
        # Arrange - use db_set to bypass DocType validation that prevents changing is_template
        frappe.db.set_value("Membership Dues Schedule", self.schedule.name, "is_template", 1)
        frappe.db.commit()
        self.schedule.reload()

        checker = EligibilityChecker(self.schedule)

        # Act
        result = checker.check_eligibility(self.member)

        # Assert
        self.assertFalse(result.can_generate)
        self.assertEqual(result.category, "system")
        self.assertIn("template", result.reason.lower())

    def test_inactive_schedule_blocked(self):
        """Test that inactive schedules cannot generate invoices"""
        # Arrange
        self.schedule.status = "Paused"
        self.schedule.save()
        frappe.db.commit()

        checker = EligibilityChecker(self.schedule)

        # Act
        result = checker.check_eligibility(self.member)

        # Assert
        self.assertFalse(result.can_generate)
        self.assertEqual(result.category, "system")
        self.assertIn("not active", result.reason.lower())

    def test_auto_generate_disabled_blocked(self):
        """Test that schedules with auto_generate disabled cannot generate"""
        # Arrange
        self.schedule.auto_generate = 0
        self.schedule.save()
        frappe.db.commit()

        checker = EligibilityChecker(self.schedule)

        # Act
        result = checker.check_eligibility(self.member)

        # Assert
        self.assertFalse(result.can_generate)
        self.assertEqual(result.category, "system")
        self.assertIn("auto generation", result.reason.lower())

    def test_test_mode_bypasses_checks(self):
        """Test that test mode allows generation regardless of other issues"""
        # Arrange - set member to Terminated (normally blocks generation)
        self.member.status = "Quit"
        self.member.save()
        frappe.db.commit()

        # But enable test mode on schedule
        self.schedule.test_mode = 1
        self.schedule.save()
        frappe.db.commit()

        checker = EligibilityChecker(self.schedule)

        # Act
        result = checker.check_eligibility(self.member)

        # Assert - test mode bypasses the terminated status check
        self.assertTrue(result.can_generate)
        self.assertEqual(result.category, "valid")
        self.assertIn("test mode", result.reason.lower())

    # ========== Member Status Tests ==========

    def test_terminated_member_blocked(self):
        """Test that terminated members cannot be billed"""
        # Arrange
        self.member.status = "Quit"
        self.member.save()
        frappe.db.commit()

        checker = EligibilityChecker(self.schedule)

        # Act
        result = checker.check_eligibility(self.member)

        # Assert
        self.assertFalse(result.can_generate)
        self.assertEqual(result.category, "member_status")
        self.assertIn("Quit", result.reason)
        self.assertEqual(result.metadata.get("member_status"), "Quit")

    def test_banned_member_blocked(self):
        """Test that banned members cannot be billed"""
        # Arrange
        self.member.status = "Banned"
        self.member.save()
        frappe.db.commit()

        checker = EligibilityChecker(self.schedule)

        # Act
        result = checker.check_eligibility(self.member)

        # Assert
        self.assertFalse(result.can_generate)
        self.assertEqual(result.category, "member_status")
        self.assertIn("Banned", result.reason)

    def test_deceased_member_blocked(self):
        """Test that deceased members cannot be billed"""
        # Arrange
        self.member.status = "Deceased"
        self.member.save()
        frappe.db.commit()

        checker = EligibilityChecker(self.schedule)

        # Act
        result = checker.check_eligibility(self.member)

        # Assert
        self.assertFalse(result.can_generate)
        self.assertEqual(result.category, "member_status")
        self.assertIn("Deceased", result.reason)

    # REMOVED: test_rejected_member_blocked
    # Rejected members don't have dues schedules in production - they never get past
    # the application stage. This test scenario isn't realistic.

    def test_suspended_member_can_generate(self):
        """Test that suspended members CAN still be billed (they're still members)"""
        # Arrange
        self.member.status = "Suspended"
        self.member.save()
        frappe.db.commit()

        checker = EligibilityChecker(self.schedule)

        # Act
        result = checker.check_eligibility(self.member)

        # Assert - suspended members should pass member status check
        # (might fail on other checks, but not member status)
        if not result.can_generate:
            self.assertNotEqual(result.category, "member_status")

    # ========== Membership Validation Tests ==========

    def test_no_active_membership_blocked(self):
        """Test that members without active membership cannot be billed"""
        # Arrange - cancel the membership (use Cancelled status which is valid)
        self.membership.status = "Cancelled"
        self.membership.docstatus = 2  # Cancelled
        # Skip validation when cancelling
        self.membership.flags.ignore_validate = True
        self.membership.save()
        frappe.db.commit()

        checker = EligibilityChecker(self.schedule)

        # Act
        result = checker.check_eligibility(self.member)

        # Assert
        self.assertFalse(result.can_generate)
        self.assertEqual(result.category, "membership")
        self.assertIn("no active membership", result.reason.lower())

    def test_missing_customer_record_blocked(self):
        """Test that members without customer records cannot be billed"""
        # Arrange - remove customer link
        self.member.customer = None
        self.member.save()
        frappe.db.commit()
        self.member.reload()

        checker = EligibilityChecker(self.schedule)

        # Act
        result = checker.check_eligibility(self.member)

        # Assert
        self.assertFalse(result.can_generate)
        self.assertEqual(result.category, "system")
        self.assertIn("customer record", result.reason.lower())
        self.assertTrue(result.metadata.get("missing_customer"))

    def test_orphaned_schedule_blocked(self):
        """Test that schedule with non-existent member is blocked"""
        # Arrange - use db_set to bypass validation that prevents orphaned schedules
        frappe.db.set_value("Membership Dues Schedule", self.schedule.name, "member", "MEMBER-DOES-NOT-EXIST")
        frappe.db.commit()
        self.schedule.reload()

        checker = EligibilityChecker(self.schedule)

        # Act
        result = checker.check_eligibility()  # No member_doc provided

        # Assert
        self.assertFalse(result.can_generate)
        self.assertEqual(result.category, "member_status")
        self.assertIn("does not exist", result.reason.lower())
        self.assertTrue(result.metadata.get("orphaned"))

    # ========== Rate Validation Tests ==========

    def test_zero_rate_allowed(self):
        """Test that zero dues rate is ALLOWED for free memberships

        Business logic (membership_dues_schedule.py:842): "zero is allowed for free memberships"
        """
        # Arrange - set zero rate for free membership
        frappe.db.set_value("Membership Dues Schedule", self.schedule.name, "dues_rate", 0)
        frappe.db.commit()
        self.schedule.reload()

        checker = EligibilityChecker(self.schedule)

        # Act
        result = checker.check_eligibility(self.member)

        # Assert - zero rate should pass validation (allows free memberships)
        self.assertTrue(result.can_generate)
        self.assertEqual(result.category, "valid")

    def test_negative_rate_blocked(self):
        """Test that negative dues rate is blocked"""
        # Arrange - use db_set to bypass DocType validation
        frappe.db.set_value("Membership Dues Schedule", self.schedule.name, "dues_rate", -10.00)
        frappe.db.commit()
        self.schedule.reload()

        checker = EligibilityChecker(self.schedule)

        # Act
        result = checker.check_eligibility(self.member)

        # Assert
        self.assertFalse(result.can_generate)
        self.assertEqual(result.category, "rate")

    def test_extremely_high_rate_blocked(self):
        """Test that unrealistically high rates are blocked"""
        # Arrange - set rate to €100,000/month (way too high)
        self.schedule.dues_rate = 100000.00
        self.schedule.save()
        frappe.db.commit()

        checker = EligibilityChecker(self.schedule)

        # Act
        result = checker.check_eligibility(self.member)

        # Assert
        self.assertFalse(result.can_generate)
        self.assertEqual(result.category, "rate")
        self.assertIn("exceed", result.reason.lower())

    # ========== Duplicate Detection Tests ==========

    # NOTE: Duplicate detection and gap reset are thoroughly tested in
    # test_duplicate_invoice_detector.py. The eligibility checker correctly
    # delegates to that service via check_for_duplicate_invoices().
    # No additional integration tests needed here.

    # ========== Schedule Timing Tests ==========
    #
    # Removed with check_schedule_timing(): test_too_early_to_generate_blocked and
    # test_within_generation_window_allowed. Both pinned the invoice_days_before guard,
    # which no longer exists - eligibility no longer decides WHEN to generate. The
    # replacement coverage is TestCutoffIsCappedAtOnePeriodAhead above, which asserts
    # the cutoff comparison bounds generation on its own.

    # ========== Concurrency Tests ==========

    def test_skip_concurrency_check_parameter(self):
        """Test that skip_concurrency_check parameter works"""
        # Arrange
        checker = EligibilityChecker(self.schedule)

        # Act - with skip_concurrency_check=True
        result = checker.check_eligibility(self.member, skip_concurrency_check=True)

        # Assert - should complete without concurrency check
        # (Result depends on other checks, but concurrency check was skipped)
        self.assertIsNotNone(result)

    # ========== Integration Tests ==========

    def test_multiple_checks_fast_fail(self):
        """Test that checks fail fast on first problem"""
        # Arrange - create multiple problems using db_set to bypass validation
        frappe.db.set_value("Membership Dues Schedule", self.schedule.name, {
            "is_template": 1,
            "status": "Paused"
        })
        frappe.db.commit()
        self.schedule.reload()

        checker = EligibilityChecker(self.schedule)

        # Act
        result = checker.check_eligibility(self.member)

        # Assert - should fail on first check (template) not second (status)
        self.assertFalse(result.can_generate)
        self.assertIn("template", result.reason.lower())

    def test_result_repr(self):
        """Test that EligibilityResult has readable repr"""
        # Arrange
        result = EligibilityResult(False, "Test reason", "test_category")

        # Act
        repr_str = repr(result)

        # Assert
        self.assertIn("EligibilityResult", repr_str)
        self.assertIn("can_generate=False", repr_str)
        self.assertIn("Test reason", repr_str)
        self.assertIn("test_category", repr_str)
