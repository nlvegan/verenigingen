"""
Tests for Deadlock Retry Utilities

Tests the centralized deadlock retry logic in retry_utilities.py:
- is_deadlock_error() - deadlock detection
- with_deadlock_retry() - decorator for automatic retry
- execute_with_deadlock_retry() - function wrapper for retry

These are unit tests that mock exceptions rather than requiring database setup.
"""

import unittest
from unittest.mock import patch

import frappe

from verenigingen.utils.retry_utilities import (
    DEADLOCK_BASE_DELAY,
    DEADLOCK_MAX_RETRIES,
    execute_with_deadlock_retry,
    is_deadlock_error,
    with_deadlock_retry,
)


class TestIsDeadlockError(unittest.TestCase):
    """Test is_deadlock_error() detection function"""

    def test_detects_frappe_query_deadlock_error(self):
        """Should detect frappe.QueryDeadlockError"""
        if hasattr(frappe, "QueryDeadlockError"):
            error = frappe.QueryDeadlockError("Deadlock found")
            self.assertTrue(is_deadlock_error(error))

    def test_detects_mysql_error_code_1213(self):
        """Should detect MySQL error code 1213 in error message"""
        error = Exception("(1213, 'Deadlock found when trying to get lock')")
        self.assertTrue(is_deadlock_error(error))

    def test_detects_deadlock_keyword_lowercase(self):
        """Should detect 'deadlock' keyword (case insensitive)"""
        error = Exception("A deadlock was detected during the transaction")
        self.assertTrue(is_deadlock_error(error))

    def test_detects_deadlock_keyword_mixed_case(self):
        """Should detect 'Deadlock' keyword"""
        error = Exception("Deadlock found when trying to get lock")
        self.assertTrue(is_deadlock_error(error))

    def test_returns_false_for_non_deadlock_error(self):
        """Should return False for non-deadlock errors"""
        error = Exception("Permission denied")
        self.assertFalse(is_deadlock_error(error))

    def test_returns_false_for_validation_error(self):
        """Should return False for validation errors"""
        error = frappe.ValidationError("Field is required")
        self.assertFalse(is_deadlock_error(error))

    def test_returns_false_for_does_not_exist_error(self):
        """Should return False for DoesNotExistError"""
        error = frappe.DoesNotExistError("Document not found")
        self.assertFalse(is_deadlock_error(error))


class TestWithDeadlockRetry(unittest.TestCase):
    """Test with_deadlock_retry() decorator"""

    def test_succeeds_on_first_try(self):
        """Should succeed without retry if no error"""
        call_count = 0

        @with_deadlock_retry(max_retries=3)
        def successful_operation():
            nonlocal call_count
            call_count += 1
            return "success"

        result = successful_operation()
        self.assertEqual(result, "success")
        self.assertEqual(call_count, 1)

    @patch("verenigingen.utils.retry_utilities.time.sleep")
    def test_retries_on_deadlock_error(self, mock_sleep):
        """Should retry on deadlock error and eventually succeed"""
        call_count = 0

        @with_deadlock_retry(max_retries=3, base_delay=0.1)
        def flaky_operation():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("(1213, 'Deadlock found')")
            return "success"

        result = flaky_operation()
        self.assertEqual(result, "success")
        self.assertEqual(call_count, 3)
        # Should have slept twice (before retry 2 and 3)
        self.assertEqual(mock_sleep.call_count, 2)

    @patch("verenigingen.utils.retry_utilities.time.sleep")
    def test_raises_after_max_retries_exhausted(self, mock_sleep):
        """Should raise exception after max retries exhausted"""
        call_count = 0

        @with_deadlock_retry(max_retries=2, base_delay=0.1)
        def always_deadlocks():
            nonlocal call_count
            call_count += 1
            raise Exception("(1213, 'Deadlock found')")

        with self.assertRaises(Exception) as context:
            always_deadlocks()

        self.assertIn("1213", str(context.exception))
        self.assertEqual(call_count, 3)  # Initial + 2 retries

    def test_does_not_retry_non_deadlock_error(self):
        """Should not retry on non-deadlock errors"""
        call_count = 0

        @with_deadlock_retry(max_retries=3)
        def permission_error():
            nonlocal call_count
            call_count += 1
            raise frappe.ValidationError("Permission denied")

        with self.assertRaises(frappe.ValidationError):
            permission_error()

        self.assertEqual(call_count, 1)  # No retry

    def test_uses_custom_operation_name_in_logging(self):
        """Should use custom operation name for logging"""
        @with_deadlock_retry(max_retries=1, operation_name="custom_op")
        def operation():
            return "done"

        result = operation()
        self.assertEqual(result, "done")


