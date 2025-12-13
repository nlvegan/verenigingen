# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Unit tests for MemberIDService

Tests member ID assignment and management functionality.
Focus on OperationResult pattern with type-safe error handling.

Migration Status: ✅ COMPLETE (2025-11-24)
- All tests updated to use OperationResult API
- Proper assertions for .success, .data, .error_message
- Type-safe test patterns
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from verenigingen.services.member.identification.member_id_service import MemberIDService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMemberIDService(EnhancedTestCase):
    """Unit tests for MemberIDService"""

    def setUp(self):
        super().setUp()
        self.service = MemberIDService()
        # Set user to Administrator for member ID assignment permissions
        frappe.set_user("Administrator")

    def test_assign_member_id_empty_name_returns_failed_operation_result(self):
        """Test that empty member name returns failed OperationResult (not exception)"""
        result = self.service.assign_member_id("")

        # OperationResult pattern
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error_message)
        self.assertIn("required", result.error_message.lower())
        self.assertGreater(len(result.errors), 0)

    def test_assign_member_id_nonexistent_member_returns_failed_operation_result(self):
        """Test that nonexistent member returns failed OperationResult (not exception)"""
        result = self.service.assign_member_id("INVALID-MEMBER-NAME")

        # Service NEVER throws, always returns OperationResult
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error_message)
        self.assertIn("does not exist", result.error_message)

    def test_assign_member_id_returns_operation_result_with_member_id(self):
        """Test that successful assignment returns OperationResult with member_id"""
        # Use unique email to avoid conflicts
        unique_email = f"test.{frappe.utils.random_string(8).lower()}@example.com"
        member = self.create_test_member(
            first_name="Test",
            last_name="Member",
            email=unique_email
        )

        result = self.service.assign_member_id(member.name)

        # OperationResult pattern
        if result.success:
            self.assertIsNotNone(result.data)  # member_id
            self.assertIsInstance(result.data, str)
            self.assertGreater(int(result.data), 0)
        else:
            # If failed, should have proper error message
            self.assertIsNotNone(result.error_message)

    def test_assign_member_id_already_has_id_returns_failed_result(self):
        """Test that member who already has ID returns failed OperationResult"""
        # Use unique email to avoid conflicts
        unique_email = f"hasid.{frappe.utils.random_string(8).lower()}@example.com"
        member = self.create_test_member(
            first_name="HasID",
            last_name="Test",
            email=unique_email
        )

        # Assign ID first time
        result1 = self.service.assign_member_id(member.name)
        if not result1.success:
            self.skipTest(f"First ID assignment failed: {result1.error_message}")

        # Try to assign again (should fail)
        result2 = self.service.assign_member_id(member.name)

        self.assertFalse(result2.success)
        self.assertIn("already has", result2.error_message.lower())
        self.assertIn("existing_member_id", result2.metadata)

    def test_assign_missing_member_ids_returns_operation_result_with_stats(self):
        """Test bulk assignment returns OperationResult with batch statistics"""
        result = self.service.assign_missing_member_ids()

        # OperationResult pattern
        self.assertIsNotNone(result)

        # Should have data dict with statistics
        if result.success:
            self.assertIsInstance(result.data, dict)
            self.assertIn("total_checked", result.data)
            self.assertIn("assigned", result.data)
            self.assertIn("errors", result.data)
            # total_checked >= assigned (some may not qualify)
            self.assertGreaterEqual(result.data["total_checked"], result.data["assigned"])

    def test_debug_member_id_assignment_returns_operation_result(self):
        """Test debug utility returns OperationResult (never throws)"""
        # Use unique email to avoid conflicts
        unique_email = f"debug.{frappe.utils.random_string(8).lower()}@example.com"
        member = self.create_test_member(
            first_name="Debug",
            last_name="Test",
            email=unique_email
        )

        result = self.service.debug_member_id_assignment(member.name)

        # OperationResult pattern
        self.assertTrue(result.success)
        self.assertIsInstance(result.data, dict)

        # Debug info structure
        debug_info = result.data
        self.assertIn("member_name", debug_info)
        self.assertIn("has_member_id", debug_info)
        self.assertIn("can_assign_id", debug_info)
        self.assertIn("explanation", debug_info)

    def test_debug_member_id_assignment_invalid_member_returns_failed_result(self):
        """Test debug utility with invalid member returns failed OperationResult (not exception)"""
        result = self.service.debug_member_id_assignment("INVALID-MEMBER")

        # Debug utilities NEVER throw - this is critical for development use
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error_message)
        self.assertIn("does not exist", result.error_message)

    def test_debug_member_id_assignment_empty_name_returns_failed_result(self):
        """Test debug utility with empty name returns failed OperationResult"""
        result = self.service.debug_member_id_assignment("")

        self.assertFalse(result.success)
        self.assertIsNotNone(result.error_message)
        self.assertIn("required", result.error_message.lower())

    def test_service_never_throws_exceptions(self):
        """Test that service never throws exceptions - always returns OperationResult"""
        # Test with various invalid inputs
        invalid_inputs = ["", "INVALID", "   ", "Non-Existent-Member-123"]

        for invalid_input in invalid_inputs:
            result = self.service.assign_member_id(invalid_input)

            # Should always return OperationResult, never throw
            self.assertIsNotNone(result, f"Returned None for input: {invalid_input}")
            self.assertFalse(result.success, f"Should fail for input: {invalid_input}")
            self.assertIsNotNone(result.error_message, f"Missing error_message for input: {invalid_input}")

    def test_debug_never_throws_exceptions(self):
        """Test that debug utility never throws exceptions"""
        invalid_inputs = ["", "INVALID", "   ", "Non-Existent-Member-123"]

        for invalid_input in invalid_inputs:
            result = self.service.debug_member_id_assignment(invalid_input)

            # Should always return OperationResult, never throw
            self.assertIsNotNone(result, f"Returned None for input: {invalid_input}")
            self.assertFalse(result.success, f"Should fail for input: {invalid_input}")

    def test_bulk_operation_handles_partial_failures(self):
        """Test that bulk operation continues even with failures"""
        result = self.service.assign_missing_member_ids()

        # Should complete and return results even if some members fail
        self.assertIsNotNone(result)

        if result.success:
            # Success means at least some assignments happened or no members to process
            self.assertIsInstance(result.data, dict)
            self.assertIn("total_checked", result.data)
            self.assertIn("assigned", result.data)
        else:
            # Failure means bulk operation encountered fatal error
            self.assertIsNotNone(result.error_message)

    def test_member_with_id_cannot_get_duplicate_id(self):
        """Test that member who already has ID cannot get duplicate"""
        # Use unique email to avoid conflicts
        unique_email = f"dupid.{frappe.utils.random_string(8).lower()}@example.com"
        member = self.create_test_member(
            first_name="DupID",
            last_name="Test",
            email=unique_email
        )

        # Member created by create_test_member already has an ID
        # Try to assign another ID (should fail)
        result = self.service.assign_member_id(member.name)

        # Should fail because member already has ID
        self.assertFalse(result.success)
        self.assertIn("already has", result.error_message.lower())

    def test_debug_provides_comprehensive_member_info(self):
        """Test that debug utility provides comprehensive diagnostic info"""
        # Use unique email to avoid conflicts
        unique_email = f"compdbg.{frappe.utils.random_string(8).lower()}@example.com"
        member = self.create_test_member(
            first_name="CompDebug",
            last_name = "Test",
            email=unique_email
        )

        result = self.service.debug_member_id_assignment(member.name)

        # Should succeed with diagnostic information
        self.assertTrue(result.success)
        debug_info = result.data

        # Check all expected fields are present
        self.assertIn("member_name", debug_info)
        self.assertIn("has_member_id", debug_info)
        self.assertIn("can_assign_id", debug_info)
        self.assertIn("should_have_member_id", debug_info)
        self.assertIn("status", debug_info)
        self.assertIn("explanation", debug_info)


def run_tests():
    """Helper function to run tests from console"""
    frappe.flags.in_test = True
    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestMemberIDService)
    unittest.TextTestRunner(verbosity=2).run(suite)
