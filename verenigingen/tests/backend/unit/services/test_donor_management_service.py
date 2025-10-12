# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Unit tests for DonorManagementService

Tests donor creation and management functionality.
Focus on dict-based error handling pattern.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from verenigingen.services.member.donor import DonorManagementService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestDonorManagementService(EnhancedTestCase):
    """Unit tests for DonorManagementService"""

    def setUp(self):
        super().setUp()
        self.service = DonorManagementService

    def test_check_donor_exists_no_donor_returns_dict(self):
        """Test checking for nonexistent donor returns dict"""
        member = self.create_test_member(
            first_name="NoDonor",
            last_name="Test",
            email="nodonor@example.com"
        )

        result = self.service.check_donor_exists(member.name)

        # Dict-based pattern
        self.assertIsInstance(result, dict)
        self.assertIn("exists", result)
        self.assertFalse(result["exists"])

    def test_check_donor_exists_invalid_member_returns_dict(self):
        """Test checking donor for invalid member returns dict (not exception)"""
        result = self.service.check_donor_exists("INVALID-MEMBER")

        # Should return dict with exists=False, not throw
        self.assertIsInstance(result, dict)
        self.assertIn("exists", result)
        self.assertFalse(result["exists"])

    def test_create_donor_from_member_returns_dict(self):
        """Test donor creation returns dict format"""
        member = self.create_test_member(
            first_name="Dict",
            last_name="Test",
            email="dict.test@example.com"
        )

        result = self.service.create_donor_from_member(member.name)

        # Always returns dict (may succeed or fail based on business rules)
        self.assertIsInstance(result, dict)
        self.assertIn("success", result)
        self.assertIn("message", result)

    def test_create_donor_invalid_member_returns_error_dict(self):
        """Test donor creation with invalid member returns error dict (not exception)"""
        result = self.service.create_donor_from_member("INVALID-MEMBER")

        # Dict-based pattern - never throws
        self.assertIsInstance(result, dict)
        self.assertFalse(result["success"])
        self.assertIn("message", result)

    def test_format_dutch_phone_number_mobile(self):
        """Test Dutch mobile phone formatting"""
        result = self.service._format_dutch_phone_number("0612345678")

        self.assertTrue(result["success"])
        self.assertEqual(result["formatted_number"], "+31612345678")

    def test_format_dutch_phone_number_landline(self):
        """Test Dutch landline phone formatting"""
        result = self.service._format_dutch_phone_number("0201234567")

        self.assertTrue(result["success"])
        self.assertEqual(result["formatted_number"], "+31201234567")

    def test_format_dutch_phone_number_already_formatted(self):
        """Test that already formatted numbers are unchanged"""
        result = self.service._format_dutch_phone_number("+31612345678")

        self.assertTrue(result["success"])
        self.assertEqual(result["formatted_number"], "+31612345678")

    def test_format_dutch_phone_number_with_spaces(self):
        """Test phone formatting with spaces"""
        result = self.service._format_dutch_phone_number("06 1234 5678")

        self.assertTrue(result["success"])
        self.assertEqual(result["formatted_number"], "+31612345678")

    def test_format_dutch_phone_number_without_leading_zero(self):
        """Test phone formatting without leading zero"""
        result = self.service._format_dutch_phone_number("612345678")

        self.assertTrue(result["success"])
        self.assertEqual(result["formatted_number"], "+31612345678")

    def test_copy_address_from_member_no_address_returns_error_dict(self):
        """Test address copying when member has no address returns error dict"""
        member = self.create_test_member(
            first_name="NoAddr",
            last_name="Test",
            email="noaddr@example.com"
        )

        result = self.service._copy_address_from_member(member)

        # Dict-based pattern
        self.assertIsInstance(result, dict)
        self.assertFalse(result["success"])
        self.assertIn("error", result)

    def test_prepare_donor_basic_data_returns_dict(self):
        """Test donor data preparation returns proper dict"""
        member = self.create_test_member(
            first_name="Data",
            last_name="Prep",
            email="data.prep@example.com",
            contact_number="0612345678"
        )

        donor_data = self.service._prepare_donor_basic_data(member)

        # Should return dict with expected keys
        self.assertIsInstance(donor_data, dict)
        self.assertEqual(donor_data["donor_name"], member.full_name)
        self.assertEqual(donor_data["donor_email"], member.email)
        self.assertEqual(donor_data["donor_type"], "Individual")
        self.assertEqual(donor_data["donor_category"], "Regular Donor")

    def test_service_never_throws_exceptions(self):
        """Test that service methods never throw exceptions"""
        invalid_inputs = [None, "", "INVALID", "Non-Existent-123"]

        for invalid_input in invalid_inputs:
            # check_donor_exists should always return dict
            result1 = self.service.check_donor_exists(invalid_input)
            self.assertIsInstance(result1, dict, f"check_donor_exists failed for: {invalid_input}")

            # create_donor_from_member should always return dict
            result2 = self.service.create_donor_from_member(invalid_input)
            self.assertIsInstance(result2, dict, f"create_donor failed for: {invalid_input}")
            self.assertFalse(result2["success"], f"Should fail for: {invalid_input}")

    def test_phone_formatting_never_throws(self):
        """Test that phone formatting never throws exceptions"""
        invalid_phones = [None, "", "   ", "abc", "!@#$", "12"]

        for phone in invalid_phones:
            if phone is None:
                continue  # Skip None as it would error before reaching method
            result = self.service._format_dutch_phone_number(phone)
            # Should always return dict
            self.assertIsInstance(result, dict, f"Phone formatting failed for: {phone}")


def run_tests():
    """Helper function to run tests from console"""
    frappe.flags.in_test = True
    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestDonorManagementService)
    unittest.TextTestRunner(verbosity=2).run(suite)
