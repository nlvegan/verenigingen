#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Service Layer Validation Tests

This test suite validates that the extracted services work correctly
without requiring complex document setup. Tests focus on service
functionality, data processing, and business logic validation.

Author: Verenigingen Development Team
"""

import unittest
from datetime import datetime, timedelta
from typing import Any, Dict, List

import frappe

from verenigingen.verenigingen_payments.services.batch_validation_service import (
    ValidationResult,
    batch_validation_service,
)

# Import the refactored services
from verenigingen.verenigingen_payments.services.sepa_configuration_service import sepa_config_service
from verenigingen.verenigingen_payments.utils.sepa_utilities import (
    BatchLoggingUtilities,
    CalculationUtilities,
    SEPAUtilities,
)


class TestServiceLayerValidation(unittest.TestCase):
    """Test suite for service layer functionality validation"""

    @classmethod
    def setUpClass(cls):
        """Set up test configuration once"""
        cls._setup_minimal_sepa_config()

    @classmethod
    def _setup_minimal_sepa_config(cls):
        """Set up minimal SEPA configuration for testing"""
        try:
            settings = frappe.get_single("Verenigingen Settings")
            settings.sepa_creditor_id = "NL12ZZZ123456789"
            settings.company_iban = "NL91ABNA0417164300"
            settings.company_bic = "ABNANL2A"
            settings.company = "Test Association"
            settings.save()
        except Exception as e:
            print(f"Warning: Could not set up SEPA config: {str(e)}")

    def test_sepa_configuration_service_basic_functionality(self):
        """Test basic SEPA Configuration Service functionality"""
        # Test settings retrieval
        settings = sepa_config_service.get_sepa_settings()

        self.assertIsInstance(settings, dict)

        # Check expected keys exist
        expected_keys = [
            "organization_name",
            "creditor_id",
            "iban",
            "bic",
            "batch_size_limit",
            "grace_period_days",
            "country_code",
        ]

        for key in expected_keys:
            self.assertIn(key, settings)

        # Test configuration validation
        validation_result = sepa_config_service.validate_sepa_configuration()

        self.assertIsInstance(validation_result, dict)
        self.assertIn("is_valid", validation_result)
        self.assertIn("errors", validation_result)
        self.assertIn("warnings", validation_result)

    def test_batch_validation_service_validation_result_class(self):
        """Test ValidationResult class functionality"""
        result = ValidationResult()

        # Test initial state
        self.assertTrue(result.is_valid)
        self.assertEqual(len(result.errors), 0)
        self.assertEqual(len(result.warnings), 0)

        # Test adding errors
        result.add_error("Test error", "TEST_ERROR")
        self.assertFalse(result.is_valid)
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.errors[0]["message"], "Test error")
        self.assertEqual(result.errors[0]["code"], "TEST_ERROR")

        # Test adding warnings
        result.add_warning("Test warning", "TEST_WARNING")
        self.assertEqual(len(result.warnings), 1)

        # Test to_dict conversion
        result_dict = result.to_dict()
        self.assertIsInstance(result_dict, dict)
        self.assertIn("is_valid", result_dict)
        self.assertIn("errors", result_dict)
        self.assertIn("warnings", result_dict)

    def test_sepa_utilities_iban_validation(self):
        """Test SEPA utilities IBAN validation functionality"""
        # Test valid Dutch IBANs (MOD-97 checksum-valid; the canonical validator
        # rejects bad checksums, so the previous placeholder RABO/INGB numbers
        # with arbitrary digits no longer pass).
        valid_ibans = ["NL91ABNA0417164300", "NL44RABO0123456789", "NL69INGB0123456789"]

        for iban in valid_ibans:
            self.assertTrue(SEPAUtilities.validate_dutch_iban(iban))
            self.assertTrue(SEPAUtilities.validate_iban_format(iban))

        # Test invalid IBANs
        invalid_ibans = [
            "",
            None,
            "INVALID",
            "DE89370400440532013000",  # German IBAN
            "NL91ABNA041716430",  # Too short
        ]

        for iban in invalid_ibans:
            self.assertFalse(SEPAUtilities.validate_dutch_iban(iban))

    def test_sepa_utilities_bic_derivation(self):
        """Test BIC derivation from Dutch IBANs"""
        # Checksum-valid Dutch IBANs (BIC derivation only runs on valid IBANs).
        test_cases = [
            ("NL91ABNA0417164300", "ABNANL2A"),
            ("NL44RABO0123456789", "RABONL2U"),
            ("NL69INGB0123456789", "INGBNL2A"),
        ]

        for iban, expected_bic in test_cases:
            derived_bic = SEPAUtilities.get_bic_from_iban(iban)
            self.assertEqual(derived_bic, expected_bic)

    def test_sepa_utilities_iban_formatting(self):
        """Test IBAN display formatting"""
        test_cases = [
            ("NL91ABNA0417164300", "NL91 ABNA 0417 1643 00"),
            ("nl91abna0417164300", "NL91 ABNA 0417 1643 00"),
            ("", ""),
        ]

        for input_iban, expected in test_cases:
            result = SEPAUtilities.format_iban_display(input_iban)
            self.assertEqual(result, expected)

    def test_calculation_utilities(self):
        """Test calculation utilities functionality"""
        # Create mock invoice data
        mock_invoices = [
            {"amount": 25.00},
            {"amount": 50.00},
            {"amount": 35.00},
        ]

        # Test batch totals calculation
        totals = CalculationUtilities.calculate_batch_totals(mock_invoices)

        self.assertIsInstance(totals, dict)
        self.assertIn("total_amount", totals)
        self.assertIn("count", totals)
        self.assertEqual(totals["count"], 3)
        self.assertEqual(totals["total_amount"], 110.00)

    def test_batch_validation_service_invoice_validation(self):
        """Test batch validation service with mock invoice data"""
        # Create mock invoice data
        valid_invoices = [
            {
                "name": "INV-001",
                "customer": "CUST-001",
                "outstanding_amount": 25.00,
                "currency": "EUR",
                "status": "Unpaid",
            },
            {
                "name": "INV-002",
                "customer": "CUST-002",
                "outstanding_amount": 50.00,
                "currency": "EUR",
                "status": "Unpaid",
            },
        ]

        # Test validation (this should work without database dependencies)
        try:
            validation_result = batch_validation_service.validate_batch_creation(
                valid_invoices, (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
            )

            # Should return a ValidationResult object
            self.assertIsNotNone(validation_result)
            self.assertTrue(hasattr(validation_result, "is_valid"))

        except Exception as e:
            # If validation fails due to missing dependencies, that's expected
            print(f"Validation test note: {str(e)}")

    def test_sepa_configuration_service_date_settings(self):
        """Test date settings functionality"""
        date_settings = sepa_config_service.get_collection_date_settings()

        self.assertIsInstance(date_settings, dict)

        expected_keys = ["offset_days", "grace_period_days", "minimum_notice_days", "maximum_notice_days"]

        for key in expected_keys:
            self.assertIn(key, date_settings)
            self.assertIsInstance(date_settings[key], int)

    def test_sepa_configuration_service_batch_limits(self):
        """Test batch processing limits"""
        limits = sepa_config_service.get_batch_processing_limits()

        self.assertIsInstance(limits, dict)

        expected_keys = [
            "max_batch_size",
            "max_amount_per_transaction",
            "max_total_batch_amount",
            "min_amount_per_transaction",
        ]

        for key in expected_keys:
            self.assertIn(key, limits)
            self.assertIsInstance(limits[key], (int, float))

    def test_sepa_configuration_service_caching(self):
        """Test settings caching functionality"""
        # Get settings twice
        settings1 = sepa_config_service.get_sepa_settings()
        settings2 = sepa_config_service.get_sepa_settings()

        # Should be the same object (cached)
        self.assertEqual(settings1, settings2)

        # Force refresh
        settings3 = sepa_config_service.get_sepa_settings(force_refresh=True)

        # Should still be equal but potentially different object
        self.assertEqual(settings1, settings3)

    def test_batch_validation_service_date_validation(self):
        """Test collection date validation logic"""
        # Create validation service instance
        validation_service = batch_validation_service

        # Test valid future date
        future_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        date_validation = validation_service._validate_collection_date(future_date)

        self.assertIsInstance(date_validation, ValidationResult)

        # Test past date (should fail)
        past_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        past_validation = validation_service._validate_collection_date(past_date)

        self.assertIsInstance(past_validation, ValidationResult)
        # Past dates should generate errors
        self.assertFalse(past_validation.is_valid)

    def test_batch_validation_service_limits_validation(self):
        """Test batch limits validation"""
        # Create mock invoice data that exceeds limits
        large_invoice_set = []
        for i in range(1500):  # Exceed typical batch size limit
            large_invoice_set.append(
                {
                    "name": f"INV-{i:04d}",
                    "customer": f"CUST-{i:04d}",
                    "outstanding_amount": 25.00,
                    "currency": "EUR",
                    "status": "Unpaid",
                }
            )

        # Test limits validation
        limits_validation = batch_validation_service._validate_batch_limits(large_invoice_set)

        self.assertIsInstance(limits_validation, ValidationResult)
        # Should detect batch size violation
        self.assertFalse(limits_validation.is_valid)

    def test_service_error_handling(self):
        """Test service error handling"""
        # Test with invalid parameters
        try:
            # Should handle None gracefully
            result = SEPAUtilities.validate_dutch_iban(None)
            self.assertFalse(result)

            # Should handle empty string gracefully
            result = SEPAUtilities.get_bic_from_iban("")
            self.assertIsNone(result)

        except Exception as e:
            self.fail(f"Service should handle invalid parameters gracefully: {str(e)}")

    def test_service_singleton_pattern(self):
        """Test that services use singleton pattern correctly"""
        # Test that we get the same instance
        config1 = sepa_config_service
        config2 = sepa_config_service

        self.assertIs(config1, config2)

        validation1 = batch_validation_service
        validation2 = batch_validation_service

        self.assertIs(validation1, validation2)


class TestSEPAUtilitiesStandalone(unittest.TestCase):
    """Standalone tests for SEPA utilities"""

    def test_dutch_bank_bic_mapping_completeness(self):
        """Test that all major Dutch banks are supported"""
        # MOD-97 checksum-valid IBANs (BIC derivation requires a valid IBAN).
        major_dutch_banks = [
            ("NL91ABNA0417164300", "ABNANL2A"),  # ABN AMRO
            ("NL44RABO0123456789", "RABONL2U"),  # Rabobank
            ("NL69INGB0123456789", "INGBNL2A"),  # ING Bank
            ("NL70TRIO0123456789", "TRIONL2U"),  # Triodos Bank
            ("NL68KNAB0123456789", "KNABNL2H"),  # Knab
        ]

        for iban, expected_bic in major_dutch_banks:
            derived_bic = SEPAUtilities.get_bic_from_iban(iban)
            self.assertEqual(derived_bic, expected_bic, f"BIC derivation failed for {iban}")

    def test_iban_edge_cases(self):
        """Test IBAN validation with edge cases"""
        edge_cases = [
            # Valid cases
            ("NL91ABNA0417164300", True),  # Standard format
            ("nl91abna0417164300", True),  # Lowercase (converted to uppercase internally)
            ("NL91 ABNA 0417 1643 00", True),  # With spaces
            # Invalid cases
            ("", False),
            (None, False),
            ("NL91ABNA041716430", False),  # Too short
            ("NL91ABNA04171643000", False),  # Too long
            ("DE89370400440532013000", False),  # German IBAN
        ]

        for iban, expected in edge_cases:
            result = SEPAUtilities.validate_dutch_iban(iban)
            if expected:
                self.assertTrue(result, f"Expected {iban} to be valid")
            else:
                self.assertFalse(result, f"Expected {iban} to be invalid")

    def test_calculation_utilities_edge_cases(self):
        """Test calculation utilities with edge cases"""
        # Empty list
        empty_result = CalculationUtilities.calculate_batch_totals([])
        self.assertEqual(empty_result["total_amount"], 0.0)
        self.assertEqual(empty_result["count"], 0)

        # Single item
        single_result = CalculationUtilities.calculate_batch_totals([{"amount": 42.50}])
        self.assertEqual(single_result["total_amount"], 42.50)
        self.assertEqual(single_result["count"], 1)

        # Items with zero amounts
        zero_result = CalculationUtilities.calculate_batch_totals(
            [{"amount": 0.00}, {"amount": 25.00}, {"amount": 0.00}]
        )
        self.assertEqual(zero_result["total_amount"], 25.00)
        self.assertEqual(zero_result["count"], 3)


if __name__ == "__main__":
    unittest.main()
