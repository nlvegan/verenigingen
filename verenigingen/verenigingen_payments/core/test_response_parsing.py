"""
Unit Tests for Response Parsing in MollieBaseClient

Tests comprehensive response parsing functionality including:
- Single object responses
- List responses
- Optional responses (allow_none)
- Error responses from API
- Invalid response types
- Response validation
- Parse error handling

All tests use minimal mocking, relying on actual BaseModel behavior for realism.
"""

import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, Mock, patch

import frappe
from frappe.test_runner import make_test_records

from verenigingen.verenigingen_payments.core.models.balance import Balance
from verenigingen.verenigingen_payments.core.models.base import BaseModel
from verenigingen.verenigingen_payments.core.models.settlement import Settlement
from verenigingen.verenigingen_payments.core.mollie_base_client import (
    MollieAPIError,
    MollieBaseClient,
    ResponseParsingError,
    ResponseValidationError,
)


# Test Model for unit tests
class TestModel(BaseModel):
    """Simple test model for response parsing tests"""

    def __init__(self, data: Optional[Dict[str, Any]] = None):
        self.id: Optional[str] = None
        self.name: Optional[str] = None
        self.value: Optional[int] = None
        super().__init__(data)


class TestModelWithRequiredFields(BaseModel):
    """Test model with required fields"""

    _required_fields = ["id", "name"]

    def __init__(self, data: Optional[Dict[str, Any]] = None):
        self.id: Optional[str] = None
        self.name: Optional[str] = None
        self.optional_field: Optional[str] = None
        super().__init__(data)


