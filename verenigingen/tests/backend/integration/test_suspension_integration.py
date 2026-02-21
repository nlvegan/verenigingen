"""
Integration tests for suspension functions using real database operations.

Tests suspend_member_safe, unsuspend_member_safe, and get_member_suspension_status
with actual Member and User documents.
"""

import unittest

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.termination_integration import (
    get_member_suspension_status,
    suspend_member_safe,
    unsuspend_member_safe,
)


class TestSuspensionIntegration(EnhancedTestCase):
    """Integration tests for suspension functions with real data"""

    def setUp(self):
        """Create test member with linked user account"""
        super().setUp()

        # Create user first so member can be linked
        self.test_user = self.create_test_user_with_roles(
            email="test.suspension@test.verenigingen.invalid",
            roles=["Verenigingen Member"],
            first_name="TestSuspension",
            last_name="Member",
        )

        # Create member linked to user
        self.test_member = self.create_test_member(
            first_name="TestSuspension",
            last_name="Member",
            email="test.suspension@test.verenigingen.invalid",
            status="Active",
        )

        self.test_member_name = self.test_member.name
        self.test_suspension_reason = "Test suspension for integration testing"
        self.test_unsuspension_reason = "Test unsuspension for integration testing"

    def _ensure_member_status(self, status):
        """Helper to set member status directly for test setup"""
        frappe.db.set_value("Member", self.test_member_name, "status", status)
        frappe.db.commit()

    def _ensure_user_enabled(self, enabled):
        """Helper to set user enabled state directly for test setup"""
        frappe.db.set_value("User", self.test_user.name, "enabled", enabled)
        frappe.db.commit()

    def test_suspend_member_safe_success(self):
        """Test successful member suspension with user account"""
        self._ensure_member_status("Active")
        self._ensure_user_enabled(1)

        result = suspend_member_safe(
            self.test_member_name,
            self.test_suspension_reason,
            suspend_user=True,
            suspend_teams=False,
        )

        self.assertTrue(result["success"])
        self.assertTrue(result["member_suspended"])

        # Verify member status in database
        member = frappe.get_doc("Member", self.test_member_name)
        self.assertEqual(member.status, "Suspended")
        self.assertIn(self.test_suspension_reason, member.notes or "")
        self.assertIn("Pre-suspension status: Active", member.notes or "")

        # Verify user account was disabled
        user = frappe.get_doc("User", self.test_user.name)
        self.assertEqual(user.enabled, 0)

        # Verify action reporting
        actions = result["actions_taken"]
        self.assertTrue(
            any("Member status changed from Active to Suspended" in a for a in actions)
        )
        self.assertTrue(any("User account suspended" in a for a in actions))

    def test_suspend_member_safe_failure_nonexistent(self):
        """Test suspension failure for non-existent member"""
        result = suspend_member_safe("NONEXISTENT-MEMBER-999", self.test_suspension_reason)

        self.assertFalse(result["success"])
        self.assertIn("error", result)

    def test_suspend_member_already_suspended(self):
        """Test suspension of already-suspended member is idempotent"""
        self._ensure_member_status("Suspended")

        result = suspend_member_safe(
            self.test_member_name, self.test_suspension_reason
        )

        # Should succeed but report already suspended
        self.assertTrue(result["success"])
        self.assertTrue(
            any("already suspended" in a for a in result["actions_taken"])
        )

    def test_unsuspend_member_safe_success(self):
        """Test successful member unsuspension"""
        # First suspend the member properly
        self._ensure_member_status("Active")
        self._ensure_user_enabled(1)
        suspend_member_safe(
            self.test_member_name,
            self.test_suspension_reason,
            suspend_user=True,
            suspend_teams=False,
        )

        # Now unsuspend
        result = unsuspend_member_safe(
            self.test_member_name, self.test_unsuspension_reason
        )

        self.assertTrue(result["success"])
        self.assertTrue(result["member_unsuspended"])

        # Verify member status restored in database
        member = frappe.get_doc("Member", self.test_member_name)
        self.assertEqual(member.status, "Active")
        self.assertIn(self.test_unsuspension_reason, member.notes or "")

        # Verify user account was re-enabled
        user = frappe.get_doc("User", self.test_user.name)
        self.assertEqual(user.enabled, 1)

        # Verify action reporting
        actions = result["actions_taken"]
        self.assertTrue(
            any("Member status restored to Active" in a for a in actions)
        )
        self.assertTrue(any("User account reactivated" in a for a in actions))

    def test_unsuspend_member_not_suspended(self):
        """Test unsuspension of non-suspended member returns error"""
        self._ensure_member_status("Active")

        result = unsuspend_member_safe(
            self.test_member_name, self.test_unsuspension_reason
        )

        self.assertFalse(result["success"])
        self.assertIn("is not suspended", result["error"])
        self.assertIn("Member is not suspended", result["errors"])

    def test_get_member_suspension_status_suspended(self):
        """Test getting suspension status for suspended member"""
        # Suspend the member first
        self._ensure_member_status("Active")
        self._ensure_user_enabled(1)
        suspend_member_safe(
            self.test_member_name,
            self.test_suspension_reason,
            suspend_user=True,
            suspend_teams=False,
        )

        status = get_member_suspension_status(self.test_member_name)

        self.assertTrue(status["is_suspended"])
        self.assertEqual(status["member_status"], "Suspended")
        self.assertTrue(status["user_suspended"])
        self.assertEqual(status["pre_suspension_status"], "Active")
        self.assertTrue(status["can_unsuspend"])

    def test_get_member_suspension_status_active(self):
        """Test getting suspension status for active member"""
        self._ensure_member_status("Active")
        self._ensure_user_enabled(1)

        status = get_member_suspension_status(self.test_member_name)

        self.assertFalse(status["is_suspended"])
        self.assertEqual(status["member_status"], "Active")
        self.assertFalse(status["can_unsuspend"])

    def test_get_member_suspension_status_nonexistent(self):
        """Test suspension status for non-existent member"""
        status = get_member_suspension_status("NONEXISTENT-MEMBER-999")

        self.assertIn("error", status)
        self.assertFalse(status["is_suspended"])
        self.assertFalse(status["can_unsuspend"])

    def test_suspend_member_without_user_account(self):
        """Test suspending member that has no linked user account"""
        # Create a member without a user account
        member_no_user = self.create_test_member(
            first_name="NoUser",
            last_name="Member",
            email="nouser.suspension@test.verenigingen.invalid",
            status="Active",
        )

        result = suspend_member_safe(
            member_no_user.name,
            self.test_suspension_reason,
            suspend_user=True,
            suspend_teams=False,
        )

        self.assertTrue(result["success"])
        self.assertTrue(result["member_suspended"])
        self.assertFalse(result["user_suspended"])

        # Verify member status in database
        member = frappe.get_doc("Member", member_no_user.name)
        self.assertEqual(member.status, "Suspended")
        self.assertIn(self.test_suspension_reason, member.notes or "")

    def test_suspend_without_user_flag(self):
        """Test suspension with suspend_user=False skips user account"""
        self._ensure_member_status("Active")
        self._ensure_user_enabled(1)

        result = suspend_member_safe(
            self.test_member_name,
            self.test_suspension_reason,
            suspend_user=False,
            suspend_teams=False,
        )

        self.assertTrue(result["success"])
        self.assertTrue(result["member_suspended"])
        self.assertFalse(result["user_suspended"])

        # Verify member is suspended but user is still enabled
        member = frappe.get_doc("Member", self.test_member_name)
        self.assertEqual(member.status, "Suspended")

        user = frappe.get_doc("User", self.test_user.name)
        self.assertEqual(user.enabled, 1)

    def test_full_suspend_unsuspend_cycle(self):
        """Test complete suspend → verify → unsuspend → verify cycle"""
        self._ensure_member_status("Active")
        self._ensure_user_enabled(1)

        # Suspend
        suspend_result = suspend_member_safe(
            self.test_member_name,
            self.test_suspension_reason,
            suspend_user=True,
            suspend_teams=False,
        )
        self.assertTrue(suspend_result["success"])

        # Verify suspended state
        status = get_member_suspension_status(self.test_member_name)
        self.assertTrue(status["is_suspended"])
        self.assertTrue(status["user_suspended"])

        # Unsuspend
        unsuspend_result = unsuspend_member_safe(
            self.test_member_name, self.test_unsuspension_reason
        )
        self.assertTrue(unsuspend_result["success"])

        # Verify restored state
        status = get_member_suspension_status(self.test_member_name)
        self.assertFalse(status["is_suspended"])
        self.assertEqual(status["member_status"], "Active")


if __name__ == "__main__":
    # bench --site veg11.veganisme.org run-tests --app verenigingen \
    #   --module verenigingen.tests.backend.integration.test_suspension_integration
    unittest.main()
