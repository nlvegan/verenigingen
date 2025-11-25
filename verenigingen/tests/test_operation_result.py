"""
Test suite for OperationResult pattern.

Tests the OperationResult class including basic operations, error handling,
the new .chain() helper method, and integration patterns.

Author: Verenigingen Development Team
Created: 2025-11-24
"""

import unittest
from typing import List

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.utils.operation_result import OperationResult


class TestOperationResult(FrappeTestCase):
    """Test cases for OperationResult class."""

    def test_ok_creates_successful_result(self):
        """Test that OperationResult.ok() creates a successful result."""
        result = OperationResult.ok("test_data")

        self.assertTrue(result.success)
        self.assertEqual(result.data, "test_data")
        self.assertIsNone(result.error_message)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.metadata, {})

    def test_ok_with_metadata(self):
        """Test that OperationResult.ok() can include metadata."""
        result = OperationResult.ok("test_data", cached=True, count=5)

        self.assertTrue(result.success)
        self.assertEqual(result.data, "test_data")
        self.assertEqual(result.metadata["cached"], True)
        self.assertEqual(result.metadata["count"], 5)

    def test_fail_creates_failed_result(self):
        """Test that OperationResult.fail() creates a failed result."""
        result = OperationResult.fail("Operation failed")

        self.assertFalse(result.success)
        self.assertIsNone(result.data)
        self.assertEqual(result.error_message, "Operation failed")
        self.assertEqual(result.errors, [])

    def test_fail_with_errors_list(self):
        """Test that OperationResult.fail() can include error list."""
        errors = ["Error 1", "Error 2", "Error 3"]
        result = OperationResult.fail("Validation failed", errors=errors)

        self.assertFalse(result.success)
        self.assertEqual(result.error_message, "Validation failed")
        self.assertEqual(result.errors, errors)

    def test_fail_with_metadata(self):
        """Test that OperationResult.fail() can include metadata."""
        result = OperationResult.fail(
            "Operation failed",
            errors=["Error 1"],
            field="email",
            code="VALIDATION_ERROR"
        )

        self.assertFalse(result.success)
        self.assertEqual(result.metadata["field"], "email")
        self.assertEqual(result.metadata["code"], "VALIDATION_ERROR")

    def test_unwrap_returns_data_on_success(self):
        """Test that unwrap() returns data on successful result."""
        result = OperationResult.ok("test_data")
        data = result.unwrap()

        self.assertEqual(data, "test_data")

    def test_unwrap_raises_on_failure(self):
        """Test that unwrap() raises ValueError on failed result."""
        result = OperationResult.fail("Operation failed")

        with self.assertRaises(ValueError) as context:
            result.unwrap()

        self.assertIn("Operation failed", str(context.exception))

    def test_unwrap_includes_errors_in_exception(self):
        """Test that unwrap() includes error list in exception message."""
        result = OperationResult.fail(
            "Validation failed",
            errors=["Email required", "Name required"]
        )

        with self.assertRaises(ValueError) as context:
            result.unwrap()

        exception_msg = str(context.exception)
        self.assertIn("Validation failed", exception_msg)
        self.assertIn("Email required", exception_msg)
        self.assertIn("Name required", exception_msg)

    def test_unwrap_or_returns_data_on_success(self):
        """Test that unwrap_or() returns data on success."""
        result = OperationResult.ok("test_data")
        data = result.unwrap_or("default")

        self.assertEqual(data, "test_data")

    def test_unwrap_or_returns_default_on_failure(self):
        """Test that unwrap_or() returns default on failure."""
        result = OperationResult.fail("Operation failed")
        data = result.unwrap_or("default")

        self.assertEqual(data, "default")

    def test_map_transforms_data_on_success(self):
        """Test that map() transforms data on successful result."""
        result = OperationResult.ok(5)
        mapped = result.map(lambda x: x * 2)

        self.assertTrue(mapped.success)
        self.assertEqual(mapped.data, 10)

    def test_map_preserves_metadata(self):
        """Test that map() preserves metadata."""
        result = OperationResult.ok(5, cached=True)
        mapped = result.map(lambda x: x * 2)

        self.assertTrue(mapped.success)
        self.assertEqual(mapped.data, 10)
        self.assertEqual(mapped.metadata["cached"], True)

    def test_map_does_not_transform_on_failure(self):
        """Test that map() does not transform failed result."""
        result = OperationResult.fail("Operation failed")
        mapped = result.map(lambda x: x * 2)

        self.assertFalse(mapped.success)
        self.assertEqual(mapped.error_message, "Operation failed")

    def test_map_handles_exceptions(self):
        """Test that map() handles exceptions in transform function."""
        result = OperationResult.ok(5)

        def failing_transform(x):
            raise ValueError("Transform failed")

        mapped = result.map(failing_transform)

        self.assertFalse(mapped.success)
        self.assertIn("Transform failed", mapped.error_message)


