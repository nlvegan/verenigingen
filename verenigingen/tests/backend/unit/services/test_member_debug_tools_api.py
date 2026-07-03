# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Unit tests for Member Debug Tools API

Tests member debugging utility API endpoints.

These endpoints are whitelisted and wrapped by @development_only_api, whose shared
decorator serializes the OperationResult return via to_dict(scrub_sensitive=True)
at the API boundary. So callers (including these in-process tests) receive the
nested dict schema: {"success", "timestamp", "data"|"error": {"message","errors"},
"meta"} -- not the OperationResult object. Assertions read those dict keys.
"""

import frappe
from verenigingen.services.member.testing.member_debug_tools import (
    debug_button_conditions,
    debug_member_id_assignment,
    debug_member_status,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
import unittest


class TestMemberDebugToolsAPI(EnhancedTestCase):
    """Unit tests for Member Debug Tools API endpoints"""

    _orig_developer_mode = False  # sentinel: "not set" (distinct from None/0/1)

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        # Create a test member for debugging
        self.test_member = self.create_test_member(
            first_name="DebugTools",
            last_name="TestMember"
        )
        # These endpoints are @development_only_api, blocked unless the environment
        # resolves to DEVELOPMENT. CI runs without developer_mode (→ PRODUCTION), so
        # enable it for the duration of the test and restore it in tearDown. Set it
        # last so a failure earlier in setUp can never leak the conf change.
        self._orig_developer_mode = frappe.conf.get("developer_mode")
        frappe.conf["developer_mode"] = 1

    def tearDown(self):
        if self._orig_developer_mode is not False:
            if self._orig_developer_mode is None:
                frappe.conf.pop("developer_mode", None)
            else:
                frappe.conf["developer_mode"] = self._orig_developer_mode
            self._orig_developer_mode = False
        super().tearDown()

    def test_debug_button_conditions_returns_operation_result(self):
        """Test debug_button_conditions returns OperationResult"""
        result = debug_button_conditions(self.test_member.name)

        # OperationResult pattern
        self.assertIsNotNone(result)
        self.assertIsNotNone(result["success"])

        if result["success"]:
            self.assertIsInstance(result["data"], dict)
            self.assertIn("has_customer", result["data"])
            self.assertIn("has_user", result["data"])
            self.assertIn("debug_completed", result["data"])

    def test_debug_button_conditions_with_invalid_member(self):
        """Test debug_button_conditions with non-existent member"""
        result = debug_button_conditions("INVALID_MEMBER_NAME")

        # Should fail gracefully
        self.assertFalse(result["success"])
        self.assertIsNotNone(result["error"]["message"])

    def test_debug_member_id_assignment_returns_operation_result(self):
        """Test debug_member_id_assignment returns OperationResult"""
        result = debug_member_id_assignment(self.test_member.name)

        # OperationResult pattern
        self.assertIsNotNone(result)
        self.assertIsNotNone(result["success"])

        if result["success"]:
            self.assertIsInstance(result["data"], dict)
            self.assertIn("member_name", result["data"])
            self.assertIn("has_member_id", result["data"])
            self.assertIn("can_assign_id", result["data"])

    def test_debug_member_id_assignment_with_invalid_member(self):
        """Test debug_member_id_assignment with non-existent member"""
        result = debug_member_id_assignment("INVALID_MEMBER_NAME")

        # Should fail gracefully
        self.assertFalse(result["success"])
        self.assertIsNotNone(result["error"]["message"])

    def test_debug_member_status_returns_operation_result(self):
        """Test debug_member_status returns OperationResult"""
        result = debug_member_status(self.test_member.name)

        # OperationResult pattern
        self.assertIsNotNone(result)
        self.assertIsNotNone(result["success"])

        if result["success"]:
            self.assertIsInstance(result["data"], dict)
            self.assertIn("name", result["data"])
            self.assertIn("status", result["data"])
            self.assertIn("docstatus", result["data"])

    def test_debug_member_status_with_invalid_member(self):
        """Test debug_member_status with non-existent member"""
        result = debug_member_status("INVALID_MEMBER_NAME")

        # Should fail gracefully
        self.assertFalse(result["success"])
        self.assertIsNotNone(result["error"]["message"])

    def test_debug_apis_never_throw_exceptions(self):
        """Test that debug APIs never throw exceptions"""
        # Test with various inputs
        apis_to_test = [
            (debug_button_conditions, (self.test_member.name,)),
            (debug_button_conditions, ("INVALID_MEMBER",)),
            (debug_member_id_assignment, (self.test_member.name,)),
            (debug_member_id_assignment, ("INVALID_MEMBER",)),
            (debug_member_status, (self.test_member.name,)),
            (debug_member_status, ("INVALID_MEMBER",)),
        ]

        for api_func, args in apis_to_test:
            result = api_func(*args)
            self.assertIsNotNone(result, f"{api_func.__name__} returned None")
            self.assertIsNotNone(result["success"], f"{api_func.__name__} missing success attribute")

    def test_api_results_contain_proper_metadata(self):
        """Test that API results contain expected metadata structure"""
        result = debug_button_conditions(self.test_member.name)

        # Check OperationResult structure
        self.assertIsNotNone(result)
        if result["success"]:
            self.assertIsInstance(result["data"], dict)
        else:
            self.assertIsNotNone(result["error"]["message"])
            self.assertIsInstance(result["error"]["errors"], list)

    def test_debug_button_conditions_contains_all_flags(self):
        """Test that debug_button_conditions returns all expected flags"""
        result = debug_button_conditions(self.test_member.name)

        if result["success"]:
            expected_flags = [
                "has_customer",
                "has_user",
                "has_email",
                "has_volunteer",
                "has_active_membership",
                "has_donor",
                "debug_completed",
            ]
            for flag in expected_flags:
                self.assertIn(flag, result["data"])


def run_tests():
    """Helper function to run tests from console"""
    frappe.flags.in_test = True
    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestMemberDebugToolsAPI)
    unittest.TextTestRunner(verbosity=2).run(suite)
