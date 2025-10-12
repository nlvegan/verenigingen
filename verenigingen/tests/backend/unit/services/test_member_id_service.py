# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Unit tests for MemberIDService

Tests member ID assignment and management functionality.
Focus on dict-based error handling pattern.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from verenigingen.services.member.identification import MemberIDService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMemberIDService(EnhancedTestCase):
    """Unit tests for MemberIDService"""

    def setUp(self):
        super().setUp()
        self.service = MemberIDService

    def test_assign_member_id_empty_name_returns_dict(self):
        """Test that empty member name returns error dict (not exception)"""
        result = self.service.assign_member_id("")

        # Dict-based pattern validation
        self.assertIsInstance(result, dict)
        self.assertFalse(result["success"])
        self.assertIn("message", result)

    def test_assign_member_id_none_name_returns_dict(self):
        """Test that None member name returns error dict (not exception)"""
        result = self.service.assign_member_id(None)

        self.assertIsInstance(result, dict)
        self.assertFalse(result["success"])
        self.assertIn("message", result)

    def test_assign_member_id_nonexistent_member_returns_dict(self):
        """Test that nonexistent member returns error dict (not exception)"""
        result = self.service.assign_member_id("INVALID-MEMBER-NAME")

        # This is the key test - service NEVER throws, always returns dict
        self.assertIsInstance(result, dict)
        self.assertFalse(result["success"])
        self.assertIn("message", result)

    def test_assign_member_id_returns_success_dict_format(self):
        """Test that successful assignment returns proper dict format"""
        member = self.create_test_member(first_name="Test", last_name="Member")

        result = self.service.assign_member_id(member.name)

        # Should return dict with these keys (may succeed or fail based on business rules)
        self.assertIsInstance(result, dict)
        self.assertIn("success", result)
        self.assertIn("message", result)

        # If successful, should have member_id
        if result["success"]:
            self.assertIn("member_id", result)

    def test_assign_missing_member_ids_returns_dict(self):
        """Test bulk assignment returns dict with proper structure"""
        result = self.service.assign_missing_member_ids()

        # Dict-based pattern
        self.assertIsInstance(result, dict)
        self.assertIn("success", result)
        self.assertIn("total_checked", result)
        self.assertIn("assigned", result)
        self.assertIn("message", result)

    def test_debug_member_id_assignment_returns_dict(self):
        """Test debug utility returns dict (never throws)"""
        member = self.create_test_member(first_name="Debug", last_name="Test")

        result = self.service.debug_member_id_assignment(member.name)

        # Debug utilities always return dict
        self.assertIsInstance(result, dict)
        self.assertIn("member_name", result)

    def test_debug_member_id_assignment_invalid_member_returns_error_dict(self):
        """Test debug utility with invalid member returns error dict (not exception)"""
        result = self.service.debug_member_id_assignment("INVALID-MEMBER")

        # Debug utilities NEVER throw - this is critical for development use
        self.assertIsInstance(result, dict)
        self.assertIn("error", result)

    def test_service_never_throws_exceptions(self):
        """Test that service never throws exceptions - always returns dicts"""
        # Test with various invalid inputs
        invalid_inputs = [None, "", "INVALID", "   ", "Non-Existent-Member-123"]

        for invalid_input in invalid_inputs:
            result = self.service.assign_member_id(invalid_input)

            # Should always return dict, never throw
            self.assertIsInstance(result, dict, f"Failed for input: {invalid_input}")
            self.assertFalse(result["success"], f"Should fail for input: {invalid_input}")
            self.assertIn("message", result, f"Missing message for input: {invalid_input}")

    def test_bulk_operation_handles_partial_failures(self):
        """Test that bulk operation continues even with failures"""
        result = self.service.assign_missing_member_ids()

        # Bulk operations should have detailed results
        self.assertIsInstance(result, dict)
        self.assertIn("total_checked", result)
        self.assertIn("assigned", result)
        self.assertIn("message", result)

        # total_checked >= assigned (some may not qualify)
        self.assertGreaterEqual(result["total_checked"], result["assigned"])


def run_tests():
    """Helper function to run tests from console"""
    frappe.flags.in_test = True
    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestMemberIDService)
    unittest.TextTestRunner(verbosity=2).run(suite)
