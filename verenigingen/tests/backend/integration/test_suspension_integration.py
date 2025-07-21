"""
Unit tests for suspension integration functions
"""

from unittest.mock import MagicMock, patch

from frappe.utils import today
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.termination_integration import (
    get_member_suspension_status,
    suspend_member_safe,
    unsuspend_member_safe,
)


class TestSuspensionIntegration(VereningingenTestCase):
    """Test suspension integration functions"""

    def setUp(self):
        """Set up test data using factory methods"""
        super().setUp()
        
        # Create test member using factory method
        self.test_member = self.create_test_member(
            first_name="TestSuspension",
            last_name="Member",
            email="test.suspension@example.com",
            status="Active"
        )
        
        self.test_member_name = self.test_member.name
        self.test_user_email = self.test_member.email
        self.test_suspension_reason = "Test suspension for unit testing"
        self.test_unsuspension_reason = "Test unsuspension for unit testing"

    # tearDown handled by VereningingenTestCase automatically

    @patch("verenigingen.utils.termination_integration.frappe.get_doc")
    @patch("verenigingen.utils.termination_integration.frappe.db.get_value")
    @patch("verenigingen.utils.termination_integration.frappe.db.exists")
    @patch("verenigingen.utils.termination_integration.suspend_team_memberships_safe")
    def test_suspend_member_safe_success(self, mock_suspend_teams, mock_exists, mock_get_value, mock_get_doc):
        """Test successful member suspension"""

        # Mock member document
        mock_member = MagicMock()
        mock_member.status = "Active"
        mock_member.notes = "Existing notes"
        mock_member.name = self.test_member_name
        mock_get_doc.return_value = mock_member

        # Mock user lookup
        mock_get_value.return_value = self.test_user_email
        mock_exists.return_value = True

        # Mock user document
        mock_user = MagicMock()
        mock_user.enabled = 1
        mock_user.bio = ""  # Initialize bio as empty string
        mock_get_doc.side_effect = lambda doctype, name: {"Member": mock_member, "User": mock_user}.get(
            doctype, mock_member
        )

        # Mock team suspension
        mock_suspend_teams.return_value = 2

        # Execute suspension
        result = suspend_member_safe(
            self.test_member_name, self.test_suspension_reason, suspend_user=True, suspend_teams=True
        )

        # Verify results
        self.assertTrue(result["success"])
        self.assertTrue(result["member_suspended"])
        self.assertTrue(result["user_suspended"])
        self.assertEqual(result["teams_suspended"], 2)
        self.assertIn("Member status changed from Active to Suspended", result["actions_taken"])
        self.assertIn("User account suspended", result["actions_taken"])
        self.assertIn("Suspended 2 team membership(s)", result["actions_taken"])

        # Verify member document updates
        self.assertEqual(mock_member.status, "Suspended")
        self.assertEqual(mock_member.pre_suspension_status, "Active")
        self.assertIn(self.test_suspension_reason, mock_member.notes)
        mock_member.save.assert_called_once()

        # Verify user document updates
        self.assertEqual(mock_user.enabled, 0)
        self.assertIn(self.test_suspension_reason, mock_user.bio)
        mock_user.save.assert_called_once()

    @patch("verenigingen.utils.termination_integration.frappe.get_doc")
    def test_suspend_member_safe_failure(self, mock_get_doc):
        """Test suspension failure handling"""

        # Mock exception during member document retrieval
        mock_get_doc.side_effect = Exception("Database error")

        # Execute suspension
        result = suspend_member_safe(self.test_member_name, self.test_suspension_reason)

        # Verify failure handling
        self.assertFalse(result["success"])
        self.assertIn("error", result)
        self.assertEqual(result["error"], "Database error")

    @patch("verenigingen.utils.termination_integration.frappe.get_doc")
    @patch("verenigingen.utils.termination_integration.frappe.db.get_value")
    @patch("verenigingen.utils.termination_integration.frappe.db.exists")
    def test_unsuspend_member_safe_success(self, mock_exists, mock_get_value, mock_get_doc):
        """Test successful member unsuspension"""

        # Mock member document
        mock_member = MagicMock()
        mock_member.status = "Suspended"
        mock_member.pre_suspension_status = "Active"
        mock_member.notes = "Existing notes"
        mock_member.name = self.test_member_name
        mock_get_doc.return_value = mock_member

        # Mock user lookup
        mock_get_value.return_value = self.test_user_email
        mock_exists.return_value = True

        # Mock user document
        mock_user = MagicMock()
        mock_user.enabled = 0
        mock_user.bio = ""  # Initialize bio as empty string
        mock_get_doc.side_effect = lambda doctype, name: {"Member": mock_member, "User": mock_user}.get(
            doctype, mock_member
        )

        # Execute unsuspension
        result = unsuspend_member_safe(self.test_member_name, self.test_unsuspension_reason)

        # Verify results
        self.assertTrue(result["success"])
        self.assertTrue(result["member_unsuspended"])
        self.assertTrue(result["user_unsuspended"])
        self.assertIn("Member status restored to Active", result["actions_taken"])
        self.assertIn("User account reactivated", result["actions_taken"])

        # Verify member document updates
        self.assertEqual(mock_member.status, "Active")
        self.assertIsNone(mock_member.pre_suspension_status)
        self.assertIn(self.test_unsuspension_reason, mock_member.notes)
        mock_member.save.assert_called_once()

        # Verify user document updates
        self.assertEqual(mock_user.enabled, 1)
        self.assertIn(self.test_unsuspension_reason, mock_user.bio)
        mock_user.save.assert_called_once()

    @patch("verenigingen.utils.termination_integration.frappe.get_doc")
    def test_unsuspend_member_not_suspended(self, mock_get_doc):
        """Test unsuspension of non-suspended member"""

        # Mock member document that is not suspended
        mock_member = MagicMock()
        mock_member.status = "Active"
        mock_get_doc.return_value = mock_member

        # Execute unsuspension
        result = unsuspend_member_safe(self.test_member_name, self.test_unsuspension_reason)

        # Verify failure handling
        self.assertFalse(result["success"])
        self.assertIn("is not suspended", result["error"])
        self.assertIn("Member is not suspended", result["errors"])

    @patch("verenigingen.utils.termination_integration.frappe.get_doc")
    @patch("verenigingen.utils.termination_integration.frappe.db.get_value")
    @patch("verenigingen.utils.termination_integration.frappe.db.exists")
    @patch("verenigingen.utils.termination_integration.frappe.db.count")
    def test_get_member_suspension_status(self, mock_count, mock_exists, mock_get_value, mock_get_doc):
        """Test getting member suspension status"""

        # Mock member document
        mock_member = MagicMock()
        mock_member.status = "Suspended"
        mock_member.pre_suspension_status = "Active"
        mock_get_doc.return_value = mock_member

        # Mock user lookup
        mock_get_value.return_value = self.test_user_email
        mock_exists.return_value = True

        # Mock user document
        mock_user = MagicMock()
        mock_user.enabled = 0
        mock_get_doc.side_effect = lambda doctype, name: {"Member": mock_member, "User": mock_user}.get(
            doctype, mock_member
        )

        # Mock team count
        mock_count.return_value = 3

        # Get suspension status
        status = get_member_suspension_status(self.test_member_name)

        # Verify status information
        self.assertTrue(status["is_suspended"])
        self.assertEqual(status["member_status"], "Suspended")
        self.assertTrue(status["user_suspended"])
        self.assertEqual(status["active_teams"], 3)
        self.assertEqual(status["pre_suspension_status"], "Active")
        self.assertTrue(status["can_unsuspend"])

    @patch("verenigingen.utils.termination_integration.frappe.get_doc")
    def test_get_member_suspension_status_failure(self, mock_get_doc):
        """Test suspension status failure handling"""

        # Mock exception during member document retrieval
        mock_get_doc.side_effect = Exception("Database error")

        # Get suspension status
        status = get_member_suspension_status(self.test_member_name)

        # Verify failure handling
        self.assertIn("error", status)
        self.assertEqual(status["error"], "Database error")
        self.assertFalse(status["is_suspended"])
        self.assertFalse(status["can_unsuspend"])

    @patch("verenigingen.utils.termination_integration.frappe.get_doc")
    @patch("verenigingen.utils.termination_integration.frappe.db.get_value")
    def test_suspend_member_without_user_account(self, mock_get_value, mock_get_doc):
        """Test suspending member without user account"""

        # Mock member document
        mock_member = MagicMock()
        mock_member.status = "Active"
        mock_member.notes = None
        mock_get_doc.return_value = mock_member

        # Mock no user account
        mock_get_value.return_value = None

        # Execute suspension
        result = suspend_member_safe(self.test_member_name, self.test_suspension_reason, suspend_user=True)

        # Verify results
        self.assertTrue(result["success"])
        self.assertTrue(result["member_suspended"])
        self.assertFalse(result["user_suspended"])  # No user to suspend

        # Verify member document updates
        self.assertEqual(mock_member.status, "Suspended")
        self.assertEqual(
            mock_member.notes, f"Member suspended on {today()} - Reason: {self.test_suspension_reason}"
        )

    @patch("verenigingen.utils.termination_integration.frappe.get_doc")
    @patch("verenigingen.utils.termination_integration.suspend_team_memberships_safe")
    def test_suspend_member_teams_only(self, mock_suspend_teams, mock_get_doc):
        """Test suspending only team memberships, not user account"""

        # Mock member document
        mock_member = MagicMock()
        mock_member.status = "Active"
        mock_member.notes = "Existing notes"
        mock_get_doc.return_value = mock_member

        # Mock team suspension
        mock_suspend_teams.return_value = 1

        # Execute suspension with user=False, teams=True
        result = suspend_member_safe(
            self.test_member_name, self.test_suspension_reason, suspend_user=False, suspend_teams=True
        )

        # Verify results
        self.assertTrue(result["success"])
        self.assertTrue(result["member_suspended"])
        self.assertFalse(result["user_suspended"])
        self.assertEqual(result["teams_suspended"], 1)

        # Verify team suspension was called
        mock_suspend_teams.assert_called_once_with(
            self.test_member_name, today(), f"Member suspended - {self.test_suspension_reason}"
        )


if __name__ == "__main__":
    # Can be run via:
    # bench --site dev.veganisme.net run-tests --app verenigingen --module verenigingen.tests.backend.integration.test_suspension_integration
    import unittest
    unittest.main()
