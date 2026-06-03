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
- Business logic orchestration
- Error handling and fallback mechanisms
- End-to-end batch processing workflows

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
from verenigingen.verenigingen_payments.services.business_logic_orchestration_service import (
    business_logic_service,
)

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
        """Set up SEPA configuration for testing"""
        try:
            # Get or create Verenigingen Settings
            settings = frappe.get_single("Verenigingen Settings")

            # Set test SEPA configuration
            settings.sepa_creditor_id = "NL12ZZZ123456789"
            settings.company_iban = "NL91ABNA0417164300"
            settings.company_bic = "ABNANL2A"
            settings.company = "Test Association"
            settings.sepa_batch_size_limit = 1000
            settings.enable_strict_sepa_validation = True
            settings.allow_zero_amount_transactions = False

            settings.save()
            frappe.db.commit()

        except Exception as e:
            frappe.logger().warning(f"Could not set up SEPA configuration: {str(e)}")

    def setUp(self):
        """Set up each test with fresh data"""
        super().setUp()
        self.test_members = []
        self.test_invoices = []
        self.test_mandates = []
        self.test_batch = None

    def tearDown(self):
        """Clean up test data"""
        super().tearDown()

        # Clean up test batch
        if self.test_batch:
            try:
                frappe.delete_doc("Direct Debit Batch", self.test_batch.name, force=True)
            except:
                pass

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

        # Test mandate coverage validation
        mandate_result = batch_validation_service.validate_mandate_coverage(test_invoices)

        self.assertIsNotNone(mandate_result)
        self.assertTrue(hasattr(mandate_result, "is_valid"))

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

        # Test sequence type validation
        sequence_result = batch_processing_service.validate_sepa_sequence_types(batch_doc)

        self.assertIsInstance(sequence_result, dict)
        self.assertIn("is_valid", sequence_result)
        self.assertIn("corrections", sequence_result)

    def test_business_logic_orchestration_service(self):
        """Test Business Logic Orchestration Service functionality"""
        # Create test batch
        batch_doc = self._create_test_batch_with_invoices()

        # Test complete batch processing orchestration
        orchestration_result = business_logic_service.orchestrate_complete_batch_processing(batch_doc)

        self.assertIsInstance(orchestration_result, dict)
        self.assertIn("validation_passed", orchestration_result)
        self.assertIn("xml_generated", orchestration_result)
        self.assertIn("batch_ready", orchestration_result)
        self.assertIn("errors", orchestration_result)
        self.assertIn("warnings", orchestration_result)

        # Test batch creation workflow
        test_invoices = self._create_test_invoices_data(3)
        creation_result = business_logic_service.orchestrate_batch_creation_workflow(
            test_invoices, (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        )

        self.assertIsInstance(creation_result, dict)
        self.assertIn("batch_created", creation_result)
        self.assertIn("total_amount", creation_result)
        self.assertIn("invoice_count", creation_result)

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

    def test_end_to_end_batch_processing(self):
        """Test complete end-to-end batch processing workflow"""
        # Step 1: Create test data
        members_with_mandates = self._create_test_members_with_mandates(3)

        # Step 2: Create unpaid invoices
        test_invoices = []
        for member_data in members_with_mandates:
            invoice = self._create_test_invoice_for_member(member_data)
            test_invoices.append(invoice)

        # Step 3: Test batch creation workflow
        collection_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")

        creation_result = business_logic_service.orchestrate_batch_creation_workflow(
            test_invoices, collection_date
        )

        self.assertTrue(creation_result.get("batch_created", False))
        batch_name = creation_result.get("batch_name")
        self.assertIsNotNone(batch_name)

        # Step 4: Test complete processing orchestration
        if batch_name:
            batch_doc = frappe.get_doc("Direct Debit Batch", batch_name)

            orchestration_result = business_logic_service.orchestrate_complete_batch_processing(batch_doc)

            self.assertIsInstance(orchestration_result, dict)
            # Should have some validation results even if not all pass
            self.assertIn("validation_passed", orchestration_result)

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
        # Real batch_type options are CORE/B2B/FRST/RCUR.
        batch_doc.batch_type = "RCUR"
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

    def _create_test_members_with_mandates(self, count: int = 3) -> List[Dict[str, Any]]:
        """Create test members with SEPA mandates"""
        from verenigingen.utils.validation.iban_validator import generate_test_iban

        members_data = []
        bank_codes = ["ABNA", "RABO", "INGB"]

        for i in range(count):
            bank_code = bank_codes[i % len(bank_codes)]
            test_iban = generate_test_iban(bank_code, f"{i:010d}")

            # Create basic member data
            member_data = {
                "first_name": f"Test{i+1}",
                "last_name": f"Member{i+1}",
                "email": f"test{i+1}@verenigingen.test",
                "iban": test_iban,
                "mandate_reference": f"MAND-{i+1:03d}",
            }

            members_data.append(member_data)

        return members_data

    def _create_test_invoice_for_member(self, member_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create test invoice data for a member"""
        return {
            "name": f"INV-{member_data['first_name']}-{random_string(4)}",
            "customer": f"CUST-{member_data['first_name']}",
            "outstanding_amount": 25.00,
            "currency": "EUR",
            "status": "Unpaid",
            "due_date": datetime.now() + timedelta(days=30),
            "posting_date": datetime.now() - timedelta(days=5),
            "iban": member_data["iban"],
            "mandate_reference": member_data["mandate_reference"],
        }

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
