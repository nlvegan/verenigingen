# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Unit tests for SEPA Mandate API Endpoints

Tests SEPA mandate API endpoints with OperationResult pattern.
Focus on critical financial operations with type-safe error handling.

Migration Status: ✅ COMPLETE (2025-11-24)
- All tests use OperationResult API
- Proper assertions for .success, .data, .error_message
- Type-safe test patterns for critical financial APIs
"""

import frappe
from frappe.utils import random_string
from verenigingen.services.payment.sepa_mandate_manager import (
    validate_mandate_creation_api,
    create_mandate_api,
    deactivate_mandates_for_iban_change_api,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestSEPAMandateAPI(EnhancedTestCase):
    """Unit tests for SEPA Mandate API endpoints"""

    def setUp(self):
        super().setUp()
        # Set user to Administrator for SEPA operations
        frappe.set_user("Administrator")

    def test_validate_mandate_creation_api_returns_operation_result(self):
        """Test validate_mandate_creation_api returns OperationResult"""
        unique_email = f"validate.sepa.{random_string(8).lower()}@example.com"
        member = self.create_test_member(
            first_name="Validate",
            last_name="SEPA",
            email=unique_email
        )

        result = validate_mandate_creation_api(
            member=member.name,
            iban="NL91ABNA0417164300",
            mandate_id="TEST-001"
        )

        # OperationResult pattern
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.success)

    def test_validate_mandate_creation_api_with_invalid_iban_returns_failed_result(self):
        """Test validation with invalid IBAN returns failed OperationResult"""
        unique_email = f"invalid.iban.{random_string(8).lower()}@example.com"
        member = self.create_test_member(
            first_name="Invalid",
            last_name="IBAN",
            email=unique_email
        )

        result = validate_mandate_creation_api(
            member=member.name,
            iban="INVALID",
            mandate_id="TEST-002"
        )

        # Should fail gracefully
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error_message)

    def test_create_mandate_api_returns_operation_result(self):
        """Test create_mandate_api returns OperationResult"""
        unique_email = f"create.sepa.{random_string(8).lower()}@example.com"
        member = self.create_test_member(
            first_name="Create",
            last_name="SEPA",
            email=unique_email
        )

        result = create_mandate_api(
            member=member.name,
            iban="NL91ABNA0417164300",
            bic="ABNANL2A",
            account_holder_name="Create SEPA"
        )

        # OperationResult pattern
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.success)

    def test_create_mandate_api_with_invalid_member_returns_failed_result(self):
        """Test mandate creation with invalid member returns failed OperationResult"""
        result = create_mandate_api(
            member="INVALID-MEMBER",
            iban="NL91ABNA0417164300"
        )

        # Should fail gracefully
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error_message)

    def test_deactivate_mandates_for_iban_change_api_returns_operation_result(self):
        """Test deactivate_mandates_for_iban_change_api returns OperationResult"""
        unique_email = f"deactivate.sepa.{random_string(8).lower()}@example.com"
        member = self.create_test_member(
            first_name="Deactivate",
            last_name="SEPA",
            email=unique_email
        )

        result = deactivate_mandates_for_iban_change_api(
            member=member.name,
            new_iban="NL20INGB0001234567"
        )

        # OperationResult pattern
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.success)

    def test_sepa_apis_never_throw_exceptions(self):
        """Test that SEPA APIs never throw exceptions"""
        # Test with various invalid inputs
        invalid_tests = [
            ("", "NL91ABNA0417164300", "TEST"),
            ("INVALID", "", "TEST"),
            ("INVALID", "INVALID", ""),
        ]

        for member, iban, mandate_id in invalid_tests:
            # validate_mandate_creation_api
            result1 = validate_mandate_creation_api(member, iban, mandate_id)
            self.assertIsNotNone(result1)
            self.assertIsNotNone(result1.success)

            # create_mandate_api
            result2 = create_mandate_api(member, iban)
            self.assertIsNotNone(result2)
            self.assertIsNotNone(result2.success)

            # deactivate_mandates_for_iban_change_api
            result3 = deactivate_mandates_for_iban_change_api(member, iban)
            self.assertIsNotNone(result3)
            self.assertIsNotNone(result3.success)

    def test_api_results_contain_proper_metadata(self):
        """Test that API results contain expected metadata structure"""
        unique_email = f"metadata.sepa.{random_string(8).lower()}@example.com"
        member = self.create_test_member(
            first_name="Metadata",
            last_name="SEPA",
            email=unique_email
        )

        # Test validate API
        result1 = validate_mandate_creation_api(
            member=member.name,
            iban="NL91ABNA0417164300",
            mandate_id="TEST-META"
        )

        # Should have OperationResult structure
        self.assertIsNotNone(result1)
        if result1.success:
            self.assertIsInstance(result1.data, dict)
        else:
            self.assertIsNotNone(result1.error_message)
            self.assertIsInstance(result1.errors, list)


def run_tests():
    """Helper function to run tests from console"""
    frappe.flags.in_test = True
    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestSEPAMandateAPI)
    unittest.TextTestRunner(verbosity=2).run(suite)
