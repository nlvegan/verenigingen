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

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.sepa_test_configuration import (
    apply_sepa_test_configuration,
    verify_sepa_configuration,
)

# Import API methods to test
from verenigingen.verenigingen_payments.doctype.direct_debit_batch.direct_debit_batch import (
    create_enhanced_dues_batch,
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
        """Set up minimal test environment.

        Fifth instance of the same shape: it set ``company = "Test Company"``, a
        Company that exists on no test site, behind a ``try/except``. It only ever
        looked harmless because the ``if not settings.company`` guard skips the
        write on any warm site, so the failure was reachable exactly where it
        mattered -- a fresh CI site with the field still empty. Now it owns a real
        EUR company, and a failure fails the class.
        """
        cls.eur_company = apply_sepa_test_configuration()

    def setUp(self):
        """Set up each test with fresh data"""
        super().setUp()
        # Re-assert per test: EnhancedTestCase.setUp re-points Verenigingen
        # Settings.company at the ERPNext "_Test Company" on EVERY test method, so
        # setUpClass's configuration is already undone by the time a body runs
        # (#528). Measured, with the other four callers, under "Callers on
        # EnhancedTestCase must re-apply this PER TEST" in
        # tests/support/sepa_test_configuration.
        self._setup_test_environment()
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

    def test_an_ordinary_test_body_runs_under_the_sepa_configuration(self):
        """The property the class-setup test above cannot prove: an ordinary body,
        which applies nothing itself, is running under the configuration.

        This is the pin for the setUp re-assertion. EnhancedTestCase.setUp reverts
        Verenigingen Settings.company to "_Test Company" before every test method
        (#528), so with that line removed this test goes red -- no damage step is
        needed, the harness supplies the damage on every run.
        """
        verify_sepa_configuration(self.eur_company)

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
        """get_dues_collection_preview() never raises to the caller (see its own
        try/except -> {"success": False, "error": ...}), so wrapping the call in a
        try/except that just logs a warning on failure meant this test could silently
        assert nothing at all if anything unexpected happened. Assert the real,
        unconditional contract instead: a dict with success=True and the documented
        collection-summary keys, whose types are load-bearing for callers.
        """
        result = get_dues_collection_preview()
        self.assertIsInstance(result, dict)
        self.assertTrue(result["success"], f"Preview call failed: {result.get('error')}")
        self.assertIn("collections", result)
        self.assertIsInstance(result["collections"], list)
        self.assertIsInstance(result["total_dates"], int)
        self.assertIsInstance(result["total_schedules"], int)
        self.assertIsInstance(result["total_amount"], (int, float))

        # Parameterized call must also succeed and stay internally consistent
        collection_date = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d")
        result = get_dues_collection_preview(collection_date=collection_date, days_ahead=14)
        self.assertTrue(result["success"], f"Preview call failed: {result.get('error')}")
        self.assertEqual(result["total_dates"], len(result["collections"]))

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

    def test_api_security_decorators_preserved(self):
        """Test that @critical_api security decorators are preserved after refactoring.

        `_security_protected` is the real marker the security framework's wrapper sets
        (see api_security_framework.py); checking `hasattr(func, "__name__")` (the
        original assertion here) is vacuously true for any function and would never
        catch a removed decorator.
        """
        from verenigingen.verenigingen_payments.doctype.direct_debit_batch.direct_debit_batch import (
            create_enhanced_dues_batch,
            mark_invoices_as_paid,
            process_batch,
        )

        critical_functions = [
            process_batch,
            mark_invoices_as_paid,
            create_enhanced_dues_batch,
        ]

        for func in critical_functions:
            self.assertTrue(
                getattr(func, "_security_protected", False),
                f"{func.__name__} should be wrapped by a security decorator (_security_protected)",
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
            mark_invoices_as_paid("INVALID_BATCH_NAME")
            self.fail("Should have raised an exception for invalid batch name")
        except Exception as e:
            # Should raise appropriate exception type
            self.assertIsInstance(e, (frappe.DoesNotExistError, frappe.ValidationError))

    def test_api_response_format_compatibility(self):
        """Test that API response formats remain compatible"""
        # Test dues collection preview response format
        result = get_dues_collection_preview()

        self.assertIsInstance(result, dict)
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
        batch_doc.calculate_totals()
        # Should set totals
        self.assertIsNotNone(batch_doc.entry_count)
        self.assertIsNotNone(batch_doc.total_amount)

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

        # This should use batch_processing_service internally
        batch_doc.validate_invoices()

        # This should use batch_processing_service internally
        batch_doc.calculate_totals()

        # Verify that services are actually being used
        # (We can check this by seeing if the service modules are imported)
        from verenigingen.verenigingen_payments.doctype.direct_debit_batch import (
            direct_debit_batch as batch_module,
        )

        # Check that service imports are present. #490: this used to also assert
        # "sepa_config_service" and "batch_validation_service", neither of which
        # direct_debit_batch.py has ever imported -- grep confirms zero
        # occurrences of either name in the module. validate_invoices() and
        # calculate_totals() (exercised above) both delegate to
        # batch_processing_service, and generate_sepa_xml() to sepa_xml_service;
        # those are the two services this module actually integrates with today.
        self.assertTrue(hasattr(batch_module, "sepa_xml_service"))
        self.assertTrue(hasattr(batch_module, "batch_processing_service"))

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
        """Critical (FINANCIAL) APIs must carry the @critical_api security wrapper.

        Rewritten: `hasattr(api_func, "__name__")` is true for every Python function,
        so the original assertion could never fail even if @critical_api were removed.
        """
        from verenigingen.verenigingen_payments.doctype.direct_debit_batch.direct_debit_batch import (
            create_enhanced_dues_batch,
            mark_invoices_as_paid,
            process_batch,
        )

        critical_apis = [
            process_batch,
            mark_invoices_as_paid,
            create_enhanced_dues_batch,
        ]

        for api_func in critical_apis:
            self.assertTrue(
                getattr(api_func, "_security_protected", False),
                f"{api_func.__name__} should be wrapped by @critical_api",
            )

    def test_high_security_api_decorators(self):
        """High-security APIs must carry the @high_security_api security wrapper."""
        from verenigingen.verenigingen_payments.doctype.direct_debit_batch.direct_debit_batch import (
            get_dues_collection_preview,
        )

        high_security_apis = [get_dues_collection_preview]

        for api_func in high_security_apis:
            self.assertTrue(
                getattr(api_func, "_security_protected", False),
                f"{api_func.__name__} should be wrapped by @high_security_api",
            )

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
