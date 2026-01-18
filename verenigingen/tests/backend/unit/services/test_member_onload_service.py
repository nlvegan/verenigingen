# Copyright (c) 2025, Verenigingen
# For license information, please see license.txt

"""
Unit Tests for MemberOnloadService

Tests the member onload orchestration service to ensure:
- New documents are skipped
- Each display operation is called
- Errors in one operation don't affect others
- Permission errors are handled gracefully
- Results are properly aggregated

Extracted from Member.onload() method.
"""

import unittest
from unittest.mock import MagicMock, patch


class TestMemberOnloadServiceExecuteOnload(unittest.TestCase):
    """Test execute_onload() method"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.display.member_onload_service import (
            get_member_onload_service,
        )
        self.service = get_member_onload_service()

    def test_skips_new_documents(self):
        """Test that onload is skipped for new/unsaved documents"""
        mock_member = MagicMock()
        mock_member.get.return_value = True  # __islocal = True

        result = self.service.execute_onload(mock_member)

        self.assertTrue(result["success"])
        self.assertIn("skipped", result["operations"])

    def test_executes_all_operations_for_saved_document(self):
        """Test that all operations are executed for saved documents"""
        mock_member = MagicMock()
        mock_member.get.return_value = False  # __islocal = False
        mock_member.name = "MEM-001"

        result = self.service.execute_onload(mock_member)

        # All operations should be in the result
        self.assertIn("chapter_display", result["operations"])
        self.assertIn("address_display", result["operations"])
        self.assertIn("household_members", result["operations"])
        self.assertIn("volunteer_details", result["operations"])
        self.assertIn("membership_duration", result["operations"])

    def test_calls_chapter_display_update(self):
        """Test that chapter display update is called"""
        mock_member = MagicMock()
        mock_member.get.return_value = False
        mock_member.name = "MEM-001"

        self.service.execute_onload(mock_member)

        mock_member.update_current_chapter_display.assert_called_once()

    def test_calls_address_display_update(self):
        """Test that address display update is called"""
        mock_member = MagicMock()
        mock_member.get.return_value = False
        mock_member.name = "MEM-001"

        self.service.execute_onload(mock_member)

        mock_member.update_address_display.assert_called_once()

    def test_calls_household_members_update(self):
        """Test that household members display update is called"""
        mock_member = MagicMock()
        mock_member.get.return_value = False
        mock_member.name = "MEM-001"
        mock_member.other_members_at_address = "<html>content</html>"

        self.service.execute_onload(mock_member)

        mock_member.update_other_members_at_address_display.assert_called_once()

    def test_calls_membership_duration_calculation(self):
        """Test that membership duration calculation is called"""
        mock_member = MagicMock()
        mock_member.get.return_value = False
        mock_member.name = "MEM-001"

        self.service.execute_onload(mock_member)

        mock_member.calculate_cumulative_membership_duration.assert_called_once()


class TestMemberOnloadServiceErrorHandling(unittest.TestCase):
    """Test error handling in onload operations"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.display.member_onload_service import (
            get_member_onload_service,
        )
        self.service = get_member_onload_service()

    @patch("verenigingen.services.member.display.member_onload_service.frappe")
    def test_chapter_display_error_isolated(self, mock_frappe):
        """Test that chapter display error doesn't affect other operations"""
        mock_member = MagicMock()
        mock_member.get.return_value = False
        mock_member.name = "MEM-001"
        mock_member.update_current_chapter_display.side_effect = Exception("Chapter error")

        result = self.service.execute_onload(mock_member)

        # Chapter display should have error
        self.assertFalse(result["operations"]["chapter_display"]["success"])
        # Other operations should still be called
        mock_member.update_address_display.assert_called_once()
        mock_member.calculate_cumulative_membership_duration.assert_called_once()

    @patch("verenigingen.services.member.display.member_onload_service.frappe")
    def test_address_display_error_isolated(self, mock_frappe):
        """Test that address display error doesn't affect other operations"""
        mock_member = MagicMock()
        mock_member.get.return_value = False
        mock_member.name = "MEM-001"
        mock_member.update_address_display.side_effect = Exception("Address error")

        result = self.service.execute_onload(mock_member)

        # Address display should have error
        self.assertFalse(result["operations"]["address_display"]["success"])
        # Other operations should still be called
        mock_member.update_current_chapter_display.assert_called_once()

    @patch("verenigingen.services.member.display.member_onload_service.frappe")
    def test_errors_collected_in_result(self, mock_frappe):
        """Test that errors are collected in the result"""
        mock_member = MagicMock()
        mock_member.get.return_value = False
        mock_member.name = "MEM-001"
        mock_member.update_current_chapter_display.side_effect = Exception("Chapter error")
        mock_member.update_address_display.side_effect = Exception("Address error")

        result = self.service.execute_onload(mock_member)

        self.assertFalse(result["success"])
        self.assertEqual(len(result["errors"]), 2)