class TestExecuteWithDeadlockRetry(unittest.TestCase):
    """Test execute_with_deadlock_retry() function"""

    def test_executes_operation_successfully(self):
        """Should execute operation and return result"""
        def simple_operation():
            return {"status": "success", "value": 42}

        result = execute_with_deadlock_retry(
            simple_operation,
            operation_name="test operation"
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["value"], 42)

    @patch("verenigingen.utils.retry_utilities.time.sleep")
    def test_retries_on_deadlock_and_succeeds(self, mock_sleep):
        """Should retry on deadlock and return result on success"""
        attempt = 0

        def eventually_succeeds():
            nonlocal attempt
            attempt += 1
            if attempt < 2:
                raise Exception("Deadlock found")
            return "completed"

        result = execute_with_deadlock_retry(
            eventually_succeeds,
            operation_name="test retry",
            base_delay=0.1
        )
        self.assertEqual(result, "completed")
        self.assertEqual(attempt, 2)

    @patch("verenigingen.utils.retry_utilities.time.sleep")
    def test_raises_after_all_retries_fail(self, mock_sleep):
        """Should raise exception after all retries exhausted"""
        def always_fails():
            raise Exception("(1213, 'Deadlock')")

        with self.assertRaises(Exception) as context:
            execute_with_deadlock_retry(
                always_fails,
                operation_name="doomed operation",
                max_retries=2,
                base_delay=0.1
            )

        self.assertIn("1213", str(context.exception))

    def test_does_not_retry_non_deadlock_exception(self):
        """Should not retry non-deadlock exceptions"""
        call_count = 0

        def raises_validation_error():
            nonlocal call_count
            call_count += 1
            raise frappe.ValidationError("Invalid data")

        with self.assertRaises(frappe.ValidationError):
            execute_with_deadlock_retry(
                raises_validation_error,
                operation_name="validation test",
                max_retries=3
            )

        self.assertEqual(call_count, 1)

    @patch("verenigingen.utils.retry_utilities.frappe.log_error")
    @patch("verenigingen.utils.retry_utilities.time.sleep")
    def test_logs_error_when_log_errors_true(self, mock_sleep, mock_log_error):
        """Should log error when log_errors=True and retries exhausted"""
        def always_deadlocks():
            raise Exception("Deadlock found")

        with self.assertRaises(Exception):
            execute_with_deadlock_retry(
                always_deadlocks,
                operation_name="logged operation",
                max_retries=1,
                log_errors=True
            )

        # Should have logged the error
        mock_log_error.assert_called()

    @patch("verenigingen.utils.retry_utilities.frappe.log_error")
    def test_does_not_log_when_log_errors_false(self, mock_log_error):
        """Should not log error when log_errors=False"""
        def raises_non_deadlock():
            raise frappe.ValidationError("Test error")

        with self.assertRaises(frappe.ValidationError):
            execute_with_deadlock_retry(
                raises_non_deadlock,
                operation_name="unlogged operation",
                log_errors=False
            )

        # Should not have logged since it's a non-deadlock error that fails immediately
        mock_log_error.assert_not_called()


class TestDeadlockRetryConstants(unittest.TestCase):
    """Test that constants are properly defined"""

    def test_max_retries_is_reasonable(self):
        """DEADLOCK_MAX_RETRIES should be a reasonable value"""
        self.assertGreaterEqual(DEADLOCK_MAX_RETRIES, 1)
        self.assertLessEqual(DEADLOCK_MAX_RETRIES, 10)

    def test_base_delay_is_reasonable(self):
        """DEADLOCK_BASE_DELAY should be a reasonable value"""
        self.assertGreater(DEADLOCK_BASE_DELAY, 0)
        self.assertLess(DEADLOCK_BASE_DELAY, 1.0)  # Less than 1 second
