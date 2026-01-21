"""
Test suite for OperationResult pattern.

Tests the OperationResult class including basic operations, error handling,
the new .chain() helper method, and integration patterns.

Author: Verenigingen Development Team
Created: 2025-11-24
Updated: 2026-01-20 - Added tests for new features (from_exception, http_status,
                      OperationResultException, wrap_operation improvements, to_dict nested schema)
"""

import unittest
from typing import List

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.utils.operation_result import (
    OperationResult,
    OperationResultException,
    wrap_operation,
)


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
        """Test that unwrap() raises OperationResultException on failed result."""
        result = OperationResult.fail("Operation failed")

        with self.assertRaises(OperationResultException) as context:
            result.unwrap()

        self.assertIn("Operation failed", str(context.exception))
        # Verify the exception preserves the original result
        self.assertIs(context.exception.operation_result, result)

    def test_unwrap_includes_errors_in_exception(self):
        """Test that unwrap() includes error list in exception message."""
        result = OperationResult.fail(
            "Validation failed",
            errors=["Email required", "Name required"]
        )

        with self.assertRaises(OperationResultException) as context:
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
        """Test converting OperationResult to dict for API responses (nested schema)."""

        # Test successful result with nested schema (default)
        result = OperationResult.ok("test_data", count=5)
        result_dict = result.to_dict()

        self.assertTrue(result_dict["success"])
        self.assertEqual(result_dict["data"], "test_data")
        # Metadata should be under "meta" key in nested schema
        self.assertEqual(result_dict["meta"]["count"], 5)
        self.assertIn("timestamp", result_dict)

        # Test failed result with nested schema
        result = OperationResult.fail(
            "Validation failed",
            errors=["Error 1", "Error 2"]
        )
        result_dict = result.to_dict()

        self.assertFalse(result_dict["success"])
        # Error should be a nested object in nested schema
        self.assertEqual(result_dict["error"]["message"], "Validation failed")
        self.assertEqual(result_dict["error"]["errors"], ["Error 1", "Error 2"])
        self.assertIn("timestamp", result_dict)

    def test_to_dict_legacy_flat_schema(self):
        """Test converting OperationResult using legacy flat schema."""

        # Test successful result with flat schema
        result = OperationResult.ok("test_data", count=5)
        result_dict = result.to_dict(nested=False)

        self.assertTrue(result_dict["success"])
        self.assertEqual(result_dict["data"], "test_data")
        # Metadata should be flattened in legacy schema
        self.assertEqual(result_dict["count"], 5)
        self.assertIn("timestamp", result_dict)

        # Test failed result with flat schema
        result = OperationResult.fail(
            "Validation failed",
            errors=["Error 1", "Error 2"]
        )
        result_dict = result.to_dict(nested=False)

        self.assertFalse(result_dict["success"])
        # Error should be at top level in flat schema
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


class TestOperationResultException(FrappeTestCase):
    """Test cases for the OperationResultException class."""

    def test_exception_preserves_result(self):
        """Test that OperationResultException preserves the full OperationResult."""
        result = OperationResult.fail(
            "Test error",
            errors=["Error 1"],
            error_code="TEST_001",
            http_status=400,
            field="email"
        )

        exc = OperationResultException(result)

        self.assertIs(exc.operation_result, result)
        self.assertEqual(exc.error_code, "TEST_001")
        self.assertEqual(exc.http_status, 400)
        self.assertEqual(exc.errors, ["Error 1"])

    def test_exception_message_format(self):
        """Test that exception message includes error details."""
        result = OperationResult.fail(
            "Validation failed",
            errors=["Email required", "Name required"]
        )

        exc = OperationResultException(result)
        msg = str(exc)

        self.assertIn("Validation failed", msg)
        self.assertIn("Email required", msg)
        self.assertIn("Name required", msg)

    def test_exception_properties_return_none_when_not_set(self):
        """Test that exception properties return None for unset fields."""
        result = OperationResult.fail("Simple error")
        exc = OperationResultException(result)

        self.assertIsNone(exc.error_code)
        self.assertIsNone(exc.http_status)
        self.assertEqual(exc.errors, [])