class TestMemberOnloadServiceHouseholdMembers(unittest.TestCase):
    """Test household members display handling"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.display.member_onload_service import (
            get_member_onload_service,
        )
        self.service = get_member_onload_service()

    def test_sets_onload_when_content_exists(self):
        """Test that onload is set when household members content exists"""
        mock_member = MagicMock()
        mock_member.get.return_value = False
        mock_member.name = "MEM-001"
        mock_member.other_members_at_address = "<html>household content</html>"

        self.service._update_household_members_display(mock_member)

        mock_member.set_onload.assert_called_with(
            "other_members_at_address", "<html>household content</html>"
        )

    @patch("verenigingen.services.member.display.member_onload_service.frappe")
    def test_permission_error_handled_silently(self, mock_frappe):
        """Test that permission errors are handled silently"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member.update_other_members_at_address_display.side_effect = Exception(
            "Access denied for Member"
        )

        result = self.service._update_household_members_display(mock_member)

        self.assertFalse(result["success"])
        self.assertTrue(result["is_permission_error"])
        # Field should be cleared
        self.assertEqual(mock_member.other_members_at_address, "")
        # Should NOT log error for permission issues
        mock_frappe.log_error.assert_not_called()

    @patch("verenigingen.services.member.display.member_onload_service.frappe")
    def test_non_permission_error_logged(self, mock_frappe):
        """Test that non-permission errors are logged"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member.update_other_members_at_address_display.side_effect = Exception(
            "Database connection failed"
        )

        result = self.service._update_household_members_display(mock_member)

        self.assertFalse(result["success"])
        self.assertFalse(result["is_permission_error"])
        # Should log error for non-permission issues
        mock_frappe.log_error.assert_called_once()


class TestMemberOnloadServiceVolunteerDetails(unittest.TestCase):
    """Test volunteer details display handling"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.display.member_onload_service import (
            get_member_onload_service,
        )
        self.service = get_member_onload_service()

    @patch("verenigingen.services.member.display.member_volunteer_display_service.get_member_volunteer_display_service")
    def test_sets_volunteer_html_when_content_exists(self, mock_get_service):
        """Test that volunteer HTML is set when content is generated"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"

        mock_volunteer_service = MagicMock()
        mock_volunteer_service.generate_volunteer_details_html.return_value = "<html>volunteer</html>"
        mock_get_service.return_value = mock_volunteer_service

        result = self.service._update_volunteer_details(mock_member)

        self.assertTrue(result["success"])
        self.assertTrue(result["has_content"])
        self.assertEqual(mock_member.volunteer_details_html, "<html>volunteer</html>")
        mock_member.set_onload.assert_called_with("volunteer_details_html", "<html>volunteer</html>")

    @patch("verenigingen.services.member.display.member_volunteer_display_service.get_member_volunteer_display_service")
    def test_handles_empty_volunteer_html(self, mock_get_service):
        """Test that empty volunteer HTML is handled correctly"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"

        mock_volunteer_service = MagicMock()
        mock_volunteer_service.generate_volunteer_details_html.return_value = None
        mock_get_service.return_value = mock_volunteer_service

        result = self.service._update_volunteer_details(mock_member)

        self.assertTrue(result["success"])
        self.assertFalse(result["has_content"])
        mock_member.set_onload.assert_not_called()


class TestMemberOnloadServiceMembershipDuration(unittest.TestCase):
    """Test membership duration calculation"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.display.member_onload_service import (
            get_member_onload_service,
        )
        self.service = get_member_onload_service()

    def test_calls_duration_calculation(self):
        """Test that duration calculation is called"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"

        result = self.service._update_membership_duration(mock_member)

        self.assertTrue(result["success"])
        mock_member.calculate_cumulative_membership_duration.assert_called_once()

    @patch("verenigingen.services.member.display.member_onload_service.frappe")
    def test_duration_error_logged(self, mock_frappe):
        """Test that duration calculation errors are logged"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member.calculate_cumulative_membership_duration.side_effect = Exception("Calc error")

        result = self.service._update_membership_duration(mock_member)

        self.assertFalse(result["success"])
        mock_frappe.log_error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