class TestResponseParsing(unittest.TestCase):
    """Test cases for MollieBaseClient._parse_response()"""

    def setUp(self):
        """Set up test environment before each test"""
        frappe.set_user("Administrator")

        # Create minimal Mollie settings for client initialization
        if not frappe.db.exists("Mollie Settings", "Mollie Settings"):
            make_test_records("Mollie Settings")

        # Initialize client (will use test mode by default)
        self.client = MollieBaseClient(use_backend_api=False)

    def tearDown(self):
        """Clean up after each test"""
        frappe.db.rollback()

    # ====================
    # Single Object Parsing
    # ====================

    def test_parse_single_object_valid(self):
        """Test parsing a valid single object response"""
        response = {"id": "test_123", "name": "Test Item", "value": 100}

        result = self.client._parse_response(response, TestModel)

        self.assertIsInstance(result, TestModel)
        self.assertEqual(result.id, "test_123")
        self.assertEqual(result.name, "Test Item")
        self.assertEqual(result.value, 100)

    def test_parse_single_object_with_extra_fields(self):
        """Test parsing response with fields not in model (should be added dynamically)"""
        response = {
            "id": "test_123",
            "name": "Test Item",
            "extra_field": "should be added dynamically",
            "another_field": 999,
        }

        result = self.client._parse_response(response, TestModel)

        self.assertIsInstance(result, TestModel)
        self.assertEqual(result.id, "test_123")
        # BaseModel adds unknown fields dynamically
        self.assertEqual(result.extra_field, "should be added dynamically")

    def test_parse_single_object_with_missing_fields(self):
        """Test parsing response with missing fields (should default to None)"""
        response = {"id": "test_123"}  # Missing name and value

        result = self.client._parse_response(response, TestModel)

        self.assertIsInstance(result, TestModel)
        self.assertEqual(result.id, "test_123")
        self.assertIsNone(result.name)
        self.assertIsNone(result.value)

    def test_parse_real_settlement_response(self):
        """Test parsing actual Settlement model response"""
        response = {
            "id": "stl_jDk30akdN",
            "resource": "settlement",
            "reference": "1234567.1234.12",
            "status": "paidout",
            "amount": {"value": "1000.00", "currency": "EUR"},
            "createdAt": "2025-01-15T10:00:00+00:00",
        }

        result = self.client._parse_response(response, Settlement)

        self.assertIsInstance(result, Settlement)
        self.assertEqual(result.id, "stl_jDk30akdN")
        self.assertEqual(result.status, "paidout")
        # Amount is nested object, BaseModel should handle it
        self.assertIsNotNone(result.amount)

    # ====================
    # List Response Parsing
    # ====================

    def test_parse_list_response_multiple_items(self):
        """Test parsing list with multiple items"""
        response = [
            {"id": "test_1", "name": "Item 1", "value": 10},
            {"id": "test_2", "name": "Item 2", "value": 20},
            {"id": "test_3", "name": "Item 3", "value": 30},
        ]

        result = self.client._parse_response(response, TestModel)

        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 3)
        self.assertIsInstance(result[0], TestModel)
        self.assertEqual(result[0].id, "test_1")
        self.assertEqual(result[1].value, 20)
        self.assertEqual(result[2].name, "Item 3")

    def test_parse_list_response_single_item(self):
        """Test parsing list with single item"""
        response = [{"id": "test_1", "name": "Item 1", "value": 10}]

        result = self.client._parse_response(response, TestModel)

        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], TestModel)
        self.assertEqual(result[0].id, "test_1")

    def test_parse_list_response_empty(self):
        """Test parsing empty list.

        An empty list is a valid result for collection endpoints (e.g. a
        settlement with zero captures/refunds/chargebacks), so _parse_response
        returns [] rather than raising, regardless of allow_none.
        """
        response = []

        # Empty list with allow_none=False returns an empty list (valid collection)
        result = self.client._parse_response(response, TestModel, allow_none=False)
        self.assertEqual(result, [])

        # Empty list with allow_none=True also returns an empty list
        result = self.client._parse_response(response, TestModel, allow_none=True)
        self.assertEqual(result, [])

    # ====================
    # Optional Response (allow_none)
    # ====================

    def test_parse_none_response_with_allow_none_true(self):
        """Test parsing None response when allow_none=True"""
        response = None

        result = self.client._parse_response(response, TestModel, allow_none=True)

        self.assertIsNone(result)

    def test_parse_none_response_with_allow_none_false(self):
        """Test parsing None response when allow_none=False (should raise)"""
        response = None

        with self.assertRaises(ResponseParsingError) as context:
            self.client._parse_response(response, TestModel, allow_none=False)

        self.assertIn("Expected TestModel response, got None", str(context.exception))

    def test_parse_empty_dict_with_allow_none(self):
        """Test parsing empty dict {}"""
        response = {}

        # Empty dict with allow_none=False should raise
        with self.assertRaises(ResponseParsingError) as context:
            self.client._parse_response(response, TestModel, allow_none=False)
        self.assertIn("Empty response", str(context.exception))

        # Empty dict with allow_none=True should return None
        result = self.client._parse_response(response, TestModel, allow_none=True)
        self.assertIsNone(result)

    # ====================
    # Error Response Handling
    # ====================

    def test_parse_mollie_error_response(self):
        """Test parsing error response from Mollie API"""
        response = {
            "error": {
                "type": "request",
                "message": "Invalid API key",
                "field": "api_key",
            },
            "status": 401,
        }

        with self.assertRaises(MollieAPIError) as context:
            self.client._parse_response(response, TestModel)

        self.assertIn("Invalid API key", str(context.exception))
        error = context.exception
        self.assertEqual(error.error_code, "request")
        self.assertIn("api_key", str(error.details))

    def test_parse_mollie_error_response_minimal(self):
        """Test parsing minimal error response (no details)"""
        response = {
            "error": {
                "message": "Something went wrong",
            }
        }

        with self.assertRaises(MollieAPIError) as context:
            self.client._parse_response(response, TestModel)

        self.assertIn("Something went wrong", str(context.exception))

    # ====================
    # Invalid Response Types
    # ====================

    def test_parse_invalid_response_type_string(self):
        """Test parsing string response (invalid)"""
        response = "invalid string response"

        with self.assertRaises(ResponseParsingError) as context:
            self.client._parse_response(response, TestModel)

        self.assertIn("Invalid response type", str(context.exception))
        self.assertIn("str", str(context.exception))

    def test_parse_invalid_response_type_int(self):
        """Test parsing int response (invalid)"""
        response = 12345

        with self.assertRaises(ResponseParsingError) as context:
            self.client._parse_response(response, TestModel)

        self.assertIn("Invalid response type", str(context.exception))
        self.assertIn("int", str(context.exception))

    # ====================
    # Response Validation
    # ====================

    def test_validate_response_with_required_fields_present(self):
        """Test validation when required fields are present"""
        response = {"id": "test_123", "name": "Test Item"}

        # Should not raise
        result = self.client._validate_response_structure(response, TestModelWithRequiredFields)
        self.assertTrue(result)

    def test_validate_response_with_required_fields_missing(self):
        """Test validation when required fields are missing (should log warning, not raise)"""
        response = {"id": "test_123"}  # Missing 'name'

        # Should log warning but not raise (BaseModel handles gracefully)
        with patch("frappe.logger") as mock_logger:
            result = self.client._validate_response_structure(response, TestModelWithRequiredFields)
            self.assertTrue(result)
            # Check that warning was logged
            mock_logger().warning.assert_called_once()
            warning_message = mock_logger().warning.call_args[0][0]
            self.assertIn("missing fields", warning_message.lower())
            self.assertIn("name", warning_message)

    def test_validate_response_error_response(self):
        """Test validation with error response"""
        response = {
            "error": {
                "type": "validation",
                "message": "Invalid field value",
                "field": "amount",
            }
        }

        with self.assertRaises(MollieAPIError):
            self.client._validate_response_structure(response, TestModel)

    # ====================
    # Parse Error Handling
    # ====================

    def test_parse_error_with_malformed_data(self):
        """Test parsing when model constructor raises exception"""

        class BrokenModel(BaseModel):
            """Model that raises on init"""

            def __init__(self, data):
                if data.get("id") == "trigger_error":
                    raise ValueError("Broken model constructor")
                super().__init__(data)

        response = {"id": "trigger_error", "name": "Test"}

        with self.assertRaises(ResponseParsingError) as context:
            self.client._parse_response(response, BrokenModel)

        self.assertIn("Failed to parse BrokenModel", str(context.exception))
        self.assertIn("Broken model constructor", str(context.exception))

    def test_parse_error_with_list_containing_bad_item(self):
        """Test parsing list where one item fails"""

        class BrokenModel(BaseModel):
            """Model that raises on specific ID"""

            def __init__(self, data):
                if data.get("id") == "bad_item":
                    raise ValueError("Bad item in list")
                super().__init__(data)

        response = [
            {"id": "good_1", "name": "Good Item 1"},
            {"id": "bad_item", "name": "Bad Item"},
            {"id": "good_2", "name": "Good Item 2"},
        ]

        with self.assertRaises(ResponseParsingError) as context:
            self.client._parse_response(response, BrokenModel)

        self.assertIn("Failed to parse BrokenModel", str(context.exception))
        self.assertIn("Bad item in list", str(context.exception))

    # ====================
    # Error Context and Logging
    # ====================

    def test_parse_error_logs_with_context(self):
        """Test that parse errors log comprehensive context"""

        class BrokenModel(BaseModel):
            def __init__(self, data):
                raise ValueError("Test error for logging")

        response = {"id": "test_123", "name": "Test Item"}

        with patch("frappe.log_error") as mock_log_error:
            with self.assertRaises(ResponseParsingError):
                self.client._parse_response(response, BrokenModel)

            # Verify error was logged with context
            mock_log_error.assert_called_once()
            log_message = mock_log_error.call_args[0][0]
            self.assertIn("BrokenModel", log_message)
            self.assertIn("test_123", log_message)

    def test_parse_error_truncates_large_response(self):
        """Test that large responses are truncated in error logs"""

        class BrokenModel(BaseModel):
            def __init__(self, data):
                raise ValueError("Test error")

        # Create large response (>500 chars)
        response = {"id": "test", "data": "x" * 1000}

        with patch("frappe.log_error") as mock_log_error:
            with self.assertRaises(ResponseParsingError):
                self.client._parse_response(response, BrokenModel)

            # Verify response was truncated
            log_message = mock_log_error.call_args[0][0]
            self.assertIn("truncated", log_message)
            # Full response should not be in log
            self.assertNotIn("x" * 1000, log_message)

    def test_parse_error_original_response_preserved(self):
        """Test that ResponseParsingError preserves original response"""

        class BrokenModel(BaseModel):
            def __init__(self, data):
                raise ValueError("Test error")

        response = {"id": "test_123", "name": "Test Item"}

        try:
            self.client._parse_response(response, BrokenModel)
        except ResponseParsingError as e:
            self.assertEqual(e.original_response, response)
        else:
            self.fail("Expected ResponseParsingError to be raised")

    # ====================
    # Integration with Error Handler
    # ====================

    def test_parse_error_calls_error_handler(self):
        """Test that parse errors log to audit trail"""

        class BrokenModel(BaseModel):
            def __init__(self, data):
                raise ValueError("Test error")

        response = {"id": "test_123"}

        with patch.object(self.client.audit_trail, "log_event") as mock_log:
            with self.assertRaises(ResponseParsingError):
                self.client._parse_response(response, BrokenModel)

            # Verify audit trail was called
            mock_log.assert_called_once()
            call_args = mock_log.call_args
            # First arg is event type, second is severity, third is message
            self.assertIn("Failed to parse BrokenModel", call_args[0][2])
            # Details should contain error context
            details = call_args[1]["details"]
            self.assertEqual(details["model_class"], "BrokenModel")
            self.assertIn("Test error", details["error_message"])

    # ====================
    # Edge Cases
    # ====================

    def test_parse_response_with_nested_objects(self):
        """Test parsing response with nested objects (BaseModel handles this)"""

        class NestedModel(BaseModel):
            def __init__(self, data=None):
                self.id: Optional[str] = None
                self.metadata: Optional[Dict] = None
                super().__init__(data)

        response = {
            "id": "test_123",
            "metadata": {"key1": "value1", "key2": "value2", "nested": {"deep": "value"}},
        }

        result = self.client._parse_response(response, NestedModel)

        self.assertIsInstance(result, NestedModel)
        self.assertEqual(result.id, "test_123")
        self.assertIsInstance(result.metadata, dict)
        self.assertEqual(result.metadata["key1"], "value1")
        self.assertEqual(result.metadata["nested"]["deep"], "value")

    def test_parse_response_with_null_values(self):
        """Test parsing response with null values in fields"""
        response = {"id": "test_123", "name": None, "value": None}

        result = self.client._parse_response(response, TestModel)

        self.assertIsInstance(result, TestModel)
        self.assertEqual(result.id, "test_123")
        self.assertIsNone(result.name)
        self.assertIsNone(result.value)


