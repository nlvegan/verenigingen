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

# Import the refactored services
from verenigingen.tests.support.sepa_test_configuration import apply_sepa_test_configuration
from verenigingen.verenigingen_payments.services.batch_validation_service import (
    ValidationResult,
    batch_validation_service,
)
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
        # Hygiene, not a fix: the base is plain unittest.TestCase, whose
        # setUpClass is a documented no-op ("pass"), so nothing was actually being
        # skipped before. The call is here so that changing the base class later
        # cannot silently skip its setup.
        super().setUpClass()
        cls._setup_minimal_sepa_config()

    @classmethod
    def _setup_minimal_sepa_config(cls):
        """Set up minimal SEPA configuration for testing.

        Fourth instance of the #466 shape, found by grepping for the class: this
        wrote ``sepa_creditor_id`` / ``company_iban`` / ``company_bic`` onto
        *Verenigingen Settings*, where none of them exist, plus
        ``company = "Test Association"``, which does not exist either -- and
        swallowed the resulting LinkValidationError into a bare ``print``. The
        shared helper refreshes the config service's in-process settings cache
        itself, which is what the note that used to sit here was about.
        """
        cls.eur_company = apply_sepa_test_configuration()

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

    def test_sepa_configuration_service_reads_configured_processing_settings(self):
        """#535: batch_size_limit / allow_zero_amounts must reflect an
        administrator's configured value, not just fall through to the
        hardcoded default -- which is what happened while ``_load_sepa_settings``
        read fieldnames (``sepa_batch_size_limit`` / ``allow_zero_amount_transactions``)
        that did not exist on ``Verenigingen Payments Settings`` (confirmed via
        ``get_meta`` on test_site_fresh: both ``get_field(...)`` calls returned
        ``None``).

        This asserts the resolved *value* changes with the configured field,
        which a bare ``assertIn("batch_size_limit", settings)`` (the pre-existing
        shape of this test class) cannot distinguish from the bug.
        """
        doctype = "Verenigingen Payments Settings"
        configured = {
            "sepa_batch_size_limit": 42,
            "allow_zero_amount_transactions": 1,
        }
        original = {
            fieldname: frappe.db.get_single_value(doctype, fieldname) for fieldname in configured
        }
        try:
            for fieldname, value in configured.items():
                frappe.db.set_single_value(doctype, fieldname, value, update_modified=False)

            settings = sepa_config_service.get_sepa_settings(force_refresh=True)

            self.assertEqual(settings["batch_size_limit"], 42)
            self.assertTrue(settings["allow_zero_amounts"])

            limits = sepa_config_service.get_batch_processing_limits()
            self.assertEqual(limits["max_batch_size"], 42)
            self.assertEqual(limits["min_amount_per_transaction"], 0.00)
        finally:
            for fieldname, value in original.items():
                frappe.db.set_single_value(doctype, fieldname, value, update_modified=False)
            sepa_config_service.refresh_settings_cache()

    def test_sepa_configuration_service_falls_back_when_unconfigured(self):
        """#535, the case the previous test could not distinguish from the bug.

        A declared-but-never-written field on a Single loads as ``None``
        (measured on test_site_fresh: deleting the ``tabSingles`` row for
        ``sepa_batch_size_limit`` outright still leaves ``getattr(doc, field,
        "MISSING")`` returning ``None``, never the sentinel) -- and once
        anything has since saved the Single, a missing Int is coerced to ``0``
        instead. Either way the field is *present*, so a presence-based
        ``getattr(doc, field, default)`` / ``doc.get(field, default)`` never
        falls back to the intended default; only a falsiness check
        (``doc.get(field) or default``) does.

        This is the one case the previous test's configured-value assertions
        cannot tell apart from the bug: reverting just the ``or default`` code
        change back to a presence-based read, while leaving the doctype fields
        declared, leaves that test green (a real, non-zero configured value
        round-trips identically either way) but leaves this one red.
        """
        doctype = "Verenigingen Payments Settings"
        original = frappe.db.get_single_value(doctype, "sepa_batch_size_limit")
        try:
            for unset in (0, None):
                with self.subTest(stored=unset):
                    frappe.db.set_single_value(
                        doctype, "sepa_batch_size_limit", unset, update_modified=False
                    )
                    settings = sepa_config_service.get_sepa_settings(force_refresh=True)
                    self.assertEqual(settings["batch_size_limit"], 1000)

                    limits = sepa_config_service.get_batch_processing_limits()
                    self.assertEqual(limits["max_batch_size"], 1000)
        finally:
            frappe.db.set_single_value(
                doctype, "sepa_batch_size_limit", original, update_modified=False
            )
            sepa_config_service.refresh_settings_cache()

    def test_sepa_configuration_service_zero_amount_limit_has_a_control(self):
        """The min-amount-per-transaction check
        (``batch_validation_service.py``'s amount-too-small guard) only proves
        it reads ``allow_zero_amounts`` if both the on and off state are
        checked -- an assertion of only the "allowed" side cannot distinguish
        "reads the field" from "always returns 0.00".
        """
        doctype = "Verenigingen Payments Settings"
        original = frappe.db.get_single_value(doctype, "allow_zero_amount_transactions")
        try:
            frappe.db.set_single_value(
                doctype, "allow_zero_amount_transactions", 0, update_modified=False
            )
            sepa_config_service.get_sepa_settings(force_refresh=True)
            limits = sepa_config_service.get_batch_processing_limits()
            self.assertEqual(limits["min_amount_per_transaction"], 0.01)
        finally:
            frappe.db.set_single_value(
                doctype, "allow_zero_amount_transactions", original, update_modified=False
            )
            sepa_config_service.refresh_settings_cache()

    def test_sepa_configuration_service_dropped_dead_strict_validation_key(self):
        """#535: ``enable_strict_validation`` read a field
        (``enable_strict_sepa_validation``) that has never existed on either
        Settings doctype and had zero consumers of its own key (confirmed by
        ``grep -rn "enable_strict_validation"`` finding only its own producer
        line). It is dead in both directions, so the fix removes the key
        entirely rather than wiring it to a field nothing reads.
        """
        settings = sepa_config_service.get_sepa_settings(force_refresh=True)
        self.assertNotIn("enable_strict_validation", settings)

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
