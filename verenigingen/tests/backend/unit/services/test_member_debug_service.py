# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Unit tests for MemberDebugService

Tests diagnostic and debugging utilities.
Focus on dict-based error handling pattern (debug utilities never throw).
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today
from verenigingen.services.member.debug import MemberDebugService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMemberDebugService(EnhancedTestCase):
    """Unit tests for MemberDebugService"""

    def setUp(self):
        super().setUp()
        self.service = MemberDebugService

    def test_debug_member_status_basic_returns_dict(self):
        """Test basic member status debugging returns dict"""
        member = self.create_test_member(first_name="Debug", last_name="Test")

        result = self.service.debug_member_status(member.name)

        # Always returns dict
        self.assertIsInstance(result, dict)
        self.assertIn("name", result)
        self.assertIn("status", result)
        self.assertIn("docstatus", result)

    def test_debug_member_status_invalid_member_returns_error_dict(self):
        """Test debug status with invalid member returns error dict (not exception)"""
        result = self.service.debug_member_status("INVALID-MEMBER")

        # Debug utilities NEVER throw
        self.assertIsInstance(result, dict)
        self.assertIn("error", result)

    def test_debug_button_conditions_returns_dict(self):
        """Test button conditions debugging returns dict"""
        member = self.create_test_member(
            first_name="Buttons",
            last_name="Test",
            email="buttons.test@example.com"
        )

        result = self.service.debug_button_conditions(member.name)

        # Always returns dict with expected structure
        self.assertIsInstance(result, dict)
        self.assertIn("member_name", result)
        self.assertIn("has_customer", result)
        self.assertIn("has_user", result)
        self.assertIn("expected_buttons", result)
        self.assertIsInstance(result["expected_buttons"], dict)

    def test_debug_button_conditions_invalid_member_returns_error_dict(self):
        """Test button conditions with invalid member returns error dict"""
        result = self.service.debug_button_conditions("INVALID-MEMBER")

        self.assertIsInstance(result, dict)
        self.assertIn("error", result)

    def test_test_dues_schedule_query_returns_dict(self):
        """Test dues schedule query returns dict"""
        member = self.create_test_member(first_name="Dues", last_name="Test")

        result = self.service.test_dues_schedule_query(member.name)

        # Should return dict with query results
        self.assertIsInstance(result, dict)
        self.assertIn("filters_used", result)
        # May have query_result or error, but always a dict

    def test_test_dues_schedule_query_invalid_member_returns_dict(self):
        """Test dues schedule query with invalid member returns dict"""
        result = self.service.test_dues_schedule_query("INVALID-MEMBER")

        # Should still return dict (may have error or empty result)
        self.assertIsInstance(result, dict)
        self.assertIn("filters_used", result)

    def test_debug_service_never_throws_exceptions(self):
        """Test that debug service never throws exceptions - always returns dicts"""
        # Test with various invalid inputs - should always return error dicts
        invalid_inputs = [None, "", "INVALID", "Non-Existent-Member-789"]

        for invalid_input in invalid_inputs:
            # debug_member_status
            result1 = self.service.debug_member_status(invalid_input)
            self.assertIsInstance(result1, dict, f"debug_member_status failed for: {invalid_input}")

            # debug_button_conditions
            result2 = self.service.debug_button_conditions(invalid_input)
            self.assertIsInstance(result2, dict, f"debug_button_conditions failed for: {invalid_input}")

            # test_dues_schedule_query
            result3 = self.service.test_dues_schedule_query(invalid_input)
            self.assertIsInstance(result3, dict, f"test_dues_schedule_query failed for: {invalid_input}")

    def test_debug_member_status_returns_expected_fields(self):
        """Test that debug_member_status returns all expected fields"""
        member = self.create_test_member(
            first_name="Fields",
            last_name="Test",
            email="fields.test@example.com"
        )

        result = self.service.debug_member_status(member.name)

        # Check all expected fields are present
        expected_fields = ["name", "status", "application_status", "customer", "user", "docstatus", "payment_method"]
        for field in expected_fields:
            self.assertIn(field, result, f"Missing expected field: {field}")

    def test_dues_schedule_query_filters_structure(self):
        """Test that dues schedule query uses correct filters structure"""
        member = self.create_test_member(first_name="Filters", last_name="Test")

        result = self.service.test_dues_schedule_query(member.name)

        # Check filters structure
        self.assertIn("filters_used", result)
        filters = result["filters_used"]
        self.assertIsInstance(filters, dict)
        self.assertEqual(filters["member"], member.name)
        self.assertEqual(filters["is_template"], 0)

    def test_button_conditions_with_email(self):
        """Test button conditions for member with email"""
        member = self.create_test_member(
            first_name="WithEmail",
            last_name="Test",
            email="withemail@test.com"
        )

        result = self.service.debug_button_conditions(member.name)

        # Should return dict with has_email=True
        self.assertIsInstance(result, dict)
        if "has_email" in result:
            self.assertTrue(result["has_email"])

    def test_debug_utilities_safe_for_development(self):
        """Test that debug utilities are safe for exploratory use"""
        # Create various test scenarios
        valid_member = self.create_test_member(first_name="Valid", last_name="Dev")

        # All of these should work without throwing
        results = [
            self.service.debug_member_status(valid_member.name),
            self.service.debug_member_status("INVALID"),
            self.service.debug_button_conditions(valid_member.name),
            self.service.debug_button_conditions("INVALID"),
            self.service.test_dues_schedule_query(valid_member.name),
            self.service.test_dues_schedule_query("INVALID"),
        ]

        # All should be dicts
        for result in results:
            self.assertIsInstance(result, dict, "Debug utility returned non-dict")


def run_tests():
    """Helper function to run tests from console"""
    frappe.flags.in_test = True
    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestMemberDebugService)
    unittest.TextTestRunner(verbosity=2).run(suite)
