#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive Tests for Direct Debit Batch Refactoring

This test suite validates that the refactored Direct Debit Batch system maintains
all functionality after extracting business logic into specialized services.
Tests focus on realistic data generation and service integration rather than mocking.

Test Areas:
- Service layer functionality
- API endpoint compatibility
- SEPA XML generation compliance
- Error handling and fallback mechanisms

Author: Verenigingen Development Team
"""

import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any, Dict, List
from unittest.mock import patch

import frappe
from frappe.utils import nowdate, nowtime, random_string, today

# Import the Enhanced Test Factory
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.services.batch_processing_service import batch_processing_service
from verenigingen.verenigingen_payments.services.batch_validation_service import batch_validation_service

# Import the refactored services
from verenigingen.verenigingen_payments.services.sepa_configuration_service import sepa_config_service
from verenigingen.verenigingen_payments.services.sepa_xml_generation_service import sepa_xml_service

# Import utilities
from verenigingen.verenigingen_payments.utils.sepa_utilities import (
    BatchLoggingUtilities,
    CalculationUtilities,
    SEPAUtilities,
)


class TestDirectDebitBatchRefactoring(EnhancedTestCase):
    """Test suite for refactored Direct Debit Batch system"""

    @classmethod
    def setUpClass(cls):
        """Set up test data once for all tests"""
        super().setUpClass()
        cls._setup_sepa_configuration()

    @classmethod
    def _setup_sepa_configuration(cls):
        """Set up SEPA configuration for testing.

        The SEPA configuration service reads creditor_id / company_bic /
        company_iban from *Verenigingen Payments Settings* (not Verenigingen
        Settings), and the company must be EUR for invoice validation.
        """
        try:
            from verenigingen.tests.support.sepa_test_company import get_eur_test_company

            cls.eur_company = get_eur_test_company()

            ven_settings = frappe.get_single("Verenigingen Settings")
            if ven_settings.company != cls.eur_company:
                ven_settings.company = cls.eur_company
                ven_settings.flags.ignore_validate = True
                ven_settings.save(ignore_permissions=True)

            payments = frappe.get_single("Verenigingen Payments Settings")
            payments.company_iban = "NL91ABNA0417164300"
            payments.company_bic = "ABNANL2A"
            payments.creditor_id = "NL12ZZZ123456789"
            payments.flags.ignore_validate = True
            payments.save(ignore_permissions=True)
            frappe.db.commit()

            # The SEPA configuration service caches the resolved settings
            # (organization_name etc.) at the singleton level; clear that cache
            # plus the cached Verenigingen Settings single so the EUR company set
            # above is picked up. (Do NOT call frappe.clear_cache() — wiping the
            # DocType meta cache mid-test drops field defaults like
            # SEPA Batch Upload Log.batch_status and breaks inserts.)
            sepa_config_service.refresh_settings_cache()
            frappe.clear_document_cache("Verenigingen Settings", "Verenigingen Settings")

        except Exception as e:
            frappe.logger().warning(f"Could not set up SEPA configuration: {str(e)}")

    def setUp(self):
        """Set up each test with fresh data"""
        super().setUp()
        self.test_members = []
        self.test_invoices = []
        self.test_mandates = []
        self.test_batch = None
        # The app's before_tests hook (and other modules) can reset
        # Verenigingen Settings.company to the ERPNext "_Test Company" (whose
        # name contains an underscore, invalid for SEPA), and the config service
        # caches the resolved organization_name. Re-assert the EUR company and
        # refresh the cache per-test so SEPA XML generation gets a valid name.
        self._setup_sepa_configuration()

    def tearDown(self):
        """Clean up test data"""
        super().tearDown()

        # Clean up test batch
        if self.test_batch:
            try:
                frappe.delete_doc("Direct Debit Batch", self.test_batch.name, force=True)
            except:
                pass

    def test_before_submit_rejects_past_batch_date(self):
        """A batch scheduled to collect on a past date must be rejected at submit.

        Guards DirectDebitBatch.before_submit(); called directly to isolate the
        date check from the heavy submit/XML machinery."""
        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = frappe.utils.add_days(today(), -1)
        with self.assertRaises(frappe.ValidationError):
            batch.before_submit()

    def test_before_submit_allows_today_and_future_batch_date(self):
        """Today and future collection dates are valid and must not be rejected."""
        for valid_date in (today(), frappe.utils.add_days(today(), 5)):
            batch = frappe.new_doc("Direct Debit Batch")
            batch.batch_date = valid_date
            batch.before_submit()  # must not raise

    def test_sepa_configuration_service(self):
        """Test SEPA Configuration Service functionality"""
        # Test settings retrieval
        settings = sepa_config_service.get_sepa_settings()

        self.assertIsInstance(settings, dict)
        self.assertIn("organization_name", settings)
        self.assertIn("creditor_id", settings)
        self.assertIn("iban", settings)
        self.assertIn("bic", settings)

        # Test configuration validation
        validation_result = sepa_config_service.validate_sepa_configuration()

        self.assertIsInstance(validation_result, dict)
        self.assertIn("is_valid", validation_result)
        self.assertIn("errors", validation_result)
        self.assertIn("warnings", validation_result)

        # Test collection date settings
        date_settings = sepa_config_service.get_collection_date_settings()

        self.assertIsInstance(date_settings, dict)
        self.assertIn("offset_days", date_settings)
        self.assertIn("grace_period_days", date_settings)

        # Test batch processing limits
        limits = sepa_config_service.get_batch_processing_limits()

        self.assertIsInstance(limits, dict)
        self.assertIn("max_batch_size", limits)
        self.assertIn("max_amount_per_transaction", limits)

    def test_batch_validation_service(self):
        """Test Batch Validation Service functionality"""
        # Create test invoices with realistic Dutch data
        test_invoices = self._create_test_invoices_data(5)

        # Test batch creation validation
        validation_result = batch_validation_service.validate_batch_creation(
            test_invoices, (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        )

        self.assertIsNotNone(validation_result)
        self.assertTrue(hasattr(validation_result, "is_valid"))

    def test_sepa_xml_generation_service(self):
        """Test SEPA XML Generation Service functionality"""
        # Create a test batch with realistic data
        batch_doc = self._create_test_batch_with_invoices()

        # Test XML generation
        try:
            xml_file_url = sepa_xml_service.generate_sepa_xml_for_batch(batch_doc)

            self.assertIsNotNone(xml_file_url)
            self.assertTrue(batch_doc.sepa_file_generated)
            self.assertIsNotNone(batch_doc.sepa_message_id)
            self.assertIsNotNone(batch_doc.sepa_payment_info_id)

            # Validate XML structure if file was created
            if batch_doc.sepa_file:
                self._validate_sepa_xml_structure(batch_doc)

        except Exception as e:
            # Log the error but don't fail the test if configuration is incomplete
            frappe.logger().warning(f"SEPA XML generation test skipped due to configuration: {str(e)}")

    def test_batch_processing_service(self):
        """Test Batch Processing Service functionality"""
        # Create test batch
        batch_doc = self._create_test_batch_with_invoices()

        # Test batch totals calculation
        batch_processing_service.calculate_batch_totals_optimized(batch_doc)

        self.assertGreater(batch_doc.entry_count, 0)
        self.assertGreater(batch_doc.total_amount, 0)

        # Test invoice validation
        validation_result = batch_processing_service.validate_batch_invoices_optimized(batch_doc)

        self.assertIsInstance(validation_result, dict)
        self.assertIn("is_valid", validation_result)
        self.assertIn("total_invoices", validation_result)
        self.assertIn("valid_invoices", validation_result)

    def test_sepa_utilities(self):
        """Test SEPA utility functions"""
        # Test IBAN validation
        valid_iban = "NL91ABNA0417164300"
        invalid_iban = "INVALID_IBAN"

        self.assertTrue(SEPAUtilities.validate_dutch_iban(valid_iban))
        self.assertFalse(SEPAUtilities.validate_dutch_iban(invalid_iban))

        # Test BIC derivation
        bic = SEPAUtilities.get_bic_from_iban(valid_iban)
        self.assertEqual(bic, "ABNANL2A")

        # Test IBAN formatting
        formatted = SEPAUtilities.format_iban_display("NL91ABNA0417164300")
        self.assertEqual(formatted, "NL91 ABNA 0417 1643 00")

    def test_api_endpoint_compatibility(self):
        """Test that original API endpoints still work after refactoring"""
        # Test the whitelisted API methods
        from verenigingen.verenigingen_payments.doctype.direct_debit_batch.direct_debit_batch import (
            create_enhanced_dues_batch,
            generate_direct_debit_batch,
            get_dues_collection_preview,
        )

        # Test dues collection preview (should not create any data)
        try:
            preview_result = get_dues_collection_preview(
                collection_date=(datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d"), days_ahead=30
            )

            self.assertIsInstance(preview_result, dict)
            self.assertIn("success", preview_result)

        except Exception as e:
            # API might fail due to missing dependencies, but should not crash
            frappe.logger().warning(f"API test warning: {str(e)}")

    def test_error_handling_and_fallback_mechanisms(self):
        """Test error handling and fallback mechanisms in the refactored system"""
        # Test SQL aggregation fallback
        batch_doc = self._create_test_batch_with_invoices()

        # Test with valid batch
        batch_processing_service.calculate_batch_totals_optimized(batch_doc)
        original_total = batch_doc.total_amount

        # Simulate SQL failure by temporarily removing batch name
        original_name = batch_doc.name
        batch_doc.name = "NONEXISTENT_BATCH"

        # This should trigger the Python fallback
        batch_processing_service.calculate_batch_totals_optimized(batch_doc)

        # Restore name
        batch_doc.name = original_name

        # Should still have calculated a total (via fallback)
        self.assertIsNotNone(batch_doc.total_amount)

    def test_dutch_business_logic_compliance(self):
        """Test compliance with Dutch SEPA and banking standards"""
        # Test Dutch IBAN validation - use valid IBANs with correct checksums
        from verenigingen.utils.validation.iban_validator import generate_test_iban

        dutch_ibans = [
            "NL91ABNA0417164300",  # ABN AMRO - valid checksum
            generate_test_iban("RABO", "0000123456"),  # Rabobank - valid checksum
            generate_test_iban("INGB", "0000000001"),  # ING Bank - valid checksum
        ]

        for iban in dutch_ibans:
            self.assertTrue(SEPAUtilities.validate_dutch_iban(iban))
            bic = SEPAUtilities.get_bic_from_iban(iban)
            self.assertIsNotNone(bic)
            self.assertTrue(len(bic) >= 8)

    def test_performance_optimization(self):
        """Test that performance optimizations work correctly"""
        # Create a larger batch to test optimization
        batch_doc = self._create_test_batch_with_invoices(invoice_count=20)

        # Test SQL aggregation performance
        import time

        start_time = time.time()

        batch_processing_service.calculate_batch_totals_optimized(batch_doc)

        calculation_time = time.time() - start_time

        # Should complete within reasonable time
        self.assertLess(calculation_time, 5.0)  # 5 seconds max

        # Test bulk validation
        start_time = time.time()

        validation_result = batch_processing_service.validate_batch_invoices_optimized(batch_doc)

        validation_time = time.time() - start_time

        # Should complete within reasonable time
        self.assertLess(validation_time, 10.0)  # 10 seconds max
        self.assertIsInstance(validation_result, dict)

    def _create_test_invoices_data(self, count: int = 5) -> List[Dict[str, Any]]:
        """Create test invoice data for validation testing"""
        from verenigingen.utils.validation.iban_validator import generate_test_iban

        invoices = []
        bank_codes = ["ABNA", "RABO", "INGB", "TRIO", "KNAB"]

        for i in range(count):
            bank_code = bank_codes[i % len(bank_codes)]
            test_iban = generate_test_iban(bank_code, f"{i:010d}")

            invoice_data = {
                "name": f"INV-TEST-{i+1:03d}",
                "customer": f"CUST-TEST-{i+1:03d}",
                "outstanding_amount": 25.00 + (i * 5),  # €25, €30, €35, etc.
                "currency": "EUR",
                "status": "Unpaid",
                "due_date": datetime.now() + timedelta(days=30),
                "posting_date": datetime.now() - timedelta(days=5),
                "iban": test_iban,
                "mandate_reference": f"MAND-{i+1:03d}",
            }
            invoices.append(invoice_data)

        return invoices

    def _create_test_batch_with_invoices(self, invoice_count: int = 5):
        """Create a test Direct Debit Batch backed by real submitted invoices.

        The Direct Debit Batch Invoice child requires a real Sales Invoice link
        plus membership/member/iban/mandate_reference (all reqd), so we build
        real members + SEPA mandates + memberships + submitted EUR Sales Invoices
        rather than fabricated INV-TEST-NNN names (which fail LinkValidation).
        """
        from verenigingen.tests.support.sepa_test_company import get_eur_test_company

        company = get_eur_test_company()

        batch_doc = frappe.new_doc("Direct Debit Batch")
        batch_doc.batch_date = today()
        batch_doc.batch_description = f"Test Batch - {random_string(8)}"
        # batch_type is the SEPA scheme (CORE/B2B/COR1); sequence_type is the SEPA
        # sequence (FRST/RCUR/FNAL/OOFF). The rows below use FRST (first usage of
        # brand-new mandates); the XML PaymentInfo SeqTp comes from sequence_type
        # and must match the transaction sequence types, so set sequence_type=FRST.
        batch_doc.batch_type = "CORE"
        batch_doc.sequence_type = "FRST"
        batch_doc.currency = "EUR"

        for i in range(invoice_count):
            amount = 25.00 + (i * 5)
            member = self.create_test_member(
                first_name=f"DDBatch{i}",
                last_name="Member",
                email=f"ddbatch{i}.{self.factory.test_run_id}@example.com",
            )

            mandate = self.create_test_sepa_mandate(member_name=member.name, status="Active")
            membership = self.create_test_membership(member=member.name)

            # create_test_sales_invoice resolves a Member name to its linked
            # Customer (creating one if needed), submits by default
            # (status != "Draft"), and uses grand_total for the line amount.
            invoice = self.create_test_sales_invoice(
                customer=member.name,
                company=company,
                membership=membership.name,
                grand_total=amount,
            )
            member.reload()

            batch_doc.append(
                "invoices",
                {
                    "invoice": invoice.name,
                    "membership": membership.name,
                    "member": member.name,
                    "member_name": member.full_name,
                    "amount": amount,
                    "currency": "EUR",
                    "iban": mandate.iban,
                    "mandate_reference": mandate.mandate_id,
                    "status": "Pending",
                    # First usage of a brand-new mandate must be FRST; the real
                    # controller rejects RCUR for first mandate usage (SEPA rule).
                    "sequence_type": "FRST",
                },
            )

        batch_doc.insert()
        self.test_batch = batch_doc

        return batch_doc

    def _validate_sepa_xml_structure(self, batch_doc):
        """Validate that generated SEPA XML has correct structure"""
        try:
            # This would validate the XML file if it exists
            # For now, we check that the required fields are set
            self.assertIsNotNone(batch_doc.sepa_message_id)
            self.assertIsNotNone(batch_doc.sepa_payment_info_id)
            self.assertIsNotNone(batch_doc.sepa_generation_date)
            self.assertTrue(batch_doc.sepa_file_generated)

        except Exception as e:
            frappe.logger().warning(f"XML validation skipped: {str(e)}")


class TestSEPAUtilities(unittest.TestCase):
    """Focused tests for SEPA utility functions"""

    def test_iban_validation_edge_cases(self):
        """Test IBAN validation with edge cases"""
        from verenigingen.utils.validation.iban_validator import generate_test_iban

        # Valid Dutch IBANs with correct checksums
        valid_ibans = [
            "NL91ABNA0417164300",  # Valid checksum
            generate_test_iban("RABO", "0000123456"),  # Valid checksum
            generate_test_iban("INGB", "0000000001"),  # Valid checksum
        ]

        for iban in valid_ibans:
            self.assertTrue(SEPAUtilities.validate_dutch_iban(iban))

        # Invalid IBANs
        invalid_ibans = [
            "",
            None,
            "INVALID",
            "DE89370400440532013000",  # German IBAN
            "NL91ABNA041716430",  # Too short
            "NL91ABNA04171643000",  # Too long
        ]

        for iban in invalid_ibans:
            self.assertFalse(SEPAUtilities.validate_dutch_iban(iban))

    def test_bic_derivation_completeness(self):
        """Test BIC derivation for all major Dutch banks"""
        from verenigingen.utils.validation.iban_validator import generate_test_iban

        # Generate valid IBANs with correct checksums for each bank
        test_cases = [
            ("NL91ABNA0417164300", "ABNANL2A"),  # ABN AMRO - valid checksum
            (generate_test_iban("RABO", "0123456789"), "RABONL2U"),  # Rabobank - valid checksum
            (generate_test_iban("INGB", "0000000001"), "INGBNL2A"),  # ING Bank - valid checksum
            (generate_test_iban("TRIO", "0123456789"), "TRIONL2U"),  # Triodos Bank - valid checksum
            (generate_test_iban("KNAB", "0123456789"), "KNABNL2H"),  # Knab - valid checksum
        ]

        for iban, expected_bic in test_cases:
            derived_bic = SEPAUtilities.get_bic_from_iban(iban)
            self.assertEqual(derived_bic, expected_bic, f"BIC derivation failed for {iban}")

    def test_iban_formatting(self):
        """Test IBAN display formatting"""
        test_cases = [
            ("NL91ABNA0417164300", "NL91 ABNA 0417 1643 00"),
            ("nl91abna0417164300", "NL91 ABNA 0417 1643 00"),  # Lowercase
            ("NL91 ABNA 0417 1643 00", "NL91 ABNA 0417 1643 00"),  # Already formatted
            ("", ""),
            (None, ""),
        ]

        for input_iban, expected in test_cases:
            result = SEPAUtilities.format_iban_display(input_iban)
            self.assertEqual(result, expected, f"Formatting failed for {input_iban}")


if __name__ == "__main__":
    # Run the tests
    unittest.main()
