# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Unit tests for DonorManagementService

Tests donor creation and management functionality.
Focus on OperationResult pattern with type-safe error handling.

Migration Status: ✅ COMPLETE (2025-11-24)
- All tests updated to use OperationResult API
- Proper assertions for .success, .data, .error_message
- Type-safe test patterns
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from verenigingen.services.member.donor.donor_management_service import DonorManagementService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
import unittest


class TestDonorManagementService(EnhancedTestCase):
    """Unit tests for DonorManagementService"""

    def setUp(self):
        super().setUp()
        self.service = DonorManagementService()
        # Set user to Administrator for donor creation permissions
        frappe.set_user("Administrator")

    def test_check_donor_exists_no_donor_returns_operation_result(self):
        """Test checking for nonexistent donor returns OperationResult with None"""
        member = self.create_test_member(
            first_name="NoDonor",
            last_name="Test",
            email="nodonor@example.com"
        )

        result = self.service.check_donor_exists(member.name)

        # OperationResult pattern
        self.assertTrue(result.success)
        self.assertIsNone(result.data)  # No donor found
        self.assertEqual(result.metadata.get("exists"), False)

    def test_check_donor_exists_invalid_member_returns_success_with_none(self):
        """Test checking donor for invalid member returns success with None (not an error)"""
        result = self.service.check_donor_exists("INVALID-MEMBER")

        # Should return success with None data (member not found is not an error)
        self.assertTrue(result.success)
        self.assertIsNone(result.data)
        self.assertTrue(result.metadata.get("member_not_found"))

    def test_create_donor_from_member_returns_operation_result(self):
        """Test donor creation returns OperationResult"""
        # Use unique email to avoid conflicts from previous test runs
        unique_email = f"dict.test.{frappe.utils.random_string(8).lower()}@example.com"
        member = self.create_test_member(
            first_name="Dict",
            last_name="Test",
            email=unique_email,
            contact_number=""  # No phone number to avoid Donor DocType validation issues
        )

        result = self.service.create_donor_from_member(member.name)

        # OperationResult pattern
        self.assertTrue(result.success, f"Donor creation failed: {result.error_message if not result.success else ''}")
        self.assertIsNotNone(result.data)  # donor_name
        self.assertIn("message", result.metadata)

    def test_create_donor_invalid_member_returns_failed_operation_result(self):
        """Test donor creation with invalid member returns failed OperationResult"""
        result = self.service.create_donor_from_member("INVALID-MEMBER")

        # OperationResult pattern - never throws
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error_message)
        self.assertGreater(len(result.errors), 0)

    def test_format_dutch_phone_number_mobile(self):
        """Test Dutch mobile phone formatting"""
        result = self.service._format_dutch_phone_number("0612345678")

        self.assertTrue(result.success)
        self.assertEqual(result.data, "+31612345678")

    def test_format_dutch_phone_number_landline(self):
        """Test Dutch landline phone formatting"""
        result = self.service._format_dutch_phone_number("0201234567")

        self.assertTrue(result.success)
        self.assertEqual(result.data, "+31201234567")

    def test_format_dutch_phone_number_already_formatted(self):
        """Test that already formatted numbers are unchanged"""
        result = self.service._format_dutch_phone_number("+31612345678")

        self.assertTrue(result.success)
        self.assertEqual(result.data, "+31612345678")

    def test_format_dutch_phone_number_with_spaces(self):
        """Test phone formatting with spaces"""
        result = self.service._format_dutch_phone_number("06 1234 5678")

        self.assertTrue(result.success)
        self.assertEqual(result.data, "+31612345678")

    def test_format_dutch_phone_number_without_leading_zero(self):
        """Test phone formatting without leading zero"""
        result = self.service._format_dutch_phone_number("612345678")

        self.assertTrue(result.success)
        self.assertEqual(result.data, "+31612345678")

    def test_copy_address_from_member_no_address_returns_failed_result(self):
        """Test address copying when member has no address returns failed OperationResult"""
        member = self.create_test_member(
            first_name="NoAddr",
            last_name="Test",
            email="noaddr@example.com"
        )

        result = self.service._copy_address_from_member(member)

        # OperationResult pattern
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error_message)
        self.assertIn("No primary address", result.error_message)

    def test_prepare_donor_basic_data_returns_operation_result(self):
        """Test donor data preparation returns OperationResult with dict data"""
        member = self.create_test_member(
            first_name="Data",
            last_name="Prep",
            email="data.prep@example.com",
            contact_number="0612345678"
        )

        result = self.service._prepare_donor_basic_data(member)

        # OperationResult pattern
        self.assertTrue(result.success)
        self.assertIsInstance(result.data, dict)

        # Validate donor data structure
        donor_data = result.data
        self.assertEqual(donor_data["donor_name"], member.full_name)
        self.assertEqual(donor_data["donor_email"], member.email)
        self.assertEqual(donor_data["donor_type"], "Individual")
        self.assertEqual(donor_data["donor_category"], "Regular Donor")

    def test_service_never_throws_exceptions(self):
        """Test that service methods never throw exceptions"""
        invalid_inputs = [None, "", "INVALID", "Non-Existent-123"]

        for invalid_input in invalid_inputs:
            # Skip None to avoid error before reaching method
            if invalid_input is None:
                continue

            # check_donor_exists should always return OperationResult
            result1 = self.service.check_donor_exists(invalid_input)
            self.assertIsNotNone(result1, f"check_donor_exists returned None for: {invalid_input}")
            self.assertIsNotNone(result1.success, f"OperationResult missing success for: {invalid_input}")

            # create_donor_from_member should always return OperationResult
            result2 = self.service.create_donor_from_member(invalid_input)
            self.assertIsNotNone(result2, f"create_donor returned None for: {invalid_input}")
            self.assertFalse(result2.success, f"Should fail for: {invalid_input}")

    def test_phone_formatting_never_throws(self):
        """Test that phone formatting never throws exceptions"""
        invalid_phones = [None, "", "   ", "abc", "!@#$", "12"]

        for phone in invalid_phones:
            if phone is None:
                continue  # Skip None as it would error before reaching method
            result = self.service._format_dutch_phone_number(phone)
            # Should always return OperationResult
            self.assertIsNotNone(result, f"Phone formatting returned None for: {phone}")
            self.assertIsNotNone(result.success, f"OperationResult missing success for: {phone}")

    def test_check_donor_exists_with_existing_donor(self):
        """Test check_donor_exists returns donor info when donor exists"""
        # Use unique email to avoid conflicts
        unique_email = f"hasdonor.{frappe.utils.random_string(8).lower()}@example.com"
        # Create member
        member = self.create_test_member(
            first_name="HasDonor",
            last_name="Test",
            email=unique_email,
            contact_number=""  # No phone to avoid validation issues
        )

        # Create donor first
        create_result = self.service.create_donor_from_member(member.name)
        self.assertTrue(create_result.success, f"Donor creation failed: {create_result.error_message if not create_result.success else ''}")

        # Now check if donor exists
        check_result = self.service.check_donor_exists(member.name)

        self.assertTrue(check_result.success)
        self.assertIsNotNone(check_result.data)
        self.assertIn("donor_name", check_result.data)
        self.assertIn("donor_display_name", check_result.data)
        self.assertEqual(check_result.metadata.get("exists"), True)

    def test_create_donor_duplicate_returns_failed_result(self):
        """Test creating duplicate donor returns failed OperationResult"""
        # Use unique email to avoid conflicts
        unique_email = f"duplicate.{frappe.utils.random_string(8).lower()}@example.com"
        member = self.create_test_member(
            first_name="Duplicate",
            last_name="Test",
            email=unique_email,
            contact_number=""  # No phone to avoid validation issues
        )

        # Create donor first time
        result1 = self.service.create_donor_from_member(member.name)
        self.assertTrue(result1.success, f"Donor creation failed: {result1.error_message if not result1.success else ''}")

        # Try to create again (should fail)
        result2 = self.service.create_donor_from_member(member.name)
        self.assertFalse(result2.success)
        self.assertIn("already exists", result2.error_message.lower())


def run_tests():
    """Helper function to run tests from console"""
    frappe.flags.in_test = True
    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestDonorManagementService)
    unittest.TextTestRunner(verbosity=2).run(suite)