class TestOperationResultChaining(FrappeTestCase):
    """Test cases for the .chain() helper method."""

    def test_chain_returns_self_on_success(self):
        """Test that chain() returns self unchanged on successful result."""
        result = OperationResult.ok("test_data", cached=True)
        chained = result.chain("Additional context")

        self.assertIs(chained, result)
        self.assertTrue(chained.success)
        self.assertEqual(chained.data, "test_data")

    def test_chain_wraps_failure_with_context(self):
        """Test that chain() wraps failed result with additional context."""
        result = OperationResult.fail(
            "Validation failed",
            errors=["Email required", "Name required"]
        )
        chained = result.chain("Failed to create member")

        self.assertFalse(chained.success)
        self.assertEqual(chained.error_message, "Failed to create member")
        self.assertEqual(chained.errors, ["Email required", "Name required"])

    def test_chain_preserves_metadata(self):
        """Test that chain() preserves original metadata."""
        result = OperationResult.fail(
            "Validation failed",
            errors=["Email required"],
            field="email",
            code="VALIDATION_ERROR"
        )
        chained = result.chain("Failed to create member")

        self.assertEqual(chained.metadata["field"], "email")
        self.assertEqual(chained.metadata["code"], "VALIDATION_ERROR")

    def test_chain_merges_additional_metadata(self):
        """Test that chain() can merge additional metadata."""
        result = OperationResult.fail(
            "Validation failed",
            errors=["Email required"],
            field="email"
        )
        chained = result.chain("Failed to create member", operation="create", doctype="Member")

        self.assertEqual(chained.metadata["field"], "email")
        self.assertEqual(chained.metadata["operation"], "create")
        self.assertEqual(chained.metadata["doctype"], "Member")

    def test_chain_uses_error_message_when_no_errors_list(self):
        """Test that chain() uses error_message when errors list is empty."""
        result = OperationResult.fail("Simple error message")
        chained = result.chain("Operation failed")

        self.assertFalse(chained.success)
        self.assertEqual(chained.error_message, "Operation failed")
        self.assertEqual(chained.errors, ["Simple error message"])

    def test_chain_multiple_levels(self):
        """Test that chain() can be called multiple times for multi-level context."""
        # Simulate nested service calls
        result = OperationResult.fail("Invalid email format", errors=["Invalid email format"])
        result = result.chain("Validation failed")
        result = result.chain("Failed to create member")
        result = result.chain("API request failed")

        self.assertFalse(result.success)
        self.assertEqual(result.error_message, "API request failed")
        # Original error should be preserved in errors list
        self.assertIn("Invalid email format", result.errors)


