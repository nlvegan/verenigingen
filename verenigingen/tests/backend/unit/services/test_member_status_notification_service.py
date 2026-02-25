# Copyright (c) 2025, Verenigingen
# For license information, please see license.txt

"""
Unit Tests for MemberStatusNotificationService

Tests the member status notification service to ensure:
- Notifications are sent when member has email
- Notifications are skipped when member has no email
- Correct notification config is used for each status
- Email context is built correctly
- Email service is called with correct parameters

Extracted from Member._send_member_status_notification() method.
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe


class TestMemberStatusNotificationServiceSendNotification(unittest.TestCase):
    """Test send_status_change_notification() method"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.lifecycle.member_status_notification_service import (
            get_member_status_notification_service,
        )
        self.service = get_member_status_notification_service()

    def test_notification_skipped_when_no_email(self):
        """Test that notification is skipped when member has no email"""
        mock_member = MagicMock()
        mock_member.email = None

        result = self.service.send_status_change_notification(
            mock_member, "Pending", "Active"
        )

        self.assertFalse(result)

    def test_notification_skipped_when_empty_email(self):
        """Test that notification is skipped when member has empty email"""
        mock_member = MagicMock()
        mock_member.email = ""

        result = self.service.send_status_change_notification(
            mock_member, "Pending", "Active"
        )

        self.assertFalse(result)

    @patch("verenigingen.verenigingen_payments.services.mollie_configuration_service.get_mollie_config")
    @patch("verenigingen.services.communication.email_service.get_email_service")
    def test_notification_sent_when_has_email(self, mock_get_email, mock_get_mollie):
        """Test that notification is sent when member has email"""
        mock_member = MagicMock()
        mock_member.email = "test@example.com"
        mock_member.name = "MEM-001"
        mock_member.full_name = "Test Member"

        mock_email_service = MagicMock()
        mock_get_email.return_value = mock_email_service

        mock_mollie_config = MagicMock()
        mock_mollie_config.get_default_company.return_value = "Test Company"
        mock_get_mollie.return_value = mock_mollie_config

        result = self.service.send_status_change_notification(
            mock_member, "Pending", "Active"
        )

        self.assertTrue(result)
        mock_email_service.send_templated_email.assert_called_once()

    @patch("verenigingen.verenigingen_payments.services.mollie_configuration_service.get_mollie_config")
    @patch("verenigingen.services.communication.email_service.get_email_service")
    def test_active_status_uses_correct_config(self, mock_get_email, mock_get_mollie):
        """Test that Active status uses correct notification config"""
        mock_member = MagicMock()
        mock_member.email = "test@example.com"
        mock_member.name = "MEM-001"
        mock_member.full_name = "Test Member"

        mock_email_service = MagicMock()
        mock_get_email.return_value = mock_email_service

        mock_mollie_config = MagicMock()
        mock_mollie_config.get_default_company.return_value = "Test Company"
        mock_get_mollie.return_value = mock_mollie_config

        self.service.send_status_change_notification(
            mock_member, "Pending", "Active"
        )

        call_kwargs = mock_email_service.send_templated_email.call_args[1]
        self.assertEqual(call_kwargs["notification_key"], "member_activated")
        self.assertEqual(call_kwargs["subject_override"], "Your Membership is Now Active")

    @patch("verenigingen.verenigingen_payments.services.mollie_configuration_service.get_mollie_config")
    @patch("verenigingen.services.communication.email_service.get_email_service")
    def test_suspended_status_uses_correct_config(self, mock_get_email, mock_get_mollie):
        """Test that Suspended status uses correct notification config"""
        mock_member = MagicMock()
        mock_member.email = "test@example.com"
        mock_member.name = "MEM-001"
        mock_member.full_name = "Test Member"

        mock_email_service = MagicMock()
        mock_get_email.return_value = mock_email_service

        mock_mollie_config = MagicMock()
        mock_mollie_config.get_default_company.return_value = "Test Company"
        mock_get_mollie.return_value = mock_mollie_config

        self.service.send_status_change_notification(
            mock_member, "Active", "Suspended"
        )

        call_kwargs = mock_email_service.send_templated_email.call_args[1]
        self.assertEqual(call_kwargs["notification_key"], "member_suspended")
        self.assertEqual(call_kwargs["subject_override"], "Membership Suspended")

    @patch("verenigingen.verenigingen_payments.services.mollie_configuration_service.get_mollie_config")
    @patch("verenigingen.services.communication.email_service.get_email_service")
    def test_terminated_status_uses_correct_config(self, mock_get_email, mock_get_mollie):
        """Test that Terminated status uses correct notification config"""
        mock_member = MagicMock()
        mock_member.email = "test@example.com"
        mock_member.name = "MEM-001"
        mock_member.full_name = "Test Member"

        mock_email_service = MagicMock()
        mock_get_email.return_value = mock_email_service

        mock_mollie_config = MagicMock()
        mock_mollie_config.get_default_company.return_value = "Test Company"
        mock_get_mollie.return_value = mock_mollie_config

        self.service.send_status_change_notification(
            mock_member, "Active", "Quit"
        )

        call_kwargs = mock_email_service.send_templated_email.call_args[1]
        self.assertEqual(call_kwargs["notification_key"], "member_terminated")
        self.assertEqual(call_kwargs["subject_override"], "Membership Terminated")

    @patch("verenigingen.verenigingen_payments.services.mollie_configuration_service.get_mollie_config")
    @patch("verenigingen.services.communication.email_service.get_email_service")
    def test_unknown_status_uses_generic_config(self, mock_get_email, mock_get_mollie):
        """Test that unknown status uses generic notification config"""
        mock_member = MagicMock()
        mock_member.email = "test@example.com"
        mock_member.name = "MEM-001"
        mock_member.full_name = "Test Member"

        mock_email_service = MagicMock()
        mock_get_email.return_value = mock_email_service

        mock_mollie_config = MagicMock()
        mock_mollie_config.get_default_company.return_value = "Test Company"
        mock_get_mollie.return_value = mock_mollie_config

        self.service.send_status_change_notification(
            mock_member, "Active", "CustomStatus"
        )

        call_kwargs = mock_email_service.send_templated_email.call_args[1]
        self.assertEqual(call_kwargs["notification_key"], "member_status_change")
        self.assertIn("CustomStatus", call_kwargs["subject_override"])