class TestFromException(FrappeTestCase):
    """Test cases for the from_exception() helper method."""

    def test_from_exception_basic(self):
        """Test basic exception conversion."""
        try:
            raise ValueError("Test error")
        except Exception as e:
            result = OperationResult.from_exception(e)

        self.assertFalse(result.success)
        self.assertEqual(result.error_message, "Test error")
        self.assertIn("ValueError", result.errors)
        self.assertIn("traceback", result.metadata)
        self.assertIn("exception", result.metadata)

    def test_from_exception_with_override_message(self):
        """Test exception conversion with custom message."""
        try:
            raise ValueError("Original error")
        except Exception as e:
            result = OperationResult.from_exception(
                e,
                message="Custom error message",
                error_code="CUSTOM_001",
                http_status=500
            )

        self.assertEqual(result.error_message, "Custom error message")
        self.assertEqual(result.error_code, "CUSTOM_001")
        self.assertEqual(result.http_status, 500)

    def test_from_exception_without_traceback(self):
        """Test exception conversion without traceback."""
        try:
            raise ValueError("Test error")
        except Exception as e:
            result = OperationResult.from_exception(e, include_traceback=False)

        self.assertFalse(result.success)
        self.assertNotIn("traceback", result.metadata)

    def test_from_exception_with_metadata(self):
        """Test exception conversion with additional metadata."""
        try:
            raise ValueError("Test error")
        except Exception as e:
            result = OperationResult.from_exception(
                e,
                field="email",
                operation="validate"
            )

        self.assertEqual(result.metadata["field"], "email")
        self.assertEqual(result.metadata["operation"], "validate")


class TestFailBackwardCompatibility(FrappeTestCase):
    """Test cases for fail() backward compatibility with error= alias."""

    def test_fail_with_error_alias(self):
        """Test that fail() accepts error= as alias for message."""
        result = OperationResult.fail(error="Error via alias")

        self.assertFalse(result.success)
        self.assertEqual(result.error_message, "Error via alias")

    def test_fail_message_takes_precedence_over_error(self):
        """Test that message= takes precedence over error= alias."""
        result = OperationResult.fail(
            message="Message param",
            error="Error param"  # Should be ignored and go to metadata
        )

        self.assertEqual(result.error_message, "Message param")
        # error should NOT be in metadata since it was consumed
        self.assertNotIn("error", result.metadata)

    def test_fail_default_message(self):
        """Test that fail() uses default message when none provided."""
        result = OperationResult.fail()

        self.assertEqual(result.error_message, "Operation failed")

    def test_fail_with_http_status(self):
        """Test that fail() accepts http_status parameter."""
        result = OperationResult.fail(
            "Not found",
            http_status=404,
            error_code="NOT_FOUND"
        )

        self.assertEqual(result.http_status, 404)
        self.assertEqual(result.error_code, "NOT_FOUND")

    def test_fail_with_exception_and_traceback(self):
        """Test that fail() accepts exception and traceback parameters."""
        exc = ValueError("Test")
        result = OperationResult.fail(
            "Error occurred",
            exception=exc,
            traceback="fake traceback"
        )

        self.assertIn("exception", result.metadata)
        self.assertEqual(result.metadata["traceback"], "fake traceback")


class TestHttpStatusField(FrappeTestCase):
    """Test cases for the http_status field."""

    def test_http_status_in_dataclass(self):
        """Test that http_status is a first-class field."""
        result = OperationResult.fail(
            "Not found",
            http_status=404
        )

        self.assertEqual(result.http_status, 404)

    def test_http_status_in_to_dict_nested(self):
        """Test that http_status appears in nested to_dict output."""
        result = OperationResult.fail(
            "Bad request",
            http_status=400
        )
        result_dict = result.to_dict(nested=True)

        self.assertEqual(result_dict["error"]["http_status"], 400)

    def test_http_status_in_to_dict_flat(self):
        """Test that http_status appears in flat to_dict output."""
        result = OperationResult.fail(
            "Bad request",
            http_status=400
        )
        result_dict = result.to_dict(nested=False)

        self.assertEqual(result_dict["http_status"], 400)

    def test_http_status_defaults_to_none(self):
        """Test that http_status defaults to None."""
        result = OperationResult.fail("Error")
        self.assertIsNone(result.http_status)

        result2 = OperationResult.ok("data")
        self.assertIsNone(result2.http_status)