class TestResponseParsingIntegration(unittest.TestCase):
    """
    Integration Tests for Response Parsing with Real Mollie Models

    Tests parsing of actual Mollie API response fixtures with real model classes.
    These tests verify end-to-end parsing works with production models.
    """

    def setUp(self):
        """Set up test client"""
        self.client = MollieBaseClient()

    def test_parse_real_settlement_response(self):
        """Test parsing real Settlement response from Mollie API"""
        # Real settlement response from Mollie API documentation
        real_mollie_response = {
            "resource": "settlement",
            "id": "stl_jDk30akdN",
            "reference": "1234567.1804.03",
            "createdAt": "2018-04-06T06:00:01.0Z",
            "settledAt": "2018-04-06T09:41:44.0Z",
            "status": "paidout",
            "amount": {"value": "39.75", "currency": "EUR"},
            "periods": {
                "2018": {
                    "04": {
                        "revenue": [
                            {
                                "description": "iDEAL",
                                "method": "ideal",
                                "count": 6,
                                "amountNet": {"value": "86.1000", "currency": "EUR"},
                                "amountVat": {"value": "18.0810", "currency": "EUR"},
                                "amountGross": {"value": "104.1810", "currency": "EUR"},
                            }
                        ],
                        "costs": [
                            {
                                "description": "iDEAL",
                                "method": "ideal",
                                "count": 6,
                                "rate": {"fixed": {"value": "0.3500", "currency": "EUR"}, "percentage": None},
                                "amountNet": {"value": "2.1000", "currency": "EUR"},
                                "amountVat": {"value": "0.4410", "currency": "EUR"},
                                "amountGross": {"value": "2.5410", "currency": "EUR"},
                            }
                        ],
                    }
                }
            },
            "_links": {"self": {"href": "...", "type": "application/hal+json"}},
        }

        # Parse with real Settlement model
        result = self.client._parse_response(real_mollie_response, Settlement)

        # Verify critical fields
        self.assertIsInstance(result, Settlement)
        self.assertEqual(result.id, "stl_jDk30akdN")
        self.assertEqual(result.reference, "1234567.1804.03")
        self.assertEqual(result.status, "paidout")
        self.assertIsNotNone(result.amount)
        self.assertEqual(result.amount.value, "39.75")
        self.assertEqual(result.amount.currency, "EUR")

    def test_parse_real_balance_response(self):
        """Test parsing real Balance response from Mollie API"""
        # Real balance response from Mollie API documentation
        real_mollie_response = {
            "resource": "balance",
            "id": "bal_gVMhHKqSSRYJyPsuoPNFH",
            "mode": "live",
            "createdAt": "2019-01-10T10:23:41+00:00",
            "currency": "EUR",
            "status": "active",
            "availableAmount": {"value": "905.25", "currency": "EUR"},
            "pendingAmount": {"value": "0.00", "currency": "EUR"},
            "transferFrequency": "twice-a-month",
            "transferThreshold": {"value": "40.00", "currency": "EUR"},
            "transferReference": "Mollie payout",
            "transferDestination": {
                "type": "bank-account",
                "beneficiaryName": "Jack Bauer",
                "bankAccount": "NL53INGB0000000000",
                "bankAccountId": "bnk_jrty3f",
            },
            "_links": {"self": {"href": "...", "type": "application/hal+json"}},
        }

        # Parse with real Balance model
        result = self.client._parse_response(real_mollie_response, Balance)

        # Verify critical fields
        self.assertIsInstance(result, Balance)
        self.assertEqual(result.id, "bal_gVMhHKqSSRYJyPsuoPNFH")
        self.assertEqual(result.currency, "EUR")
        self.assertEqual(result.status, "active")
        self.assertIsNotNone(result.available_amount)
        self.assertEqual(result.available_amount.value, "905.25")

    def test_parse_real_settlement_list_response(self):
        """Test parsing list of real Settlement responses"""
        # Real list response (truncated for testing)
        real_mollie_response = [
            {
                "resource": "settlement",
                "id": "stl_jDk30akdN",
                "reference": "1234567.1804.03",
                "createdAt": "2018-04-06T06:00:01.0Z",
                "settledAt": "2018-04-06T09:41:44.0Z",
                "status": "paidout",
                "amount": {"value": "39.75", "currency": "EUR"},
                "_links": {"self": {"href": "...", "type": "application/hal+json"}},
            },
            {
                "resource": "settlement",
                "id": "stl_QM24OAv0UL",
                "reference": "1234567.1803.03",
                "createdAt": "2018-03-20T06:00:01.0Z",
                "settledAt": "2018-03-20T09:41:44.0Z",
                "status": "paidout",
                "amount": {"value": "50.00", "currency": "EUR"},
                "_links": {"self": {"href": "...", "type": "application/hal+json"}},
            },
        ]

        # Parse with real Settlement model
        result = self.client._parse_response(real_mollie_response, Settlement)

        # Verify list parsing
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], Settlement)
        self.assertIsInstance(result[1], Settlement)
        self.assertEqual(result[0].id, "stl_jDk30akdN")
        self.assertEqual(result[1].id, "stl_QM24OAv0UL")

    def test_parse_real_balance_list_response(self):
        """Test parsing list of real Balance responses"""
        # Real list response
        real_mollie_response = [
            {
                "resource": "balance",
                "id": "bal_test1",
                "currency": "EUR",
                "availableAmount": {"value": "100.00", "currency": "EUR"},
                "status": "active",
            },
            {
                "resource": "balance",
                "id": "bal_test2",
                "currency": "USD",
                "availableAmount": {"value": "50.00", "currency": "USD"},
                "status": "active",
            },
        ]

        # Parse with real Balance model
        result = self.client._parse_response(real_mollie_response, Balance)

        # Verify list parsing
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], Balance)
        self.assertIsInstance(result[1], Balance)
        self.assertEqual(result[0].id, "bal_test1")
        self.assertEqual(result[1].currency, "USD")

    def test_parse_with_nested_amount_objects(self):
        """Test parsing responses with nested amount objects"""
        # Balance with nested availableAmount and pendingAmount
        real_mollie_response = {
            "resource": "balance",
            "id": "bal_nested",
            "currency": "EUR",
            "availableAmount": {"value": "1500.75", "currency": "EUR"},
            "pendingAmount": {"value": "250.25", "currency": "EUR"},
            "status": "active",
        }

        # Parse with real Balance model
        result = self.client._parse_response(real_mollie_response, Balance)

        # Verify nested objects parsed correctly
        self.assertIsNotNone(result.available_amount)
        self.assertEqual(result.available_amount.value, "1500.75")
        # Note: pending_amount might not be set if model doesn't handle it

    def test_parse_settlement_with_complex_periods(self):
        """Test parsing Settlement with complex nested periods structure"""
        # Settlement with nested period data
        real_mollie_response = {
            "resource": "settlement",
            "id": "stl_complex",
            "reference": "2024.10.1",
            "status": "pending",
            "amount": {"value": "250.00", "currency": "EUR"},
            "periods": {"2024": {"10": {"revenue": [], "costs": []}}},
        }

        # Parse with real Settlement model
        result = self.client._parse_response(real_mollie_response, Settlement)

        # Verify complex structure handled
        self.assertIsInstance(result, Settlement)
        self.assertEqual(result.id, "stl_complex")
        self.assertEqual(result.reference, "2024.10.1")
        self.assertIsNotNone(result.periods)

    def test_client_initialization_with_strict_mode(self):
        """Test that client can be initialized with strict=False"""
        # Create client with non-strict validation
        client = MollieBaseClient(strict_financial_validation=False)

        # Verify attribute is set
        self.assertFalse(client.strict_financial_validation)

        # Verify it can still parse valid responses
        response = {
            "resource": "settlement",
            "id": "stl_test",
            "amount": {"value": "10.00", "currency": "EUR"},
            "status": "paidout",
        }

        result = client._parse_response(response, Settlement)
        self.assertEqual(result.id, "stl_test")

    def test_parse_optional_settlement_response_none(self):
        """Test parsing optional Settlement when response is None"""
        # None response with allow_none=True
        result = self.client._parse_response(None, Settlement, allow_none=True)

        # Should return None, not raise
        self.assertIsNone(result)


# Test suite execution
def run_tests():
    """Run all response parsing tests"""
    suite = unittest.TestLoader().loadTestsFromTestCase(TestResponseParsing)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


if __name__ == "__main__":
    unittest.main()