class TestMemberStatusNotificationServiceConfig(unittest.TestCase):
    """Test _get_notification_config() method"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.lifecycle.member_status_notification_service import (
            get_member_status_notification_service,
        )
        self.service = get_member_status_notification_service()

    def test_active_config(self):
        """Test notification config for Active status"""
        config = self.service._get_notification_config("Pending", "Active")

        self.assertEqual(config["notification_key"], "member_activated")
        self.assertEqual(config["subject"], "Your Membership is Now Active")
        self.assertIn("activated", config["message"])

    def test_suspended_config(self):
        """Test notification config for Suspended status"""
        config = self.service._get_notification_config("Active", "Suspended")

        self.assertEqual(config["notification_key"], "member_suspended")
        self.assertEqual(config["subject"], "Membership Suspended")
        self.assertIn("suspended", config["message"])

    def test_terminated_config(self):
        """Test notification config for Terminated status"""
        config = self.service._get_notification_config("Active", "Quit")

        self.assertEqual(config["notification_key"], "member_terminated")
        self.assertEqual(config["subject"], "Membership Terminated")
        self.assertIn("terminated", config["message"])

    def test_generic_config_for_unknown_status(self):
        """Test generic notification config for unknown status"""
        config = self.service._get_notification_config("Active", "UnknownStatus")

        self.assertEqual(config["notification_key"], "member_status_change")
        self.assertIn("UnknownStatus", config["subject"])
        self.assertIn("Active", config["message"])
        self.assertIn("UnknownStatus", config["message"])


class TestMemberStatusNotificationServiceContext(unittest.TestCase):
    """Test _build_email_context() method"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.lifecycle.member_status_notification_service import (
            get_member_status_notification_service,
        )
        self.service = get_member_status_notification_service()

    @patch("verenigingen.verenigingen_payments.services.mollie_configuration_service.get_mollie_config")
    def test_context_includes_member_name(self, mock_get_mollie):
        """Test that context includes member name"""
        mock_member = MagicMock()
        mock_member.full_name = "John Doe"
        mock_member.first_name = "John"
        mock_member.last_name = "Doe"

        mock_mollie_config = MagicMock()
        mock_mollie_config.get_default_company.return_value = "Test Company"
        mock_get_mollie.return_value = mock_mollie_config

        config = {"message": "Test message"}
        context = self.service._build_email_context(
            mock_member, "Pending", "Active", config
        )

        self.assertEqual(context["member_name"], "John Doe")

    @patch("verenigingen.verenigingen_payments.services.mollie_configuration_service.get_mollie_config")
    def test_context_uses_first_last_name_when_no_full_name(self, mock_get_mollie):
        """Test that context uses first/last name when full_name is empty"""
        mock_member = MagicMock()
        mock_member.full_name = None
        mock_member.first_name = "Jane"
        mock_member.last_name = "Smith"

        mock_mollie_config = MagicMock()
        mock_mollie_config.get_default_company.return_value = "Test Company"
        mock_get_mollie.return_value = mock_mollie_config

        config = {"message": "Test message"}
        context = self.service._build_email_context(
            mock_member, "Pending", "Active", config
        )

        self.assertEqual(context["member_name"], "Jane Smith")

    @patch("verenigingen.verenigingen_payments.services.mollie_configuration_service.get_mollie_config")
    def test_context_includes_status_info(self, mock_get_mollie):
        """Test that context includes old and new status"""
        mock_member = MagicMock()
        mock_member.full_name = "Test Member"

        mock_mollie_config = MagicMock()
        mock_mollie_config.get_default_company.return_value = "Test Company"
        mock_get_mollie.return_value = mock_mollie_config

        config = {"message": "Test message"}
        context = self.service._build_email_context(
            mock_member, "Pending", "Active", config
        )

        self.assertEqual(context["old_status"], "Pending")
        self.assertEqual(context["new_status"], "Active")
        self.assertEqual(context["change_type"], "Status Change")

    @patch("verenigingen.verenigingen_payments.services.mollie_configuration_service.get_mollie_config")
    def test_context_includes_company(self, mock_get_mollie):
        """Test that context includes company from mollie config"""
        mock_member = MagicMock()
        mock_member.full_name = "Test Member"

        mock_mollie_config = MagicMock()
        mock_mollie_config.get_default_company.return_value = "My Association"
        mock_get_mollie.return_value = mock_mollie_config

        config = {"message": "Test message"}
        context = self.service._build_email_context(
            mock_member, "Pending", "Active", config
        )

        self.assertEqual(context["company"], "My Association")


if __name__ == "__main__":
    unittest.main()
