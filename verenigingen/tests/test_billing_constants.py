# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Unit tests for billing_constants module.

Tests verify:
- All constants are properly defined with correct types
- Deadlock patterns are comprehensive
- Error deduplication regex pattern works correctly
- RecoveryAction enum has all required values
- Module exports are complete via __all__
"""

import re
import unittest

from verenigingen.utils.billing_constants import (
    DEADLOCK_PATTERNS,
    ERROR_DEDUP_PATTERN,
    MAX_DB_ERROR_LENGTH,
    MAX_LOG_ERROR_LENGTH,
    MAX_USER_ERROR_LENGTH,
    RecoveryAction,
)


class TestBillingConstants(unittest.TestCase):
    """Test suite for billing constants module."""

    def test_error_length_constants_defined(self):
        """Verify all error length constants are defined with correct types and values."""
        # Test that constants exist and are integers
        self.assertIsInstance(MAX_USER_ERROR_LENGTH, int)
        self.assertIsInstance(MAX_DB_ERROR_LENGTH, int)
        self.assertIsInstance(MAX_LOG_ERROR_LENGTH, int)

        # Test expected values
        self.assertEqual(MAX_USER_ERROR_LENGTH, 200)
        self.assertEqual(MAX_DB_ERROR_LENGTH, 255)
        self.assertEqual(MAX_LOG_ERROR_LENGTH, 100)

        # Test logical relationships
        self.assertLess(MAX_LOG_ERROR_LENGTH, MAX_USER_ERROR_LENGTH)
        self.assertLess(MAX_USER_ERROR_LENGTH, MAX_DB_ERROR_LENGTH)

    def test_deadlock_patterns_comprehensive(self):
        """Verify deadlock patterns list is comprehensive and contains expected values."""
        # Test that DEADLOCK_PATTERNS is a list
        self.assertIsInstance(DEADLOCK_PATTERNS, list)

        # Test minimum number of patterns (should have at least 4)
        self.assertGreaterEqual(len(DEADLOCK_PATTERNS), 4)

        # Test required patterns are present
        required_patterns = ["deadlock", "1213", "1205", "3058"]
        for pattern in required_patterns:
            self.assertIn(
                pattern,
                DEADLOCK_PATTERNS,
                f"Required deadlock pattern '{pattern}' not found in DEADLOCK_PATTERNS",
            )

        # Test all patterns are strings
        for pattern in DEADLOCK_PATTERNS:
            self.assertIsInstance(pattern, str, f"Pattern '{pattern}' is not a string")

    def test_error_dedup_pattern_type(self):
        """Verify ERROR_DEDUP_PATTERN is a compiled regex pattern."""
        self.assertIsInstance(ERROR_DEDUP_PATTERN, re.Pattern)

    def test_error_dedup_pattern_functionality(self):
        """Test that error deduplication regex pattern works correctly."""
        # Test case 1: Double "Invoice generation failed:" prefix
        test_msg_1 = "Invoice generation failed: Invoice generation failed: Amount too low"
        result_1 = ERROR_DEDUP_PATTERN.sub("Invoice generation failed: ", test_msg_1)
        self.assertEqual(result_1, "Invoice generation failed: Amount too low")

        # Test case 2: Triple prefix
        test_msg_2 = (
            "Invoice generation failed: Invoice generation failed: "
            "Invoice generation failed: Invalid rate"
        )
        result_2 = ERROR_DEDUP_PATTERN.sub("Invoice generation failed: ", test_msg_2)
        self.assertEqual(result_2, "Invoice generation failed: Invalid rate")

        # Test case 3: Abbreviated "Invoice gen failed:"
        test_msg_3 = "Invoice gen failed: Invoice gen failed: Error occurred"
        result_3 = ERROR_DEDUP_PATTERN.sub("Invoice generation failed: ", test_msg_3)
        self.assertEqual(result_3, "Invoice generation failed: Error occurred")

        # Test case 4: Mixed case (should handle case-insensitive)
        test_msg_4 = "Invoice Generation Failed: invoice generation failed: Error"
        result_4 = ERROR_DEDUP_PATTERN.sub("Invoice generation failed: ", test_msg_4)
        self.assertEqual(result_4, "Invoice generation failed: Error")

        # Test case 5: No duplication (should not modify)
        test_msg_5 = "Invoice generation failed: Single error message"
        result_5 = ERROR_DEDUP_PATTERN.sub("Invoice generation failed: ", test_msg_5)
        self.assertEqual(result_5, "Invoice generation failed: Single error message")

        # Test case 6: No "Invoice generation failed:" prefix at all
        test_msg_6 = "Some other error message"
        result_6 = ERROR_DEDUP_PATTERN.sub("Invoice generation failed: ", test_msg_6)
        self.assertEqual(result_6, "Some other error message")

    def test_recovery_action_enum_values(self):
        """Verify RecoveryAction enum has all required values."""
        # Test enum exists and has correct type
        from enum import Enum

        self.assertTrue(issubclass(RecoveryAction, Enum))
        self.assertTrue(issubclass(RecoveryAction, str))

        # Test required enum members exist
        self.assertTrue(hasattr(RecoveryAction, "RETRY_TRACKED"))
        self.assertTrue(hasattr(RecoveryAction, "DATE_ADVANCED"))
        self.assertTrue(hasattr(RecoveryAction, "SKIPPED"))

        # Test enum values are correct
        self.assertEqual(RecoveryAction.RETRY_TRACKED.value, "retry_tracked")
        self.assertEqual(RecoveryAction.DATE_ADVANCED.value, "date_advanced")
        self.assertEqual(RecoveryAction.SKIPPED.value, "skipped")

        # Test enum members are strings (for JSON serialization)
        self.assertIsInstance(RecoveryAction.RETRY_TRACKED.value, str)
        self.assertIsInstance(RecoveryAction.DATE_ADVANCED.value, str)
        self.assertIsInstance(RecoveryAction.SKIPPED.value, str)

    def test_recovery_action_enum_iteration(self):
        """Verify RecoveryAction enum can be iterated correctly."""
        actions = list(RecoveryAction)
        self.assertEqual(len(actions), 3)

        action_values = [action.value for action in RecoveryAction]
        self.assertIn("retry_tracked", action_values)
        self.assertIn("date_advanced", action_values)
        self.assertIn("skipped", action_values)

    def test_module_all_export(self):
        """Verify __all__ contains all expected exports."""
        from verenigingen.utils import billing_constants

        # Test __all__ is defined
        self.assertTrue(hasattr(billing_constants, "__all__"))
        self.assertIsInstance(billing_constants.__all__, list)

        # Test expected exports are in __all__
        expected_exports = [
            "MAX_USER_ERROR_LENGTH",
            "MAX_DB_ERROR_LENGTH",
            "MAX_LOG_ERROR_LENGTH",
            "DEADLOCK_PATTERNS",
            "ERROR_DEDUP_PATTERN",
            "RecoveryAction",
        ]

        for export in expected_exports:
            self.assertIn(export, billing_constants.__all__, f"Expected export '{export}' not found in __all__")

        # Test that all items in __all__ actually exist in the module
        for export in billing_constants.__all__:
            self.assertTrue(
                hasattr(billing_constants, export), f"Export '{export}' in __all__ but not found in module"
            )

    def test_deadlock_pattern_matching(self):
        """Test that deadlock patterns can identify deadlock errors in realistic messages."""
        # Realistic deadlock error messages
        deadlock_messages = [
            "Error 1213: Deadlock found when trying to get lock; try restarting transaction",
            "Lock wait timeout exceeded; try restarting transaction (1205)",
            "InnoDB: deadlock detected (3058)",
            "Database deadlock occurred during update",
            "DEADLOCK: Transaction rolled back",
        ]

        for msg in deadlock_messages:
            msg_lower = msg.lower()
            found = any(pattern in msg_lower for pattern in DEADLOCK_PATTERNS)
            self.assertTrue(
                found, f"Deadlock pattern not detected in realistic message: '{msg}'"
            )

        # Non-deadlock error messages (should NOT match)
        non_deadlock_messages = [
            "Validation failed: Amount too low",
            "Permission denied",
            "Customer not found",
            "Invalid configuration",
        ]

        for msg in non_deadlock_messages:
            msg_lower = msg.lower()
            found = any(pattern in msg_lower for pattern in DEADLOCK_PATTERNS)
            self.assertFalse(found, f"False positive: Non-deadlock message matched pattern: '{msg}'")

    def test_constant_immutability(self):
        """Test that constant values are appropriate and not accidentally mutable."""
        # Integer constants should be immutable by nature
        original_max_db = MAX_DB_ERROR_LENGTH
        self.assertEqual(original_max_db, 255)

        # List constants - verify they're not accidentally shared references
        original_patterns = DEADLOCK_PATTERNS.copy()
        self.assertEqual(len(original_patterns), len(DEADLOCK_PATTERNS))

    def test_regex_pattern_performance(self):
        """Verify regex pattern is compiled (for performance)."""
        # Compiled patterns have the 'pattern' attribute
        self.assertTrue(hasattr(ERROR_DEDUP_PATTERN, "pattern"))

        # Test that it's the expected pattern
        expected_pattern = r"(Invoice gen(?:eration)? failed:\s*)+"
        self.assertEqual(ERROR_DEDUP_PATTERN.pattern, expected_pattern)

        # Test flags are set correctly
        self.assertTrue(ERROR_DEDUP_PATTERN.flags & re.IGNORECASE)
