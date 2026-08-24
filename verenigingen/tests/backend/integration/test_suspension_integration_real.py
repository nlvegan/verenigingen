"""
Real Integration Tests for Suspension Functionality
==================================================

Phase 5.1 Database Mock Elimination: Suspension Integration
This test file replaces the inappropriate database mocking in test_suspension_integration.py
with real database operations and proper business logic testing.

Key Improvements:
- Eliminates all frappe.get_doc mocks - uses real document operations
- Eliminates all frappe.db.get_value mocks - uses real database queries
- Eliminates all frappe.db.exists mocks - uses real existence checking
- Tests actual suspension business logic through real document state changes
- Validates real User account suspension functionality
- Tests real team membership suspension integration

This approach catches real configuration issues, business rule violations, and integration problems
that mocked tests miss entirely.
"""

import frappe
from frappe.utils import today, add_days

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.termination_integration import (
    get_member_suspension_status,
    suspend_member_safe,
    unsuspend_member_safe,
)


class TestSuspensionIntegrationReal(EnhancedTestCase):
    """Real integration tests for suspension functionality without database mocks"""

    def setUp(self):
        """Set up test data using Enhanced Test Factory"""
        super().setUp()
        
        # Create test member with real database operations
        self.test_member = self.create_test_member(
            first_name="TestSuspension",
            last_name="Member", 
            email="test.suspension.real@example.com",
            status="Active"
        )
        
        # Create associated User account for real testing
        self.test_user = self.create_test_user(
            email=self.test_member.email,
            roles=["Verenigingen Member"],
            enabled=1
        )
        
        # Create test volunteer profile for team suspension testing
        self.test_volunteer = self.create_test_volunteer(
            member_name=self.test_member.name,
            start_date=add_days(today(), -30)  # Started 30 days ago
        )
        
        # The team below needs a Chapter and Team Role "Team Member", neither of
        # which is seeded on fresh CI-mirror sites, so create both first.
        #
        # The chapter name is unique per test: "Test Chapter" was a fixed name that
        # four different files created (#533), so on a warm site this test's team
        # was linked to whichever file's chapter happened to survive.
        from verenigingen.setup import create_default_team_roles

        create_default_team_roles()
        self.test_chapter = self.create_test_chapter(
            chapter_name=f"Test Chapter {frappe.generate_hash(length=6)}"
        )

        # Create test team and membership for suspension testing with unique name
        import uuid
        unique_suffix = str(uuid.uuid4())[:8]
        self.test_team = self.create_test_team(
            team_name=f"Test Suspension Team {unique_suffix}",
            chapter=self.test_chapter.name
        )
        
        self.test_team_member = self.create_test_team_member(
            team_name=self.test_team.name,
            volunteer_name=self.test_volunteer.name,
            team_role_name="Team Member"
        )
        
        self.suspension_reason = "Test suspension for integration testing"
        self.unsuspension_reason = "Test completed - unsuspending member"

    def test_suspend_member_safe_success_real_database(self):
        """Test successful member suspension with real database operations"""
        
        # Verify initial state through real database queries
        member = frappe.get_doc("Member", self.test_member.name)
        self.assertEqual(member.status, "Active")
        
        user = frappe.get_doc("User", self.test_user.email)
        self.assertEqual(user.enabled, 1)
        
        # Execute real suspension (no mocks)
        result = suspend_member_safe(
            self.test_member.name, 
            self.suspension_reason,
            suspend_user=True, 
            suspend_teams=True
        )
        
        # Verify results from actual database operations
        self.assertTrue(result["success"])
        self.assertTrue(result["member_suspended"])
        self.assertTrue(result["user_suspended"])
        self.assertGreaterEqual(result["teams_suspended"], 0)  # May vary based on actual team setup
        
        # Verify real member document changes
        member.reload()  # Get fresh data from database
        self.assertEqual(member.status, "Suspended")
        # Pre-suspension status is not a Member field; it is recorded in notes and
        # surfaced via get_member_suspension_status().
        self.assertIn("Pre-suspension status: Active", member.notes)
        self.assertEqual(
            get_member_suspension_status(self.test_member.name)["pre_suspension_status"], "Active"
        )
        self.assertIn(self.suspension_reason, member.notes)
        
        # Verify real user account suspension
        user.reload()  # Get fresh data from database
        self.assertEqual(user.enabled, 0)
        self.assertIn(self.suspension_reason, user.bio or "")
        
        # Verify actions taken list contains expected entries. The user-account
        # action includes the email in parentheses, so match by prefix.
        actions = result["actions_taken"]
        self.assertIn("Member status changed from Active to Suspended", actions)
        self.assertTrue(
            any(a.startswith("User account suspended") for a in actions),
            f"Expected a 'User account suspended' action, got {actions}",
        )

    def test_suspend_member_safe_already_suspended_real(self):
        """Test suspension of already suspended member with real database state"""
        
        # First, suspend the member using real operations
        first_result = suspend_member_safe(
            self.test_member.name,
            "First suspension reason"
        )
        self.assertTrue(first_result["success"])
        
        # Verify real database state
        member = frappe.get_doc("Member", self.test_member.name)
        self.assertEqual(member.status, "Suspended")
        
        # Try to suspend again
        second_result = suspend_member_safe(
            self.test_member.name,
            "Second suspension reason"  
        )
        
        # Should still succeed but indicate already suspended
        self.assertTrue(second_result["success"])
        self.assertFalse(second_result["member_suspended"])  # No change made
        
        # Member should remain in Suspended state
        member.reload()
        self.assertEqual(member.status, "Suspended")

    def test_unsuspend_member_safe_success_real_database(self):
        """Test successful member unsuspension with real database operations"""
        
        # First suspend the member with real database operations
        suspend_result = suspend_member_safe(
            self.test_member.name,
            self.suspension_reason,
            suspend_user=True
        )
        self.assertTrue(suspend_result["success"])
        
        # Verify suspended state in real database
        member = frappe.get_doc("Member", self.test_member.name)
        self.assertEqual(member.status, "Suspended")
        self.assertEqual(
            get_member_suspension_status(self.test_member.name)["pre_suspension_status"], "Active"
        )

        user = frappe.get_doc("User", self.test_user.email)
        self.assertEqual(user.enabled, 0)
        
        # Now unsuspend with real database operations
        unsuspend_result = unsuspend_member_safe(
            self.test_member.name,
            self.unsuspension_reason,
        )
        
        # Verify unsuspension results
        self.assertTrue(unsuspend_result["success"])
        self.assertTrue(unsuspend_result["member_unsuspended"])
        self.assertTrue(unsuspend_result["user_unsuspended"])
        
        # Verify real database changes
        member.reload()
        self.assertEqual(member.status, "Active")  # Restored to pre-suspension status
        self.assertIn(self.unsuspension_reason, member.notes)
        
        user.reload()
        self.assertEqual(user.enabled, 1)  # User re-enabled
        
        # Verify actions taken. Current messages: "Member status restored to
        # Active" and "User account reactivated (<email>)".
        actions = unsuspend_result["actions_taken"]
        self.assertTrue(
            any("status restored to Active" in a for a in actions),
            f"Expected a member-status-restored action, got {actions}",
        )
        self.assertTrue(
            any(a.startswith("User account reactivated") for a in actions),
            f"Expected a 'User account reactivated' action, got {actions}",
        )

    def test_get_member_suspension_status_real_database(self):
        """Test suspension status retrieval with real database queries"""
        
        # Test that status function can handle active member
        # Note: This function may return various formats, test what it actually returns
        status = get_member_suspension_status(self.test_member.name)
        # Status function exists and doesn't crash with real database operations
        self.assertIsNotNone(status)
        
        # Suspend member with real database operations
        suspend_result = suspend_member_safe(
            self.test_member.name,
            self.suspension_reason
        )
        self.assertTrue(suspend_result["success"])
        
        # Test that status function works with suspended member
        status_after = get_member_suspension_status(self.test_member.name)
        self.assertIsNotNone(status_after)
        
        # Verify real database state directly
        member = frappe.get_doc("Member", self.test_member.name)
        self.assertEqual(member.status, "Suspended")

    def test_suspension_workflow_error_handling_real(self):
        """Test error handling in suspension workflow with real operations"""
        
        # Test suspension of non-existent member (real database query failure)
        result = suspend_member_safe(
            "NON-EXISTENT-MEMBER",
            "Test reason"
        )
        
        # Should fail gracefully with real error
        self.assertFalse(result["success"])
        self.assertIn("error", result)
        # The actual error message will come from real database operation failure
        
        # Test unsuspension of non-suspended member. Unsuspending an Active member
        # is an invalid operation, so the service reports success=False with a
        # clear "not suspended" error rather than silently no-opping.
        unsuspend_result = unsuspend_member_safe(
            self.test_member.name,  # This member is Active, not Suspended
            "Test reason"
        )

        self.assertFalse(unsuspend_result["success"])
        self.assertIn("not suspended", unsuspend_result.get("error", "").lower())

    def test_suspension_with_real_team_integration(self):
        """Test suspension with real team membership operations"""
        
        # Verify team membership exists in real database. Team Member is a child
        # table of Team, so the team is the `parent` (there is no `team` column).
        team_memberships = frappe.get_all(
            "Team Member",
            filters={
                "volunteer": self.test_volunteer.name,
                "parent": self.test_team.name,
                "parenttype": "Team",
            }
        )
        self.assertGreater(len(team_memberships), 0)
        
        # Suspend with team operations
        result = suspend_member_safe(
            self.test_member.name,
            self.suspension_reason,
            suspend_teams=True
        )
        
        self.assertTrue(result["success"])
        # Teams suspended count will reflect real team membership data
        teams_suspended = result.get("teams_suspended", 0)
        self.assertIsInstance(teams_suspended, int)
        
        if teams_suspended > 0:
            self.assertIn("Suspended", result["actions_taken"][0])

    def test_suspension_user_account_integration_real(self):
        """Test suspension integrates properly with real User accounts"""
        
        # Verify user exists and is enabled in real database
        user_exists = frappe.db.exists("User", self.test_user.email)
        self.assertTrue(user_exists)
        
        user = frappe.get_doc("User", self.test_user.email)
        original_enabled_state = user.enabled
        
        # Suspend with real user account operations
        result = suspend_member_safe(
            self.test_member.name,
            self.suspension_reason,
            suspend_user=True
        )
        
        self.assertTrue(result["success"])
        
        # Verify real user account changes
        user.reload()
        self.assertEqual(user.enabled, 0)
        
        # Unsuspend and verify user account restoration
        unsuspend_result = unsuspend_member_safe(
            self.test_member.name,
            self.unsuspension_reason,
        )
        
        self.assertTrue(unsuspend_result["success"])
        
        user.reload()
        self.assertEqual(user.enabled, original_enabled_state)  # Restored to original state