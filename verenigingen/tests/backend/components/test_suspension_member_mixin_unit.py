"""
Integration tests for member suspension mixin
"""

import unittest
from unittest.mock import MagicMock, patch

from verenigingen.verenigingen.doctype.member.mixins.termination_mixin import TerminationMixin


class TestSuspensionMemberMixin(unittest.TestCase):
    """Test suspension functionality in member mixin"""

    def setUp(self):
        """Set up test data"""
        self.test_member_name = "TEST-MEMBER-001"
        self.test_suspension_reason = "Mixin test suspension"
        self.test_unsuspension_reason = "Mixin test unsuspension"

        # Create a mock member object with the mixin
        self.mock_member = MagicMock()
        self.mock_member.name = self.test_member_name
        self.mock_member.status = "Active"

        # Apply mixin methods to mock member
        for method_name in dir(TerminationMixin):
            if not method_name.startswith("_") and callable(getattr(TerminationMixin, method_name)):
                method = getattr(TerminationMixin, method_name)
                setattr(
                    self.mock_member, method_name, method.__get__(self.mock_member, type(self.mock_member))
                )

    @patch("verenigingen.utils.termination_integration.get_member_suspension_status")
    def test_get_suspension_summary(self, mock_get_status):
        """Test get_suspension_summary mixin method"""

        # Mock suspension status
        expected_status = {
            "is_suspended": True,
            "member_status": "Suspended",
            "user_suspended": True,
            "active_teams": 1,
            "can_unsuspend": True}
        mock_get_status.return_value = expected_status

        # Call mixin method
        result = self.mock_member.get_suspension_summary()

        # Verify call and result
        mock_get_status.assert_called_once_with(self.test_member_name)
        self.assertEqual(result, expected_status)

    @patch("verenigingen.utils.termination_integration.suspend_member_safe")
    def test_suspend_member_mixin_method(self, mock_suspend_safe):
        """Test suspend_member mixin method"""

        # Mock successful suspension
        expected_result = {
            "success": True,
            "actions_taken": ["Member suspended", "User account disabled"],
            "member_suspended": True,
            "user_suspended": True,
            "teams_suspended": 2}
        mock_suspend_safe.return_value = expected_result

        # Call mixin method
        result = self.mock_member.suspend_member(
            self.test_suspension_reason, suspend_user=True, suspend_teams=True
        )

        # Verify call and result
        mock_suspend_safe.assert_called_once_with(
            member_name=self.test_member_name,
            suspension_reason=self.test_suspension_reason,
            suspend_user=True,
            suspend_teams=True,
        )
        self.assertEqual(result, expected_result)

    @patch("verenigingen.utils.termination_integration.suspend_member_safe")
    def test_suspend_member_mixin_method_with_defaults(self, mock_suspend_safe):
        """Test suspend_member mixin method with default parameters"""

        # Mock successful suspension
        expected_result = {"success": True}
        mock_suspend_safe.return_value = expected_result

        # Call mixin method with defaults
        result = self.mock_member.suspend_member(self.test_suspension_reason)

        # Verify call with default parameters
        mock_suspend_safe.assert_called_once_with(
            member_name=self.test_member_name,
            suspension_reason=self.test_suspension_reason,
            suspend_user=True,  # Default
            suspend_teams=True,  # Default
        )
        self.assertEqual(result, expected_result)

    @patch("verenigingen.utils.termination_integration.unsuspend_member_safe")
    def test_unsuspend_member_mixin_method(self, mock_unsuspend_safe):
        """Test unsuspend_member mixin method"""

        # Mock successful unsuspension
        expected_result = {
            "success": True,
            "actions_taken": ["Member restored", "User account reactivated"],
            "member_unsuspended": True,
            "user_unsuspended": True}
        mock_unsuspend_safe.return_value = expected_result

        # Call mixin method
        result = self.mock_member.unsuspend_member(self.test_unsuspension_reason)

        # Verify call and result
        mock_unsuspend_safe.assert_called_once_with(
            member_name=self.test_member_name, unsuspension_reason=self.test_unsuspension_reason
        )
        self.assertEqual(result, expected_result)

    @patch("verenigingen.utils.termination_integration.suspend_member_safe")
    def test_suspend_member_error_handling(self, mock_suspend_safe):
        """Test suspend_member mixin method error handling"""

        # Mock suspension failure
        expected_result = {
            "success": False,
            "error": "Database connection failed",
            "actions_taken": [],
            "errors": ["Database connection failed"]}
        mock_suspend_safe.return_value = expected_result

        # Call mixin method
        result = self.mock_member.suspend_member(self.test_suspension_reason)

        # Verify error handling
        self.assertFalse(result["success"])
        self.assertIn("error", result)
        self.assertEqual(result["error"], "Database connection failed")

    @patch("verenigingen.utils.termination_integration.unsuspend_member_safe")
    def test_unsuspend_member_error_handling(self, mock_unsuspend_safe):
        """Test unsuspend_member mixin method error handling"""

        # Mock unsuspension failure
        expected_result = {
            "success": False,
            "error": "Member is not suspended",
            "actions_taken": [],
            "errors": ["Member is not suspended"]}
        mock_unsuspend_safe.return_value = expected_result

        # Call mixin method
        result = self.mock_member.unsuspend_member(self.test_unsuspension_reason)

        # Verify error handling
        self.assertFalse(result["success"])
        self.assertIn("error", result)
        self.assertEqual(result["error"], "Member is not suspended")

    def test_mixin_method_availability(self):
        """Test that all suspension methods are available in mixin"""

        # Test that suspension methods exist in the mixin
        required_methods = ["get_suspension_summary", "suspend_member", "unsuspend_member"]

        for method_name in required_methods:
            self.assertTrue(
                hasattr(TerminationMixin, method_name), f"Method {method_name} not found in TerminationMixin"
            )

            # Test that method is callable
            method = getattr(TerminationMixin, method_name)
            self.assertTrue(callable(method), f"Method {method_name} is not callable")

    def test_mixin_integration_with_mock_member(self):
        """Test that mixin methods work correctly when applied to mock member"""

        # Verify that our mock member has the suspension methods
        required_methods = ["get_suspension_summary", "suspend_member", "unsuspend_member"]

        for method_name in required_methods:
            self.assertTrue(
                hasattr(self.mock_member, method_name), f"Method {method_name} not applied to mock member"
            )

            # Test that method is callable on the mock member
            method = getattr(self.mock_member, method_name)
            self.assertTrue(callable(method), f"Method {method_name} is not callable on mock member")

    @patch("verenigingen.utils.termination_integration.get_member_suspension_status")
    def test_get_suspension_summary_exception_handling(self, mock_get_status):
        """Test get_suspension_summary handles exceptions gracefully"""

        # Mock exception in underlying function
        mock_get_status.side_effect = Exception("Network error")

        # Call mixin method - should propagate exception
        with self.assertRaises(Exception) as context:
            self.mock_member.get_suspension_summary()

        self.assertEqual(str(context.exception), "Network error")
        mock_get_status.assert_called_once_with(self.test_member_name)


if __name__ == "__main__":
    unittest.main()
