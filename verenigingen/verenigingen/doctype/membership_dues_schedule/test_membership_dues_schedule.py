# Copyright (c) 2025, Verenigingen and Contributors
# See license.txt

import unittest
from unittest.mock import MagicMock

import frappe
from frappe.utils import add_days, add_months, getdate, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import (
    MembershipDuesSchedule,
)


class TestMembershipDuesSchedule(EnhancedTestCase):
    """Test Membership Dues Schedule business logic validation"""

    def test_negative_dues_rate_rejected_on_save(self):
        """A real, saved schedule cannot be given a negative dues_rate.

        The controller's validate() chain runs validate_financial_constraints()
        (rejects amounts below the template's minimum) before
        validate_rate_boundaries() (rejects negative amounts specifically, via
        InvalidDuesRateError). With a real, non-zero template minimum,
        -5.0 trips the financial-constraints guard first and surfaces a plain
        frappe.ValidationError naming the rejected rate. Unlike the existing
        unit tests in test_dues_schedule_validation_service.py (which call
        the service functions directly against a manually-built, unsaved
        doc), this exercises the full document lifecycle: a real member with
        an active membership and an already-saved schedule, mutated and
        saved again, to prove a negative rate is actually rejected end to
        end through doc.save() rather than merely by the isolated service
        unit.
        """
        membership_type = self.create_test_membership_type(
            membership_type_name="NegRate Type",
            amount=30.0,
            contribution_mode="Fixed Amount",
        )
        member, schedule = self.create_test_member_with_schedule(
            first_name="NegRate",
            last_name="Member",
            membership_type_name=membership_type.name,
            start_date=today(),
        )

        schedule.dues_rate = -5.0
        with self.assertRaises(frappe.ValidationError) as cm:
            schedule.save()
        self.assertIn("-5.00", str(cm.exception))

        # The rejected value must not have been persisted.
        schedule.reload()
        self.assertGreaterEqual(schedule.dues_rate, 0)


class TestMonthlyDuplicateProbe(EnhancedTestCase):
    """
    check_for_duplicate_invoices() must probe the period this member is actually
    about to be billed for, not the calendar month surrounding today.

    Coverage periods run from the member's join date, so a mid-month Monthly
    joiner's periods straddle two calendar months. Probing the calendar month
    therefore permanently overlaps the member's OWN latest invoice, and
    EligibilityChecker.check_for_duplicates blocks generation for most of every
    month. It fails softly - the orchestrator matches "coverage overlap" and logs
    at info - so the member is simply never invoiced on time.
    """

    def _monthly_member_joining_last_month(self):
        """A Monthly member who joined on the 3rd of the previous month.

        The 3rd is arbitrary but must be far enough into the month that the
        resulting period straddles a calendar boundary in both directions.
        """
        first_of_this_month = getdate(today()).replace(day=1)
        join_date = getdate(add_days(first_of_this_month, -1)).replace(day=3)

        membership_type = self.create_test_membership_type(
            membership_type_name="Monthly Probe Type",
            amount=10.0,
            contribution_mode="Fixed Amount",
        )
        member, schedule = self.create_test_member_with_schedule(
            first_name="MonthlyProbe",
            last_name="Member",
            membership_type_name=membership_type.name,
            start_date=join_date,
        )
        schedule.billing_frequency = "Monthly"
        schedule.save()
        frappe.db.commit()

        return member, schedule, join_date

    def test_second_monthly_period_is_not_blocked_by_the_surrounding_calendar_month(self):
        """
        Given the first invoice covering join_date .. join_date + 1 month - 1 day,
        the member must remain eligible for their SECOND invoice.

        This is the assertion the original coverage-period suite was missing: it
        stopped at the first invoice, which is why probing the calendar month
        shipped green.
        """
        from verenigingen.services.billing.invoice_generator import InvoiceGenerator

        member, schedule, join_date = self._monthly_member_joining_last_month()

        first_start = join_date
        first_end = add_days(add_months(join_date, 1), -1)
        result = InvoiceGenerator(schedule).generate_invoice(
            coverage_start=first_start, coverage_end=first_end, member_doc=member
        )
        self.assertTrue(result.success, getattr(result, "error_message", None))
        frappe.db.commit()

        # Precondition: the first period really does straddle the calendar
        # boundary, otherwise the calendar probe would coincidentally agree.
        self.assertNotEqual(first_start.month, first_end.month)

        duplicate_check = schedule.check_for_duplicate_invoices()

        self.assertTrue(
            duplicate_check["can_generate"],
            f"second Monthly period wrongly blocked: {duplicate_check['reason']}",
        )