class TestOperationResultPatterns(FrappeTestCase):
    """Test cases for common OperationResult usage patterns."""

    def test_service_layer_validation_pattern(self):
        """Test typical service layer validation pattern."""

        def validate_email(email: str) -> OperationResult[None]:
            if not email:
                return OperationResult.fail("Email required", errors=["Email is required"])
            if "@" not in email:
                return OperationResult.fail("Invalid email", errors=["Email must contain @"])
            return OperationResult.ok(None)

        # Test successful validation
        result = validate_email("test@example.com")
        self.assertTrue(result.success)

        # Test missing email
        result = validate_email("")
        self.assertFalse(result.success)
        self.assertIn("Email is required", result.errors)

        # Test invalid email
        result = validate_email("invalid-email")
        self.assertFalse(result.success)
        self.assertIn("Email must contain @", result.errors)

    def test_service_layer_chaining_pattern(self):
        """Test service layer error propagation with chaining."""

        def validate_member(data: dict) -> OperationResult[None]:
            if not data.get("email"):
                return OperationResult.fail("Invalid email", errors=["Email is required"])
            return OperationResult.ok(None)

        def create_member(data: dict) -> OperationResult[str]:
            # Validate first
            validation_result = validate_member(data)
            if not validation_result.success:
                return validation_result.chain("Failed to create member")

            # Create member (simplified)
            member_id = "MEM-001"
            return OperationResult.ok(member_id, created=True)

        # Test successful creation
        result = create_member({"email": "test@example.com", "name": "Test User"})
        self.assertTrue(result.success)
        self.assertEqual(result.data, "MEM-001")
        self.assertTrue(result.metadata["created"])

        # Test failed validation
        result = create_member({"name": "Test User"})
        self.assertFalse(result.success)
        self.assertEqual(result.error_message, "Failed to create member")
        self.assertIn("Email is required", result.errors)

    def test_to_dict_for_api_responses(self):
        """Test converting OperationResult to dict for API responses."""

        # Test successful result
        result = OperationResult.ok("test_data", count=5)
        result_dict = result.to_dict()

        self.assertTrue(result_dict["success"])
        self.assertEqual(result_dict["data"], "test_data")
        self.assertEqual(result_dict["count"], 5)
        self.assertIn("timestamp", result_dict)

        # Test failed result
        result = OperationResult.fail(
            "Validation failed",
            errors=["Error 1", "Error 2"]
        )
        result_dict = result.to_dict()

        self.assertFalse(result_dict["success"])
        self.assertEqual(result_dict["error"], "Validation failed")
        self.assertEqual(result_dict["errors"], ["Error 1", "Error 2"])
        self.assertIn("timestamp", result_dict)

    def test_generic_type_safety(self):
        """Test that OperationResult maintains type information."""

        # String result
        str_result: OperationResult[str] = OperationResult.ok("test")
        self.assertEqual(str_result.data, "test")

        # Integer result
        int_result: OperationResult[int] = OperationResult.ok(42)
        self.assertEqual(int_result.data, 42)

        # List result
        list_result: OperationResult[List[str]] = OperationResult.ok(["a", "b", "c"])
        self.assertEqual(list_result.data, ["a", "b", "c"])

        # Dict result
        dict_result: OperationResult[dict] = OperationResult.ok({"key": "value"})
        self.assertEqual(dict_result.data["key"], "value")


class TestOperationResultMigrationHelpers(FrappeTestCase):
    """Test cases for migration helpers from dict-based results."""

    def test_from_dict_result_success(self):
        """Test converting successful dict result to OperationResult."""
        legacy_result = {
            "success": True,
            "data": "test_data",
            "count": 5,
            "cached": True
        }

        result = OperationResult.from_dict_result(legacy_result)

        self.assertTrue(result.success)
        self.assertEqual(result.data, "test_data")
        self.assertEqual(result.metadata["count"], 5)
        self.assertEqual(result.metadata["cached"], True)

    def test_from_dict_result_failure(self):
        """Test converting failed dict result to OperationResult."""
        legacy_result = {
            "success": False,
            "error": "Operation failed",
            "errors": ["Error 1", "Error 2"],
            "field": "email"
        }

        result = OperationResult.from_dict_result(legacy_result)

        self.assertFalse(result.success)
        self.assertEqual(result.error_message, "Operation failed")
        self.assertEqual(result.errors, ["Error 1", "Error 2"])
        self.assertEqual(result.metadata["field"], "email")


def run_tests():
    """Helper function to run all OperationResult tests."""
    import sys

    # Create test suite
    suite = unittest.TestSuite()

    # Add all test classes
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestOperationResult))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestOperationResultChaining))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestOperationResultPatterns))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestOperationResultMigrationHelpers))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Return exit code
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_tests())
