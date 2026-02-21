# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Unit tests for MemberDebugService

Tests diagnostic and debugging utilities.
Focus on OperationResult pattern with type-safe error handling.

Migration Status: ✅ COMPLETE (2025-11-24)
- All tests updated to use OperationResult API
- Proper assertions for .success, .data, .error_message
- Type-safe test patterns
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today
from verenigingen.services.member.debug.member_debug_service import MemberDebugService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
import unittest


class TestMemberDebugService(EnhancedTestCase):
    """Unit tests for MemberDebugService"""

    def setUp(self):
        super().setUp()
        self.service = MemberDebugService()
        # Set user to Administrator for debug operations
        frappe.set_user("Administrator")

    def test_debug_member_status_basic_returns_operation_result(self):
        """Test basic member status debugging returns OperationResult"""
        member = self.create_test_member(first_name="Debug", last_name="Test")

        result = self.service.debug_member_status(member.name)

        # OperationResult pattern
        self.assertTrue(result.success)
        self.assertIsInstance(result.data, dict)
        self.assertIn("name", result.data)
        self.assertIn("status", result.data)
        self.assertIn("docstatus", result.data)

    def test_debug_member_status_invalid_member_returns_failed_result(self):
        """Test debug status with invalid member returns failed OperationResult (not exception)"""
        result = self.service.debug_member_status("INVALID-MEMBER")

        # Debug utilities NEVER throw
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error_message)

    def test_debug_button_conditions_returns_operation_result(self):
        """Test button conditions debugging returns OperationResult"""
        member = self.create_test_member(
            first_name="Buttons",
            last_name="Test",
            email="buttons.test@example.com"
        )

        result = self.service.debug_button_conditions(member.name)

        # OperationResult pattern
        self.assertTrue(result.success)
        self.assertIsInstance(result.data, dict)
        self.assertIn("member_name", result.data)
        self.assertIn("has_customer", result.data)
        self.assertIn("has_user", result.data)
        self.assertIn("expected_buttons", result.data)
        self.assertIsInstance(result.data["expected_buttons"], dict)

    def test_debug_button_conditions_invalid_member_returns_failed_result(self):
        """Test button conditions with invalid member returns failed OperationResult"""
        result = self.service.debug_button_conditions("INVALID-MEMBER")

        self.assertFalse(result.success)
        self.assertIsNotNone(result.error_message)

    def test_test_dues_schedule_query_returns_operation_result(self):
        """Test dues schedule query returns OperationResult"""
        member = self.create_test_member(first_name="Dues", last_name="Test")

        result = self.service.test_dues_schedule_query(member.name)

        # Should return OperationResult with query results
        self.assertTrue(result.success)
        self.assertIsInstance(result.data, dict)
        self.assertIn("filters_used", result.data)

    def test_test_dues_schedule_query_invalid_member_returns_operation_result(self):
        """Test dues schedule query with invalid member returns OperationResult"""
        result = self.service.test_dues_schedule_query("INVALID-MEMBER")

        # Should still return OperationResult (success with empty results or fail)
        self.assertIsNotNone(result)
        self.assertIsInstance(result.data if result.success else result.metadata, dict)

    def test_debug_service_never_throws_exceptions(self):
        """Test that debug service never throws exceptions - always returns OperationResult"""
        # Test with various invalid inputs - should always return failed OperationResult
        invalid_inputs = ["", "INVALID", "Non-Existent-Member-789"]

        for invalid_input in invalid_inputs:
            # debug_member_status
            result1 = self.service.debug_member_status(invalid_input)
            self.assertIsNotNone(result1, f"debug_member_status returned None for: {invalid_input}")

            # debug_button_conditions
            result2 = self.service.debug_button_conditions(invalid_input)
            self.assertIsNotNone(result2, f"debug_button_conditions returned None for: {invalid_input}")

            # test_dues_schedule_query
            result3 = self.service.test_dues_schedule_query(invalid_input)
            self.assertIsNotNone(result3, f"test_dues_schedule_query returned None for: {invalid_input}")

    def test_debug_member_status_returns_expected_fields(self):
        """Test that debug_member_status returns all expected fields"""
        member = self.create_test_member(
            first_name="Fields",
            last_name="Test",
            email="fields.test@example.com"
        )

        result = self.service.debug_member_status(member.name)

        # OperationResult pattern
        self.assertTrue(result.success)

        # Check all expected fields are present
        expected_fields = ["name", "status", "application_status", "customer", "user", "docstatus", "payment_method"]
        for field in expected_fields:
            self.assertIn(field, result.data, f"Missing expected field: {field}")

    def test_dues_schedule_query_filters_structure(self):
        """Test that dues schedule query uses correct filters structure"""
        member = self.create_test_member(first_name="Filters", last_name="Test")

        result = self.service.test_dues_schedule_query(member.name)

        # OperationResult pattern
        self.assertTrue(result.success)

        # Check filters structure
        self.assertIn("filters_used", result.data)
        filters = result.data["filters_used"]
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

        # OperationResult pattern
        self.assertTrue(result.success)
        if "has_email" in result.data:
            self.assertTrue(result.data["has_email"])

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

        # All should be OperationResult
        for result in results:
            self.assertIsNotNone(result, "Debug utility returned None")
            self.assertIsNotNone(result.success, "OperationResult missing success attribute")

    def test_test_amendment_filtering_returns_operation_result(self):
        """Test amendment filtering test returns OperationResult"""
        result = self.service.test_amendment_filtering()

        # Should return OperationResult with test results
        self.assertIsNotNone(result)
        if result.success:
            self.assertIsInstance(result.data, dict)
            self.assertIn("member", result.data)
            self.assertIn("filtered_count", result.data)
            self.assertIn("raw_count", result.data)

    def test_button_conditions_expected_buttons_structure(self):
        """Test that button conditions returns proper expected_buttons structure"""
        member = self.create_test_member(
            first_name="ButtonStruct",
            last_name="Test",
            email="buttonstruct@test.com"
        )

        result = self.service.debug_button_conditions(member.name)

        self.assertTrue(result.success)
        expected_buttons = result.data["expected_buttons"]

        # Check for expected button keys
        expected_button_keys = ["create_customer", "create_user", "create_volunteer", "create_membership", "create_donor"]
        for key in expected_button_keys:
            self.assertIn(key, expected_buttons, f"Missing button key: {key}")
            self.assertIsInstance(expected_buttons[key], bool, f"Button {key} should be boolean")


def run_tests():
    """Helper function to run tests from console"""
    frappe.flags.in_test = True
    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestMemberDebugService)
    unittest.TextTestRunner(verbosity=2).run(suite)
