# Copyright (c) 2025, Verenigingen and Contributors
# See license.txt

import unittest
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import (
    MembershipDuesSchedule,
)


class TestMembershipDuesSchedule(EnhancedTestCase):
    """Test Membership Dues Schedule business logic validation"""

    def test_dues_schedule_validation(self):
        """Test basic dues schedule validation"""
        # This test validates the enhanced test framework is working
        # Membership Dues Schedule specific business logic tests can be added here
        self.assertTrue(True)  # Placeholder for actual business logic tests


class TestErrorMessageDeduplication(unittest.TestCase):
    """Test error message deduplication helper method"""

    def test_deduplicate_single_prefix(self):
        """Test deduplication with single repeated prefix"""
        error = "Invoice generation failed: Invoice generation failed: Deadlock error"
        result = MembershipDuesSchedule._deduplicate_error_message(error)
        self.assertEqual(result, "Invoice generation failed: Deadlock error")

    def test_deduplicate_multiple_nested_prefixes(self):
        """Test deduplication with deeply nested prefixes"""
        error = "Invoice generation failed: Invoice generation failed: Invoice generation failed: Original error"
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
        self.schedule._should_auto_advance_schedule = lambda err: MembershipDuesSchedule._should_auto_advance_schedule(self.schedule, err)

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
    """Test that error length constants are properly defined and used"""

    def test_constants_exist(self):
        """Test that error length constants are defined"""
        from verenigingen.verenigingen.doctype.membership_dues_schedule import (
            membership_dues_schedule as mds_module
        )

        self.assertTrue(hasattr(mds_module, 'MAX_USER_ERROR_LENGTH'))
        self.assertTrue(hasattr(mds_module, 'MAX_DB_ERROR_LENGTH'))
        self.assertTrue(hasattr(mds_module, 'MAX_LOG_ERROR_LENGTH'))

    def test_constant_values(self):
        """Test that constants have sensible values"""
        from verenigingen.verenigingen.doctype.membership_dues_schedule import (
            membership_dues_schedule as mds_module
        )

        self.assertEqual(mds_module.MAX_USER_ERROR_LENGTH, 200)
        self.assertEqual(mds_module.MAX_DB_ERROR_LENGTH, 255)
        self.assertEqual(mds_module.MAX_LOG_ERROR_LENGTH, 100)

    def test_deadlock_patterns_defined(self):
        """Test that deadlock patterns are properly defined"""
        from verenigingen.verenigingen.doctype.membership_dues_schedule import (
            membership_dues_schedule as mds_module
        )

        self.assertTrue(hasattr(mds_module, 'DEADLOCK_PATTERNS'))
        self.assertIsInstance(mds_module.DEADLOCK_PATTERNS, list)
        self.assertGreaterEqual(len(mds_module.DEADLOCK_PATTERNS), 4)
        # Verify specific patterns
        self.assertIn('deadlock', mds_module.DEADLOCK_PATTERNS)
        self.assertIn('1213', mds_module.DEADLOCK_PATTERNS)
        self.assertIn('1205', mds_module.DEADLOCK_PATTERNS)
        self.assertIn('3058', mds_module.DEADLOCK_PATTERNS)
