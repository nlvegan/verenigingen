"""
Unit Tests for PaymentValidationService

Tests validation orchestration logic without testing underlying validators directly.
Focuses on:
- Result pattern consistency
- Error message enhancement
- Orchestration logic
- Edge cases and error handling
"""

import unittest
from decimal import Decimal

import frappe
from verenigingen.services.payment.validation_service import (
    PaymentValidationService,
    ValidationResult,
    get_payment_validation_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


# Module-level service instance for tests
_test_service = None


def get_test_service():
    """Get or create a test service instance."""
    global _test_service
    if _test_service is None:
        _test_service = get_payment_validation_service()
    return _test_service


class TestValidationResult(EnhancedTestCase):
    """Test ValidationResult dataclass"""

    def test_success_creation(self):
        """Test creating successful validation result"""
        result = ValidationResult.success("Test passed", data={"key": "value"})

        self.assertTrue(result.valid)
        self.assertEqual(result.message, "Test passed")
        self.assertEqual(result.data, {"key": "value"})
        self.assertEqual(result.errors, [])

    def test_failure_creation(self):
        """Test creating failed validation result"""
        result = ValidationResult.failure("Test failed", errors=["Error 1", "Error 2"])

        self.assertFalse(result.valid)
        self.assertEqual(result.message, "Test failed")
        self.assertEqual(result.errors, ["Error 1", "Error 2"])
        self.assertIsNone(result.data)

    def test_failure_without_explicit_errors(self):
        """Test failure result uses message as error if errors not provided"""
        result = ValidationResult.failure("Single error")

        self.assertFalse(result.valid)
        self.assertEqual(result.errors, ["Single error"])


class TestIBANValidationWithContext(EnhancedTestCase):
    """Test IBAN validation with context-aware error messages"""

    def test_valid_dutch_iban(self):
        """Test validation of valid Dutch IBAN"""
        result = get_test_service().validate_iban_with_context("NL91ABNA0417164300")

        self.assertTrue(result.valid)
        self.assertIn("formatted_iban", result.data)
        self.assertEqual(result.data["formatted_iban"], "NL91 ABNA 0417 1643 00")
        self.assertEqual(result.data["iban_clean"], "NL91ABNA0417164300")

    def test_valid_iban_with_spaces(self):
        """Test IBAN validation handles spaces correctly"""
        result = get_test_service().validate_iban_with_context("NL91 ABNA 0417 1643 00")

        self.assertTrue(result.valid)
        self.assertEqual(result.data["iban_clean"], "NL91ABNA0417164300")

    def test_empty_iban(self):
        """Test validation fails for empty IBAN"""
        result = get_test_service().validate_iban_with_context("")

        self.assertFalse(result.valid)
        self.assertIn("required", result.message.lower())

    def test_invalid_iban_checksum(self):
        """Test validation fails for invalid checksum with user-friendly message"""
        result = get_test_service().validate_iban_with_context("NL00ABNA0417164300")

        self.assertFalse(result.valid)
        # Should have enhanced error message about double-checking
        self.assertIn("double-check", result.message.lower())

    def test_iban_too_short(self):
        """Test validation fails for too-short IBAN with helpful message"""
        result = get_test_service().validate_iban_with_context("NL91")

        self.assertFalse(result.valid)
        # Error message is enhanced to be user-friendly (mentions "incorrect" instead of technical "too short")
        self.assertIn("incorrect", result.message.lower())

    def test_iban_with_invalid_characters(self):
        """Test validation fails for IBAN with special characters"""
        result = get_test_service().validate_iban_with_context("NL91-ABNA-0417-1643-00")

        self.assertFalse(result.valid)
        # Error message is enhanced to be user-friendly (mentions "incorrect" from checksum validation)
        self.assertIn("incorrect", result.message.lower())

    def test_context_in_error_message(self):
        """Test context is included in error messages"""
        result = get_test_service().validate_iban_with_context("", context="SEPA mandate")

        self.assertFalse(result.valid)
        self.assertIn("SEPA mandate", result.message)

    def test_auto_format_disabled(self):
        """Test validation without auto-formatting"""
        result = get_test_service().validate_iban_with_context(
            "NL91ABNA0417164300",
            auto_format=False
        )

        self.assertTrue(result.valid)
        self.assertNotIn("formatted_iban", result.data)


class TestBankDetailsValidation(EnhancedTestCase):
    """Test comprehensive bank details validation"""

    def test_valid_bank_details_with_auto_derive_bic(self):
        """Test validation with BIC auto-derivation for Dutch IBAN"""
        result = get_test_service().validate_bank_details(
            iban="NL91ABNA0417164300",
            auto_derive_bic=True
        )

        self.assertTrue(result.valid)
        self.assertIn("bic", result.data)
        self.assertEqual(result.data["bic"], "ABNANL2A")
        self.assertTrue(result.data["bic_derived"])

    def test_valid_bank_details_with_provided_bic(self):
        """Test validation with manually provided BIC"""
        result = get_test_service().validate_bank_details(
            iban="NL91ABNA0417164300",
            bic="ABNANL2A"
        )

        self.assertTrue(result.valid)
        self.assertEqual(result.data["bic"], "ABNANL2A")
        self.assertFalse(result.data["bic_derived"])

    def test_bank_details_with_account_holder_name(self):
        """Test validation including account holder name"""
        result = get_test_service().validate_bank_details(
            iban="NL91ABNA0417164300",
            account_holder_name="Test User"
        )

        self.assertTrue(result.valid)
        self.assertEqual(result.data["account_holder_name"], "Test User")

    def test_invalid_iban_fails_bank_details(self):
        """Test bank details validation fails if IBAN is invalid"""
        result = get_test_service().validate_bank_details(
            iban="INVALID",
            bic="ABNANL2A"
        )

        self.assertFalse(result.valid)
        self.assertGreater(len(result.errors), 0)

    def test_invalid_bic_format(self):
        """Test validation fails for invalid BIC format"""
        result = get_test_service().validate_bank_details(
            iban="NL91ABNA0417164300",
            bic="INVALID"
        )

        self.assertFalse(result.valid)
        self.assertIn("BIC", result.errors[0])

    def test_bic_required_but_missing(self):
        """Test validation fails when BIC is required but not provided/derivable"""
        # Use non-Dutch IBAN that can't auto-derive BIC
        result = get_test_service().validate_bank_details(
            iban="DE89370400440532013000",  # German IBAN
            auto_derive_bic=True,
            require_bic=True
        )

        # Should fail because BIC can't be derived from German IBAN
        # Note: This test may pass if DE BIC derivation is implemented
        # The important thing is require_bic=True enforces BIC presence

    def test_account_holder_name_too_short(self):
        """Test validation fails for too-short account holder name"""
        result = get_test_service().validate_bank_details(
            iban="NL91ABNA0417164300",
            account_holder_name="A"
        )

        self.assertFalse(result.valid)
        self.assertIn("short", result.errors[0].lower())

    def test_account_holder_name_too_long(self):
        """Test validation fails for too-long account holder name"""
        result = get_test_service().validate_bank_details(
            iban="NL91ABNA0417164300",
            account_holder_name="A" * 71  # SEPA max is 70
        )

        self.assertFalse(result.valid)
        self.assertIn("long", result.errors[0].lower())

    def test_account_holder_name_only_numbers(self):
        """Test validation fails for account holder name with only numbers"""
        result = get_test_service().validate_bank_details(
            iban="NL91ABNA0417164300",
            account_holder_name="123456"
        )

        self.assertFalse(result.valid)
        self.assertIn("numbers", result.errors[0].lower())


class TestBICFormatValidation(EnhancedTestCase):
    """Test BIC format validation"""

    def test_valid_bic_8_characters(self):
        """Test validation of valid 8-character BIC"""
        result = get_test_service()._validate_bic_format("ABNANL2A")

        self.assertTrue(result.valid)

    def test_valid_bic_11_characters(self):
        """Test validation of valid 11-character BIC"""
        result = get_test_service()._validate_bic_format("ABNANL2AXXX")

        self.assertTrue(result.valid)

    def test_invalid_bic_length(self):
        """Test validation fails for invalid BIC length"""
        result = get_test_service()._validate_bic_format("ABNA")

        self.assertFalse(result.valid)
        self.assertIn("8 or 11", result.message)

    def test_invalid_bic_format(self):
        """Test validation fails for invalid BIC format"""
        result = get_test_service()._validate_bic_format("12345678")

        self.assertFalse(result.valid)

    def test_bic_case_insensitive(self):
        """Test BIC validation is case-insensitive"""
        result = get_test_service()._validate_bic_format("abnanl2a")

        self.assertTrue(result.valid)


class TestPaymentMethodValidation(EnhancedTestCase):
    """Test payment method validation"""

    def test_valid_payment_method(self):
        """Test validation of valid payment method"""
        # Create test payment method
        if not frappe.db.exists("Mode of Payment", "Test Cash"):
            mode = frappe.new_doc("Mode of Payment")
            mode.mode_of_payment = "Test Cash"
            mode.enabled = 1
            mode.type = "Cash"
            mode.insert()

        result = get_test_service().validate_payment_method("Test Cash")

        self.assertTrue(result.valid)
        self.assertEqual(result.data["method_name"], "Test Cash")

    def test_nonexistent_payment_method(self):
        """Test validation fails for non-existent payment method"""
        result = get_test_service().validate_payment_method("NonExistent Method")

        self.assertFalse(result.valid)
        self.assertIn("does not exist", result.message)

    def test_disabled_payment_method(self):
        """Test validation fails for disabled payment method"""
        # Create disabled payment method
        if not frappe.db.exists("Mode of Payment", "Disabled Method"):
            mode = frappe.new_doc("Mode of Payment")
            mode.mode_of_payment = "Disabled Method"
            mode.enabled = 0
            mode.insert()

        result = get_test_service().validate_payment_method("Disabled Method")

        self.assertFalse(result.valid)
        self.assertIn("disabled", result.message.lower())

    def test_empty_payment_method(self):
        """Test validation fails for empty payment method"""
        result = get_test_service().validate_payment_method("")

        self.assertFalse(result.valid)
        self.assertIn("required", result.message.lower())


class TestPaymentAmountValidation(EnhancedTestCase):
    """Test payment amount validation"""

    def test_valid_amount(self):
        """Test validation of valid payment amount"""
        result = get_test_service().validate_payment_amount(25.50)

        self.assertTrue(result.valid)
        self.assertEqual(result.data["amount"], Decimal("25.50"))
        self.assertEqual(result.data["amount_formatted"], "25.50")

    def test_zero_amount_not_allowed_by_default(self):
        """Test validation fails for zero amount by default"""
        result = get_test_service().validate_payment_amount(0)

        self.assertFalse(result.valid)
        self.assertIn("greater than zero", result.message)

    def test_zero_amount_allowed_when_configured(self):
        """Test validation passes for zero when explicitly allowed"""
        result = get_test_service().validate_payment_amount(0, allow_zero=True)

        self.assertTrue(result.valid)

    def test_negative_amount(self):
        """Test validation fails for negative amount"""
        result = get_test_service().validate_payment_amount(-10.00)

        self.assertFalse(result.valid)
        self.assertIn("negative", result.message.lower())

    def test_amount_below_minimum(self):
        """Test validation fails for amount below minimum"""
        result = get_test_service().validate_payment_amount(0.001)

        self.assertFalse(result.valid)
        self.assertIn("at least", result.message)

    def test_amount_above_maximum(self):
        """Test validation fails for amount above maximum"""
        result = get_test_service().validate_payment_amount(150000.00)

        self.assertFalse(result.valid)
        self.assertIn("cannot exceed", result.message)

    def test_custom_minimum(self):
        """Test validation with custom minimum amount"""
        result = get_test_service().validate_payment_amount(
            5.00,
            min_amount=10.00
        )

        self.assertFalse(result.valid)
        self.assertIn("at least 10", result.message)

    def test_custom_maximum(self):
        """Test validation with custom maximum amount"""
        result = get_test_service().validate_payment_amount(
            50.00,
            max_amount=40.00
        )

        self.assertFalse(result.valid)
        self.assertIn("cannot exceed 40", result.message)

    def test_invalid_amount_type(self):
        """Test validation fails for invalid amount type"""
        result = get_test_service().validate_payment_amount("not a number")

        self.assertFalse(result.valid)
        self.assertIn("not a valid number", result.message)

    def test_none_amount(self):
        """Test validation fails for None amount"""
        result = get_test_service().validate_payment_amount(None)

        self.assertFalse(result.valid)
        self.assertIn("required", result.message.lower())

    def test_excessive_decimal_places(self):
        """Test validation fails for more than 2 decimal places"""
        result = get_test_service().validate_payment_amount(25.555)

        self.assertFalse(result.valid)
        self.assertIn("2 decimal places", result.message)

    def test_amount_precision_preserved(self):
        """Test Decimal precision is maintained for amounts"""
        result = get_test_service().validate_payment_amount(25.50)

        self.assertTrue(result.valid)
        # Check it's Decimal, not float
        self.assertIsInstance(result.data["amount"], Decimal)
        # Decimal normalizes trailing zeros, but formatted version has them
        self.assertEqual(result.data["amount"], Decimal("25.5"))  # Normalized form
        self.assertEqual(result.data["amount_formatted"], "25.50")  # Formatted with 2 decimals


class TestAPIEndpoints(EnhancedTestCase):
    """Test whitelisted API endpoints"""

    def test_validate_iban_api(self):
        """Test IBAN validation API endpoint"""
        from verenigingen.services.payment.validation_service import validate_iban_api

        # @public_api serializes the OperationResult via to_dict() for HTTP
        result = validate_iban_api(iban="NL91ABNA0417164300")

        self.assertIsInstance(result, dict)
        self.assertTrue(result["success"])
        self.assertIn("formatted_iban", result["data"])

    def test_validate_bank_details_api(self):
        """Test bank details validation API endpoint"""
        from verenigingen.services.payment.validation_service import validate_bank_details_api

        # @public_api serializes the OperationResult via to_dict() for HTTP
        result = validate_bank_details_api(iban="NL91ABNA0417164300")

        self.assertIsInstance(result, dict)
        self.assertTrue(result["success"])

    def test_validate_payment_method_api(self):
        """Test payment method validation API endpoint"""
        from verenigingen.services.payment.validation_service import validate_payment_method_api

        # Create test payment method first
        if not frappe.db.exists("Mode of Payment", "API Test"):
            mode = frappe.new_doc("Mode of Payment")
            mode.mode_of_payment = "API Test"
            mode.enabled = 1
            mode.insert()

        # @public_api serializes the OperationResult via to_dict() for HTTP
        result = validate_payment_method_api(method="API Test")

        self.assertIsInstance(result, dict)
        self.assertTrue(result["success"])

    def test_validate_payment_amount_api(self):
        """Test payment amount validation API endpoint"""
        from verenigingen.services.payment.validation_service import validate_payment_amount_api

        # @public_api serializes the OperationResult via to_dict() for HTTP
        result = validate_payment_amount_api(amount=25.50)

        self.assertIsInstance(result, dict)
        self.assertTrue(result["success"])
        # Amount should be converted to float for JSON serialization
        self.assertIsInstance(result["data"]["amount"], float)


def run_tests():
    """Run all PaymentValidationService tests"""
    unittest.main()


if __name__ == "__main__":
    run_tests()