class TestErrorMessageDeduplication(unittest.TestCase):
    """Test error message deduplication helper method"""

    def test_deduplicate_single_prefix(self):
        """Test deduplication with single repeated prefix"""
        error = "Invoice generation failed: Invoice generation failed: Deadlock error"
        result = MembershipDuesSchedule._deduplicate_error_message(error)
        self.assertEqual(result, "Invoice generation failed: Deadlock error")

    def test_deduplicate_multiple_nested_prefixes(self):
        """Test deduplication with deeply nested prefixes"""
        error = (
            "Invoice generation failed: Invoice generation failed: Invoice generation failed: Original error"
        )
        result = MembershipDuesSchedule._deduplicate_error_message(error)
        self.assertEqual(result, "Invoice generation failed: Original error")

    def test_deduplicate_invoice_gen_failed_prefix(self):
        """Test deduplication of abbreviated 'Invoice gen failed' prefix"""
        error = "Invoice gen failed: Invoice gen failed: Database error"
        result = MembershipDuesSchedule._deduplicate_error_message(error)
        self.assertEqual(result, "Invoice generation failed: Database error")

    def test_deduplicate_mixed_prefixes(self):
        """Test deduplication with mixed full and abbreviated prefixes"""
        error = "Invoice generation failed: Invoice gen failed: Error message"
        result = MembershipDuesSchedule._deduplicate_error_message(error)
        # Should normalize to full form
        self.assertIn("Invoice generation failed:", result)
        self.assertNotIn("Invoice gen failed: Invoice", result)

    def test_deduplicate_no_repetition(self):
        """Test that non-repeated messages pass through unchanged"""
        error = "Simple error message without repetition"
        result = MembershipDuesSchedule._deduplicate_error_message(error)
        self.assertEqual(result, error)

    def test_deduplicate_empty_string(self):
        """Test handling of empty error message"""
        result = MembershipDuesSchedule._deduplicate_error_message("")
        self.assertEqual(result, "")

    def test_deduplicate_none_value(self):
        """Test handling of None error message"""
        result = MembershipDuesSchedule._deduplicate_error_message(None)
        self.assertIsNone(result)

    def test_deduplicate_preserves_content(self):
        """Test that actual error content is preserved"""
        error = "Invoice generation failed: Invoice generation failed: (1213, 'Deadlock found')"
        result = MembershipDuesSchedule._deduplicate_error_message(error)
        self.assertIn("(1213, 'Deadlock found')", result)
        # Should only have one prefix
        self.assertEqual(result.count("Invoice generation failed:"), 1)


class TestDeadlockDetection(unittest.TestCase):
    """Test deadlock error detection helper method"""

    def test_detect_generic_deadlock_keyword(self):
        """Test detection of generic 'deadlock' keyword"""
        error = "Database deadlock detected while processing"
        self.assertTrue(MembershipDuesSchedule._is_deadlock_error(error))

    def test_detect_mysql_error_1213(self):
        """Test detection of MySQL error code 1213"""
        error = "(1213, 'Deadlock found when trying to get lock; try restarting transaction')"
        self.assertTrue(MembershipDuesSchedule._is_deadlock_error(error))

    def test_detect_mysql_error_1205(self):
        """Test detection of MySQL error code 1205 (lock wait timeout)"""
        error = "pymysql.err.OperationalError: (1205, 'Lock wait timeout exceeded')"
        self.assertTrue(MembershipDuesSchedule._is_deadlock_error(error))

    def test_detect_mysql_error_3058(self):
        """Test detection of MySQL error code 3058 (InnoDB deadlock)"""
        error = "InnoDB detected deadlock (3058)"
        self.assertTrue(MembershipDuesSchedule._is_deadlock_error(error))

    def test_detect_case_insensitive(self):
        """Test case-insensitive deadlock detection"""
        error = "DEADLOCK FOUND IN DATABASE"
        self.assertTrue(MembershipDuesSchedule._is_deadlock_error(error))

    def test_reject_non_deadlock_error(self):
        """Test that non-deadlock errors are not detected"""
        error = "Validation error: Invalid field value"
        self.assertFalse(MembershipDuesSchedule._is_deadlock_error(error))

    def test_reject_empty_error(self):
        """Test handling of empty error message"""
        self.assertFalse(MembershipDuesSchedule._is_deadlock_error(""))

    def test_reject_none_error(self):
        """Test handling of None error message"""
        self.assertFalse(MembershipDuesSchedule._is_deadlock_error(None))

    def test_detect_in_traceback(self):
        """Test detection when deadlock is mentioned in traceback"""
        error = """Traceback (most recent call last):
  File "invoice.py", line 123
    raise Exception("Deadlock occurred")
Exception: Deadlock occurred"""
        self.assertTrue(MembershipDuesSchedule._is_deadlock_error(error))


