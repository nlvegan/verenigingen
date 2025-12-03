"""
Simplified Real Integration Tests for Suspension Functionality
============================================================

Phase 5.1 Database Mock Elimination: Core Suspension Tests
This demonstrates successful elimination of database mocks from suspension testing.

Key Achievement: Replaces inappropriate mocking patterns with real database operations.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.termination_integration import (
    suspend_member_safe,
    unsuspend_member_safe,
)


class TestSuspensionSimpleReal(EnhancedTestCase):
    """Simplified real integration tests for suspension without complex dependencies"""

    def setUp(self):
        """Set up test data using Enhanced Test Factory"""
        super().setUp()
        
        # Create test member with real database operations
        self.test_member = self.create_test_member(
            first_name="TestSuspension",
            last_name="Simple", 
            email="test.suspension.simple@example.com",
            status="Active"
        )
        
        # Create associated User account for real testing
        self.test_user = self.create_test_user(
            email=self.test_member.email,
            roles=["Verenigingen Member"],
            enabled=1
        )
        
        self.suspension_reason = "Test suspension for database mock elimination"

    def test_member_suspension_real_database_operations(self):
        """Test member suspension with real database operations (no mocks)"""
        
        # Verify initial state through real database queries (not mocked)
        member = frappe.get_doc("Member", self.test_member.name)
        self.assertEqual(member.status, "Active")
        
        user = frappe.get_doc("User", self.test_user.email)
        self.assertEqual(user.enabled, 1)
        
        # Execute real suspension - tests actual business logic
        result = suspend_member_safe(
            self.test_member.name, 
            self.suspension_reason,
            suspend_user=True
        )
        
        # Verify results from real database state changes
        self.assertTrue(result["success"])
        self.assertTrue(result["member_suspended"])
        self.assertTrue(result["user_suspended"])
        
        # Verify real member document changes (not mock assertions)
        member.reload()  # Real database query
        self.assertEqual(member.status, "Suspended")
        # Note: pre_suspension_status is stored internally but not as a doctype field
        self.assertIn(self.suspension_reason, member.notes)
        
        # Verify real user account suspension
        user.reload()  # Real database query  
        self.assertEqual(user.enabled, 0)

    def test_member_unsuspension_real_database_operations(self):
        """Test member unsuspension with real database operations (no mocks)"""
        
        # First suspend with real operations
        suspend_result = suspend_member_safe(
            self.test_member.name,
            self.suspension_reason,
            suspend_user=True
        )
        self.assertTrue(suspend_result["success"])
        
        # Verify suspended state in real database
        member = frappe.get_doc("Member", self.test_member.name)
        self.assertEqual(member.status, "Suspended")
        
        # Now unsuspend with real database operations
        unsuspend_result = unsuspend_member_safe(
            self.test_member.name,
            "Test completed - unsuspending",
            restore_teams=True
        )
        
        # Verify unsuspension results
        self.assertTrue(unsuspend_result["success"])
        self.assertTrue(unsuspend_result["member_unsuspended"])
        self.assertTrue(unsuspend_result["user_unsuspended"])
        
        # Verify real database changes
        member.reload()
        self.assertEqual(member.status, "Active")  # Restored
        
        user = frappe.get_doc("User", self.test_user.email)
        self.assertEqual(user.enabled, 1)  # Re-enabled

    def test_suspension_error_handling_real_operations(self):
        """Test error handling with real database operations (no mocked exceptions)"""
        
        # Test suspension of non-existent member (real database failure)
        result = suspend_member_safe(
            "NON-EXISTENT-MEMBER-12345",
            "Test reason"
        )
        
        # Should fail with real error from actual database operation
        self.assertFalse(result["success"])
        self.assertIn("error", result)
        
        # The error comes from real frappe.get_doc() failure, not mocked exception
        self.assertTrue(len(result["error"]) > 0)

    def test_suspension_business_logic_validation_real(self):
        """Test business logic validation without database mocks"""
        
        # Test suspension of already suspended member
        # First suspension - real database operations
        first_result = suspend_member_safe(
            self.test_member.name,
            "First suspension"
        )
        self.assertTrue(first_result["success"])
        
        # Verify real database state
        member = frappe.get_doc("Member", self.test_member.name)
        self.assertEqual(member.status, "Suspended")
        
        # Second suspension attempt - should handle gracefully
        second_result = suspend_member_safe(
            self.test_member.name,
            "Second suspension attempt"  
        )
        
        # Business logic should handle this appropriately
        self.assertTrue(second_result["success"])
        self.assertFalse(second_result["member_suspended"])  # Already suspended
        
        # Member remains in suspended state (verified via real database)
        member.reload()
        self.assertEqual(member.status, "Suspended")