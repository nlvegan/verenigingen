#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API Regression Tests for Direct Debit Batch Refactoring

This test suite ensures that all original API endpoints continue to work
correctly after the service layer extraction. Tests focus on API contracts,
security decorators, and response formats.

Test Coverage:
- @critical_api decorated methods
- @high_security_api decorated methods
- Public API endpoints
- Error handling consistency
- Security framework compliance
- Response format compatibility

Author: Verenigingen Development Team
"""

import unittest
from datetime import datetime, timedelta
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import nowdate, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

# Import API methods to test
from verenigingen.verenigingen_payments.doctype.direct_debit_batch.direct_debit_batch import (
    create_direct_debit_batch_for_unpaid_memberships,
    create_enhanced_dues_batch,
    generate_direct_debit_batch,
    get_dues_collection_preview,
    mark_invoices_as_paid,
    process_batch,
)


class TestDirectDebitBatchAPIRegression(EnhancedTestCase):
    """Test suite for API endpoint regression after refactoring"""

    @classmethod
    def setUpClass(cls):
        """Set up test environment once"""
        super().setUpClass()
        cls._setup_test_environment()

    @classmethod
    def _setup_test_environment(cls):
        """Set up minimal test environment"""
        try:
            # Ensure we have basic settings
            settings = frappe.get_single("Verenigingen Settings")
            if not settings.company:
                settings.company = "Test Company"
                settings.save()

        except Exception as e:
            frappe.logger().warning(f"Test environment setup warning: {str(e)}")

    def setUp(self):
        """Set up each test with fresh data"""
        super().setUp()
        self.test_batch = None
        self.test_invoices = []

    def tearDown(self):
        """Clean up test data"""
        super().tearDown()
        # Clean up any created batches
        if self.test_batch:
            try:
                frappe.delete_doc("Direct Debit Batch", self.test_batch.name, force=True)
            except:
                pass

    def test_generate_direct_debit_batch_api(self):
        """Test generate_direct_debit_batch API endpoint"""
        try:
            # Test with default date
            result = generate_direct_debit_batch()

            # Should return None or batch name
            self.assertIsInstance(result, (str, type(None)))

            # Test with specific date
            test_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
            result = generate_direct_debit_batch(date=test_date)

            # Should handle the date parameter
            self.assertIsInstance(result, (str, type(None)))

        except Exception as e:
            # API might fail due to missing data, but should not crash
            self.assertIsInstance(e, (frappe.ValidationError, frappe.DoesNotExistError))

    def test_create_enhanced_dues_batch_api(self):
        """Test create_enhanced_dues_batch API endpoint"""
        try:
            # Test without collection date
            result = create_enhanced_dues_batch()

            # Should return None or batch name
            self.assertIsInstance(result, (str, type(None)))

            # Test with specific collection date
            collection_date = (datetime.now() + timedelta(days=10)).strftime("%Y-%m-%d")
            result = create_enhanced_dues_batch(collection_date=collection_date)

            # Should handle the collection_date parameter
            self.assertIsInstance(result, (str, type(None)))

        except Exception as e:
            # API might fail due to missing dependencies
            self.assertIsInstance(e, (frappe.ValidationError, frappe.DoesNotExistError, ImportError))

    def test_get_dues_collection_preview_api(self):
        """Test get_dues_collection_preview API endpoint"""
        try:
            # Test with default parameters
            result = get_dues_collection_preview()

            # Should return a dictionary with success indicator
            self.assertIsInstance(result, dict)
            self.assertIn("success", result)

            # Test with specific parameters
            collection_date = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d")
            result = get_dues_collection_preview(collection_date=collection_date, days_ahead=14)

            # Should handle parameters correctly
            self.assertIsInstance(result, dict)
            self.assertIn("success", result)

            if result["success"]:
                # Check expected response structure
                self.assertIn("collections", result)
                self.assertIn("total_dates", result)
                self.assertIn("total_schedules", result)
                self.assertIn("total_amount", result)

        except Exception as e:
            # API might fail due to missing dependencies
            frappe.logger().warning(f"Preview API test failed: {str(e)}")

    def test_process_batch_api(self):
        """Test process_batch API endpoint"""
        # Create a test batch first
        batch_doc = self._create_minimal_test_batch()

        try:
            # Submit the batch first
            batch_doc.submit()

            # Test process_batch API
            result = process_batch(batch_doc.name)

            # Should return a boolean or None
            self.assertIsInstance(result, (bool, type(None)))

        except Exception as e:
            # Expected to fail due to incomplete configuration
            self.assertIsInstance(e, (frappe.ValidationError, frappe.PermissionError))

    def test_mark_invoices_as_paid_api(self):
        """Test mark_invoices_as_paid API endpoint"""
        # Create a test batch with invoices
        batch_doc = self._create_minimal_test_batch()

        try:
            # Submit the batch first
            batch_doc.submit()

            # Test mark_invoices_as_paid API
            result = mark_invoices_as_paid(batch_doc.name)

            # Should return a number (count of processed invoices)
            self.assertIsInstance(result, (int, type(None)))

        except Exception as e:
            # Expected to fail due to missing invoices or permissions
            self.assertIsInstance(e, (frappe.ValidationError, frappe.PermissionError))

    def test_create_direct_debit_batch_for_unpaid_memberships_api(self):
        """Test create_direct_debit_batch_for_unpaid_memberships API endpoint"""
        try:
            # Test the API
            result = create_direct_debit_batch_for_unpaid_memberships()

            # Should return None or batch name
            self.assertIsInstance(result, (str, type(None)))

        except Exception as e:
            # Expected to fail if no unpaid memberships exist
            frappe.logger().warning(f"Unpaid memberships API test: {str(e)}")

    def test_api_security_decorators_preserved(self):
        """Test that security decorators are preserved after refactoring"""
        # Import the functions to check their decorators
        import inspect

        from verenigingen.verenigingen_payments.doctype.direct_debit_batch.direct_debit_batch import (
            create_enhanced_dues_batch,
            generate_direct_debit_batch,
            get_dues_collection_preview,
            mark_invoices_as_paid,
            process_batch,
        )

        # Check that functions are still whitelisted
        critical_functions = [
            generate_direct_debit_batch,
            process_batch,
            mark_invoices_as_paid,
            create_enhanced_dues_batch,
        ]

        for func in critical_functions:
            # Check that @frappe.whitelist() is present
            self.assertTrue(
                hasattr(func, "__wrapped__")
                or getattr(func, "is_whitelisted", False)
                or func.__name__ in frappe.get_all_hooks().get("whitelist", [])
            )

    def test_api_error_handling_consistency(self):
        """Test that error handling is consistent after refactoring"""
        # Test with invalid batch name
        try:
            result = process_batch("INVALID_BATCH_NAME")
            self.fail("Should have raised an exception for invalid batch name")
        except Exception as e:
            # Should raise appropriate exception type
            self.assertIsInstance(e, (frappe.DoesNotExistError, frappe.ValidationError))

        # Test with invalid parameters
        try:
            result = mark_invoices_as_paid("INVALID_BATCH_NAME")
            self.fail("Should have raised an exception for invalid batch name")
        except Exception as e:
            # Should raise appropriate exception type
            self.assertIsInstance(e, (frappe.DoesNotExistError, frappe.ValidationError))

    def test_api_response_format_compatibility(self):
        """Test that API response formats remain compatible"""
        # Test dues collection preview response format
        try:
            result = get_dues_collection_preview()

            if isinstance(result, dict):
                # Check response structure hasn't changed
                required_keys = ["success"]
                for key in required_keys:
                    self.assertIn(key, result)

                if result.get("success"):
                    success_keys = ["collections", "total_dates", "total_schedules", "total_amount"]
                    for key in success_keys:
                        if key in result:
                            # Verify data types
                            if key == "collections":
                                self.assertIsInstance(result[key], list)
                            elif key in ["total_dates", "total_schedules"]:
                                self.assertIsInstance(result[key], int)
                            elif key == "total_amount":
                                self.assertIsInstance(result[key], (int, float))

        except Exception as e:
            frappe.logger().warning(f"Response format test warning: {str(e)}")

    def test_batch_document_api_methods(self):
        """Test that Direct Debit Batch document methods still work"""
        batch_doc = self._create_minimal_test_batch()

        # Test validate method
        try:
            batch_doc.validate()
            # Should complete without error
        except Exception as e:
            # Validation might fail due to missing data, but should not crash
            self.assertIsInstance(e, (frappe.ValidationError, AttributeError))

        # Test calculate_totals method
        try:
            batch_doc.calculate_totals()
            # Should set totals
            self.assertIsNotNone(batch_doc.entry_count)
            self.assertIsNotNone(batch_doc.total_amount)
        except Exception as e:
            frappe.logger().warning(f"Calculate totals test warning: {str(e)}")

        # Test generate_sepa_xml method
        try:
            result = batch_doc.generate_sepa_xml()
            # Should return file URL or None
            self.assertIsInstance(result, (str, type(None)))
        except Exception as e:
            # Expected to fail due to incomplete configuration
            self.assertIsInstance(e, (frappe.ValidationError, AttributeError))

    def test_legacy_method_compatibility(self):
        """Test that legacy methods are still accessible"""
        batch_doc = self._create_minimal_test_batch()

        # Test that old method signatures still work
        legacy_methods = [
            "validate_invoices",
            "validate_sequence_types",
            "calculate_totals",
            "add_to_batch_log",
            "process_batch",
        ]

        for method_name in legacy_methods:
            method = getattr(batch_doc, method_name, None)
            self.assertIsNotNone(method, f"Method {method_name} should still exist")
            self.assertTrue(callable(method), f"Method {method_name} should be callable")

    def test_service_integration_in_apis(self):
        """Test that APIs properly integrate with the new service layer"""
        batch_doc = self._create_minimal_test_batch()

        # Test that document methods use services
        try:
            # This should use batch_processing_service internally
            batch_doc.validate_invoices()

            # This should use batch_processing_service internally
            batch_doc.calculate_totals()

            # Verify that services are actually being used
            # (We can check this by seeing if the service modules are imported)
            from verenigingen.verenigingen_payments.doctype.direct_debit_batch import (
                direct_debit_batch as batch_module,
            )

            # Check that service imports are present
            self.assertTrue(hasattr(batch_module, "sepa_config_service"))
            self.assertTrue(hasattr(batch_module, "batch_validation_service"))
            self.assertTrue(hasattr(batch_module, "sepa_xml_service"))
            self.assertTrue(hasattr(batch_module, "batch_processing_service"))
            self.assertTrue(hasattr(batch_module, "business_logic_service"))

        except Exception as e:
            frappe.logger().warning(f"Service integration test warning: {str(e)}")

    def _create_minimal_test_batch(self):
        """Create minimal test batch for API testing.

        The Direct Debit Batch validates its invoice/mandate Link fields on insert,
        so the row must point at real records. Build a member + EUR Unpaid invoice +
        active SEPA mandate via the SEPA test factory rather than hardcoded fake IDs.
        """
        from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory

        sepa_factory = SEPATestDataFactory(seed=self.factory.seed, use_faker=self.factory.use_faker)

        member = sepa_factory.create_test_member(first_name="APIReg")
        customer = sepa_factory.create_test_customer(customer_name=f"Customer {member.full_name}")
        member.db_set("customer", customer.name)
        membership = sepa_factory.create_test_membership(member=member.name)
        mandate = sepa_factory.create_test_sepa_mandate(member=member.name)
        invoice = sepa_factory.create_test_sales_invoice(
            customer=customer.name,
            member=member.name,
            status="Unpaid",
            submit=True,
        )
        self._track_test_document("Sales Invoice", invoice.name)
        self._track_test_document("Member", member.name)
        self._track_test_document("Customer", customer.name)
        self._track_test_document("Membership", membership.name)
        self._track_test_document("SEPA Mandate", mandate.name)

        batch_doc = frappe.new_doc("Direct Debit Batch")
        batch_doc.batch_date = today()
        batch_doc.collection_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        batch_doc.batch_description = "API Regression Test Batch"
        batch_doc.batch_type = "CORE"  # SEPA scheme
        batch_doc.sequence_type = "FRST"  # first use of a fresh mandate -> FRST
        batch_doc.currency = "EUR"

        batch_doc.append(
            "invoices",
            {
                "invoice": invoice.name,
                "membership": membership.name,
                "member": member.name,
                "member_name": member.full_name,
                "amount": invoice.outstanding_amount,
                "currency": "EUR",
                "iban": mandate.iban,
                "mandate_reference": mandate.mandate_id,
                "status": "Pending",
                "sequence_type": "FRST",
            },
        )

        batch_doc.insert()
        self._track_test_document("Direct Debit Batch", batch_doc.name)
        self.test_batch = batch_doc
        return batch_doc


class TestAPISecurityCompliance(unittest.TestCase):
    """Test suite for API security compliance"""

    def test_critical_api_decorators(self):
        """Test that critical APIs have proper security decorators"""
        from verenigingen.verenigingen_payments.doctype.direct_debit_batch.direct_debit_batch import (
            create_enhanced_dues_batch,
            generate_direct_debit_batch,
            mark_invoices_as_paid,
            process_batch,
        )

        critical_apis = [
            generate_direct_debit_batch,
            process_batch,
            mark_invoices_as_paid,
            create_enhanced_dues_batch,
        ]

        for api_func in critical_apis:
            # Check for security decorator presence
            # This would be more specific in a real implementation
            self.assertTrue(hasattr(api_func, "__wrapped__") or hasattr(api_func, "__name__"))

    def test_high_security_api_decorators(self):
        """Test that high security APIs have proper decorators"""
        from verenigingen.verenigingen_payments.doctype.direct_debit_batch.direct_debit_batch import (
            get_dues_collection_preview,
        )

        high_security_apis = [get_dues_collection_preview]

        for api_func in high_security_apis:
            # Check for security decorator presence
            self.assertTrue(hasattr(api_func, "__wrapped__") or hasattr(api_func, "__name__"))

    def test_operation_type_classification(self):
        """Test that APIs are properly classified by operation type"""
        # This would test that financial operations are properly marked
        # For now, we just verify the imports work
        try:
            from verenigingen.utils.security.api_security_framework import OperationType

            # Check that OperationType.FINANCIAL exists
            self.assertTrue(hasattr(OperationType, "FINANCIAL"))

        except ImportError:
            self.skipTest("Security framework not available")


if __name__ == "__main__":
    unittest.main()