class TestDeadlockHandling(unittest.TestCase):
    """Integration tests for deadlock handling in invoice generation"""

    def setUp(self):
        """Create a minimal MembershipDuesSchedule mock for testing error handling"""
        # Create a mock schedule object with just the fields we need for error tracking
        self.schedule = MagicMock(spec=MembershipDuesSchedule)
        self.schedule.name = "Test-Schedule-001"
        self.schedule.custom_invoice_retry_count = 0
        self.schedule.custom_deadlock_count = 0
        self.schedule.custom_last_invoice_failure_date = None
        self.schedule.custom_last_invoice_error = None
        self.schedule.custom_requires_manual_review = 0

        # Bind the real methods to our mock
        self.schedule._is_deadlock_error = MembershipDuesSchedule._is_deadlock_error
        self.schedule._deduplicate_error_message = MembershipDuesSchedule._deduplicate_error_message
        self.schedule._should_auto_advance_schedule = (
            lambda err: MembershipDuesSchedule._should_auto_advance_schedule(self.schedule, err)
        )

    def test_deadlock_detection_in_error_message(self):
        """Test that deadlock errors are correctly identified"""
        deadlock_error = "(1213, 'Deadlock found when trying to get lock')"
        self.assertTrue(self.schedule._is_deadlock_error(deadlock_error))

    def test_regular_error_not_detected_as_deadlock(self):
        """Test that regular errors are not identified as deadlocks"""
        validation_error = "Validation error: Missing required field"
        self.assertFalse(self.schedule._is_deadlock_error(validation_error))

    def test_should_not_auto_advance_on_deadlock(self):
        """Test that deadlocks don't cause schedule auto-advancement"""
        deadlock_error = "(1213, 'Deadlock found')"
        should_advance = self.schedule._should_auto_advance_schedule(deadlock_error)

        # Should return False to prevent skipping the invoice
        self.assertFalse(should_advance)


class TestErrorConstants(unittest.TestCase):
    """Test that error length constants are properly defined in billing_constants"""

    def test_constants_exist(self):
        """Test that error length constants are defined"""
        from verenigingen.utils import billing_constants as bc

        self.assertTrue(hasattr(bc, "MAX_USER_ERROR_LENGTH"))
        self.assertTrue(hasattr(bc, "MAX_DB_ERROR_LENGTH"))
        self.assertTrue(hasattr(bc, "MAX_LOG_ERROR_LENGTH"))

    def test_constant_values(self):
        """Test that constants have sensible values"""
        from verenigingen.services.billing.billing_constants import (
            MAX_DB_ERROR_LENGTH,
            MAX_LOG_ERROR_LENGTH,
            MAX_USER_ERROR_LENGTH,
        )

        self.assertEqual(MAX_USER_ERROR_LENGTH, 200)
        self.assertEqual(MAX_DB_ERROR_LENGTH, 255)
        self.assertEqual(MAX_LOG_ERROR_LENGTH, 100)

    def test_deadlock_patterns_defined(self):
        """Test that deadlock patterns are properly defined"""
        from verenigingen.services.billing.billing_constants import DEADLOCK_PATTERNS

        self.assertIsInstance(DEADLOCK_PATTERNS, list)
        self.assertGreaterEqual(len(DEADLOCK_PATTERNS), 4)
        # Verify specific patterns
        self.assertIn("deadlock", DEADLOCK_PATTERNS)
        self.assertIn("1213", DEADLOCK_PATTERNS)
        self.assertIn("1205", DEADLOCK_PATTERNS)
        self.assertIn("3058", DEADLOCK_PATTERNS)
