"""
Specific tests for the new import fallback mechanism in suspension API
Tests the error handling and fallback functionality added to fix import issues
"""

import unittest
from unittest.mock import MagicMock, patch


class TestSuspensionAPIImportFallback(unittest.TestCase):
    """Test the import fallback mechanism in suspension API"""

    def setUp(self):
        """Set up test data"""
        self.test_member_name = "TEST-FALLBACK-MEMBER-001"
        self.test_user = "test.fallback@example.com"

    @patch("frappe.get_attr")
    @patch("frappe.log_error")
    def test_import_error_triggers_fallback(self, mock_log_error, mock_get_attr):
        """Test that import errors trigger the fallback mechanism"""
        from verenigingen.api.suspension_api import can_suspend_member

        # Mock import error
        mock_get_attr.side_effect = ImportError("No module named 'verenigingen.permissions'")

        # Mock fallback to return False (no permission)
        with patch(
            "verenigingen.api.suspension_api._can_suspend_member_fallback", return_value=False
        ) as mock_fallback:
            result = can_suspend_member(self.test_member_name)

        # Verify error was logged
        mock_log_error.assert_called_once()
        error_call = mock_log_error.call_args[0]
        self.assertIn("Import error in can_suspend_member", error_call[0])

        # Verify fallback was called
        mock_fallback.assert_called_once_with(self.test_member_name)

        # Verify result from fallback
        self.assertFalse(result)

    @patch("frappe.get_attr")
    def test_successful_import_bypasses_fallback(self, mock_get_attr):
        """Test that successful imports don't trigger fallback"""
        from verenigingen.api.suspension_api import can_suspend_member

        # Mock successful import
        mock_permission_func = MagicMock(return_value=True)
        mock_get_attr.return_value = mock_permission_func

        # Mock fallback (should not be called)
        with patch("verenigingen.api.suspension_api._can_suspend_member_fallback") as mock_fallback:
            result = can_suspend_member(self.test_member_name)

        # Verify successful import path
        mock_get_attr.assert_called_once_with("verenigingen.permissions.can_terminate_member")
        mock_permission_func.assert_called_once_with(self.test_member_name)

        # Verify fallback was NOT called
        mock_fallback.assert_not_called()

        # Verify result
        self.assertTrue(result)

    @patch("frappe.session")
    @patch("frappe.get_roles")
    def test_fallback_admin_permission(self, mock_get_roles, mock_session):
        """Test fallback grants permission to admin users"""
        from verenigingen.api.suspension_api import _can_suspend_member_fallback

        # Mock admin user
        mock_session.user = "admin@example.com"
        mock_get_roles.return_value = ["System Manager", "User"]

        result = _can_suspend_member_fallback(self.test_member_name)

        # Verify admin access granted
        self.assertTrue(result)
        mock_get_roles.assert_called_once_with("admin@example.com")

    @patch("frappe.session")
    @patch("frappe.get_roles")
    @patch("frappe.get_doc")
    @patch("frappe.db.get_value")
    def test_fallback_board_member_permission(
        self, mock_get_value, mock_get_doc, mock_get_roles, mock_session
    ):
        """Test fallback grants permission to board members"""
        from verenigingen.api.suspension_api import _can_suspend_member_fallback

        # Mock board member user
        mock_session.user = "board@example.com"
        mock_get_roles.return_value = ["User"]
        mock_get_value.return_value = "BOARD-MEMBER-001"

        # Mock member and chapter
        mock_member = MagicMock()
        mock_member.primary_chapter = "TEST-CHAPTER"

        mock_chapter = MagicMock()
        mock_chapter.user_has_board_access.return_value = True

        def get_doc_side_effect(doctype, name):
            if doctype == "Member":
                return mock_member
            elif doctype == "Chapter":
                return mock_chapter
            return MagicMock()

        mock_get_doc.side_effect = get_doc_side_effect

        result = _can_suspend_member_fallback(self.test_member_name)

        # Verify board member access granted
        self.assertTrue(result)
        mock_chapter.user_has_board_access.assert_called_once_with("BOARD-MEMBER-001")

    @patch("frappe.session")
    @patch("frappe.get_roles")
    @patch("frappe.db.get_value")
    def test_fallback_denies_regular_users(self, mock_get_value, mock_get_roles, mock_session):
        """Test fallback denies permission to regular users"""
        from verenigingen.api.suspension_api import _can_suspend_member_fallback

        # Mock regular user with no member record
        mock_session.user = "user@example.com"
        mock_get_roles.return_value = ["User"]
        mock_get_value.return_value = None  # No member record

        result = _can_suspend_member_fallback(self.test_member_name)

        # Verify access denied
        self.assertFalse(result)

    @patch("frappe.session")
    @patch("frappe.get_roles")
    @patch("frappe.get_doc")
    @patch("frappe.db.get_value")
    def test_fallback_handles_chapter_errors(
        self, mock_get_value, mock_get_doc, mock_get_roles, mock_session
    ):
        """Test fallback handles errors when checking chapter access"""
        from verenigingen.api.suspension_api import _can_suspend_member_fallback

        # Mock user and member
        mock_session.user = "board@example.com"
        mock_get_roles.return_value = ["User"]
        mock_get_value.return_value = "BOARD-MEMBER-001"

        # Mock member
        mock_member = MagicMock()
        mock_member.primary_chapter = "TEST-CHAPTER"

        # Mock chapter that raises exception
        mock_chapter = MagicMock()
        mock_chapter.user_has_board_access.side_effect = Exception("Chapter error")

        def get_doc_side_effect(doctype, name):
            if doctype == "Member":
                return mock_member
            elif doctype == "Chapter":
                return mock_chapter
            return MagicMock()

        mock_get_doc.side_effect = get_doc_side_effect

        result = _can_suspend_member_fallback(self.test_member_name)

        # Verify error is handled gracefully and access denied
        self.assertFalse(result)

    @patch("frappe.session")
    @patch("frappe.get_roles")
    @patch("frappe.get_doc")
    @patch("frappe.db.get_value")
    def test_fallback_member_without_chapter(
        self, mock_get_value, mock_get_doc, mock_get_roles, mock_session
    ):
        """Test fallback handles members without chapters"""
        from verenigingen.api.suspension_api import _can_suspend_member_fallback

        # Mock user and member
        mock_session.user = "board@example.com"
        mock_get_roles.return_value = ["User"]
        mock_get_value.return_value = "BOARD-MEMBER-001"

        # Mock member without chapter
        mock_member = MagicMock()
        mock_member.primary_chapter = None

        mock_get_doc.return_value = mock_member

        result = _can_suspend_member_fallback(self.test_member_name)

        # Verify access denied for members without chapters
        self.assertFalse(result)

    def test_fallback_function_exists_and_callable(self):
        """Test that the fallback function exists and is callable"""
        from verenigingen.api.suspension_api import _can_suspend_member_fallback

        # Verify function exists and is callable
        self.assertTrue(callable(_can_suspend_member_fallback))

        # Verify function has correct signature by attempting to call with mock data
        # This should not raise a TypeError about incorrect arguments
        try:
            with patch("frappe.session"), patch("frappe.get_roles"), patch("frappe.db.get_value"):
                _can_suspend_member_fallback("TEST-MEMBER")
        except TypeError as e:
            if "arguments" in str(e):
                self.fail(f"Fallback function signature is incorrect: {e}")
        except Exception:
            # Other exceptions are expected due to mocking
            pass


if __name__ == "__main__":
    unittest.main()