class TestWrapOperation(FrappeTestCase):
    """Test cases for the wrap_operation decorator."""

    def test_wrap_operation_success(self):
        """Test that wrap_operation wraps successful return values."""
        @wrap_operation
        def successful_function():
            return "success"

        result = successful_function()

        self.assertIsInstance(result, OperationResult)
        self.assertTrue(result.success)
        self.assertEqual(result.data, "success")

    def test_wrap_operation_no_double_wrap(self):
        """Test that wrap_operation doesn't double-wrap OperationResult."""
        @wrap_operation
        def returns_operation_result():
            return OperationResult.ok("inner result", inner=True)

        result = returns_operation_result()

        # Should NOT be nested - should pass through unchanged
        self.assertIsInstance(result, OperationResult)
        self.assertTrue(result.success)
        self.assertEqual(result.data, "inner result")
        self.assertEqual(result.metadata.get("inner"), True)
        # Should NOT have nested data
        self.assertNotIsInstance(result.data, OperationResult)

    def test_wrap_operation_preserves_failure_result(self):
        """Test that wrap_operation passes through failure OperationResult."""
        @wrap_operation
        def returns_failure():
            return OperationResult.fail("inner failure", error_code="INNER_001")

        result = returns_failure()

        self.assertFalse(result.success)
        self.assertEqual(result.error_message, "inner failure")
        self.assertEqual(result.error_code, "INNER_001")

    def test_wrap_operation_captures_exception(self):
        """Test that wrap_operation captures exceptions with traceback."""
        @wrap_operation
        def raises_exception():
            raise ValueError("Test exception")

        result = raises_exception()

        self.assertFalse(result.success)
        self.assertEqual(result.error_message, "Test exception")
        self.assertIn("ValueError", result.errors)
        self.assertIn("traceback", result.metadata)
        self.assertIn("exception", result.metadata)

    def test_wrap_operation_preserves_function_metadata(self):
        """Test that wrap_operation preserves function name and docstring."""
        @wrap_operation
        def my_documented_function():
            """This is the docstring."""
            return "result"

        self.assertEqual(my_documented_function.__name__, "my_documented_function")
        self.assertEqual(my_documented_function.__doc__, "This is the docstring.")


class TestToDictNestedSchema(FrappeTestCase):
    """Test cases for to_dict() nested schema stability."""

    def test_nested_schema_prevents_key_collision(self):
        """Test that nested schema prevents metadata from overwriting core keys."""
        # In flat schema, this could overwrite "success"
        result = OperationResult.ok("data", success="should not override")
        result_dict = result.to_dict(nested=True)

        # Core "success" should be True, not the metadata value
        self.assertTrue(result_dict["success"])
        # Metadata with collision key should be safe under "meta"
        self.assertEqual(result_dict["meta"]["success"], "should not override")

    def test_nested_schema_error_object_structure(self):
        """Test that nested schema has proper error object structure."""
        result = OperationResult.fail(
            "Error message",
            errors=["Detail 1", "Detail 2"],
            error_code="ERR_001",
            http_status=422,
            extra_context="value"
        )
        result_dict = result.to_dict(nested=True)

        # Error should be a structured object
        error_obj = result_dict["error"]
        self.assertEqual(error_obj["message"], "Error message")
        self.assertEqual(error_obj["errors"], ["Detail 1", "Detail 2"])
        self.assertEqual(error_obj["code"], "ERR_001")
        self.assertEqual(error_obj["http_status"], 422)

        # Extra metadata should be under "meta"
        self.assertEqual(result_dict["meta"]["extra_context"], "value")

    def test_nested_schema_success_has_no_error_key(self):
        """Test that successful results don't have error key in nested schema."""
        result = OperationResult.ok("data")
        result_dict = result.to_dict(nested=True)

        self.assertNotIn("error", result_dict)
        self.assertIn("data", result_dict)

    def test_nested_schema_empty_metadata(self):
        """Test that empty metadata doesn't create meta key."""
        result = OperationResult.ok("data")
        result_dict = result.to_dict(nested=True)

        # Empty metadata should not create "meta" key
        self.assertNotIn("meta", result_dict)


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
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestOperationResultException))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestFromException))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestFailBackwardCompatibility))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestHttpStatusField))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestWrapOperation))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestToDictNestedSchema))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Return exit code
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_tests())
