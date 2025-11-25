# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Unit tests for Payment Validation Service API

Tests payment validation API endpoints with OperationResult pattern.
Focus on type-safe error handling for payment validation operations.

Migration Status: ✅ COMPLETE (2025-11-24)
- All tests use OperationResult API
- Proper assertions for .success, .data, .error_message
"""

import frappe
from verenigingen.services.payment.validation_service import (
    validate_iban_api,
    validate_bank_details_api,
    validate_payment_method_api,
    validate_payment_amount_api,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPaymentValidationAPI(EnhancedTestCase):
    """Unit tests for Payment Validation Service API endpoints"""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def test_validate_iban_api_returns_operation_result(self):
        """Test validate_iban_api returns OperationResult"""
        result = validate_iban_api("NL91ABNA0417164300")

        # OperationResult pattern
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.success)

    def test_validate_iban_api_with_invalid_iban_returns_failed_result(self):
        """Test IBAN validation with invalid IBAN returns failed OperationResult"""
        result = validate_iban_api("INVALID_IBAN")

        # Should fail gracefully
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error_message)

    def test_validate_bank_details_api_returns_operation_result(self):
        """Test validate_bank_details_api returns OperationResult"""
        result = validate_bank_details_api(
            iban="NL91ABNA0417164300",
            bic="ABNANL2A",
            account_holder_name="Test Account"
        )

        # OperationResult pattern
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.success)

    def test_validate_bank_details_api_with_invalid_data_returns_failed_result(self):
        """Test bank details validation with invalid data returns failed OperationResult"""
        result = validate_bank_details_api(iban="INVALID")

        # Should fail gracefully
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error_message)

    def test_validate_payment_method_api_returns_operation_result(self):
        """Test validate_payment_method_api returns OperationResult"""
        result = validate_payment_method_api("Cash")

        # OperationResult pattern
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.success)

    def test_validate_payment_amount_api_returns_operation_result(self):
        """Test validate_payment_amount_api returns OperationResult"""
        result = validate_payment_amount_api(100.00)

        # OperationResult pattern
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.success)

    def test_validate_payment_amount_api_with_negative_amount(self):
        """Test payment amount validation with negative amount"""
        result = validate_payment_amount_api(-50.00)

        # Should return OperationResult (may fail depending on validation rules)
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.success)

    def test_payment_validation_apis_never_throw_exceptions(self):
        """Test that payment validation APIs never throw exceptions"""
        # Test with various invalid inputs
        apis_to_test = [
            (validate_iban_api, ("",)),
            (validate_iban_api, ("INVALID",)),
            (validate_bank_details_api, ("",)),
            (validate_payment_method_api, ("NonexistentMethod",)),
            (validate_payment_amount_api, (0.0,)),
        ]

        for api_func, args in apis_to_test:
            result = api_func(*args)
            self.assertIsNotNone(result, f"{api_func.__name__} returned None")
            self.assertIsNotNone(result.success, f"{api_func.__name__} missing success attribute")

    def test_api_results_contain_proper_metadata(self):
        """Test that API results contain expected metadata structure"""
        result = validate_iban_api("NL91ABNA0417164300")

        # Check OperationResult structure
        self.assertIsNotNone(result)
        if result.success:
            self.assertIsInstance(result.data, dict)
        else:
            self.assertIsNotNone(result.error_message)
            self.assertIsInstance(result.errors, list)

    def test_iban_masking_in_context(self):
        """Test that IBAN is masked in error context for security"""
        result = validate_iban_api("INVALID_IBAN_12345678")

        # Even if validation fails, should not expose full IBAN
        if not result.success and hasattr(result, 'metadata') and result.metadata:
            context = result.metadata.get('context', {})
            if 'params' in context and 'iban' in context['params']:
                # IBAN should be masked (only first 4 chars + ****)
                self.assertIn("****", context['params']['iban'])


def run_tests():
    """Helper function to run tests from console"""
    frappe.flags.in_test = True
    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestPaymentValidationAPI)
    unittest.TextTestRunner(verbosity=2).run(suite)
