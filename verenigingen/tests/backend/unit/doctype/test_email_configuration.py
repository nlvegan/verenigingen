"""
Unit tests for Email Configuration DocType.

Tests the Email Configuration singleton DocType including:
- Validation logic (email formats, unique keys)
- is_email_enabled() with pause logic
- get_notification_config() method
- is_notification_enabled() method
- get_recipients_for_category() method
- Auto-resume from pause
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from verenigingen.tests.fixtures.singleton_backup import singleton_backup


class TestEmailConfigurationValidation(FrappeTestCase):
    """Test Email Configuration validation logic."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()

    def test_validates_unique_notification_keys(self):
        """Test validation fails for duplicate notification keys."""
        with singleton_backup("Email Configuration"):
            config = frappe.get_single("Email Configuration")

            # Add two notification types with same key
            config.notification_types = []
            config.append("notification_types", {
                "notification_key": "duplicate_key",
                "label": "First Notification",
                "category": "Member",
                "enabled": 1,
            })
            config.append("notification_types", {
                "notification_key": "duplicate_key",
                "label": "Second Notification",
                "category": "Member",
                "enabled": 1,
            })

            with self.assertRaises(frappe.ValidationError) as ctx:
                config.validate()

            self.assertIn("unique", str(ctx.exception).lower())

    def test_validates_email_format_in_admin_emails(self):
        """Test validation fails for invalid email in admin_notification_emails."""
        with singleton_backup("Email Configuration"):
            config = frappe.get_single("Email Configuration")
            config.admin_notification_emails = "valid@test.com, invalid-email, another@test.com"

            with self.assertRaises(frappe.ValidationError) as ctx:
                config.validate()

            self.assertIn("invalid", str(ctx.exception).lower())

    def test_validates_email_format_in_financial_emails(self):
        """Test validation fails for invalid email in financial_admin_emails."""
        with singleton_backup("Email Configuration"):
            config = frappe.get_single("Email Configuration")
            config.financial_admin_emails = "not-an-email"

            with self.assertRaises(frappe.ValidationError) as ctx:
                config.validate()

            self.assertIn("invalid", str(ctx.exception).lower())

    def test_warns_about_pause_without_resume_time(self):
        """Test warns when paused without pause_until set."""
        with singleton_backup("Email Configuration"):
            config = frappe.get_single("Email Configuration")
            config.email_mode = "Paused"
            config.pause_until = None

            # Should not raise, but should msgprint warning
            with patch("frappe.msgprint") as mock_msgprint:
                config._validate_pause_settings()
                mock_msgprint.assert_called_once()
                call_args = mock_msgprint.call_args
                self.assertIn("Pause Until", call_args.args[0])


class TestEmailConfigurationIsEmailEnabled(FrappeTestCase):
    """Test is_email_enabled() logic."""

    def test_returns_false_when_master_disabled(self):
        """Test returns False when master_email_enabled is off."""
        with singleton_backup("Email Configuration"):
            config = frappe.get_single("Email Configuration")
            config.master_email_enabled = 0
            config.email_mode = "Active"

            self.assertFalse(config.is_email_enabled())

    def test_returns_true_when_active(self):
        """Test returns True when enabled and active."""
        with singleton_backup("Email Configuration"):
            config = frappe.get_single("Email Configuration")
            config.master_email_enabled = 1
            config.email_mode = "Active"

            self.assertTrue(config.is_email_enabled())

    def test_returns_false_when_paused_indefinitely(self):
        """Test returns False when paused with no resume time."""
        with singleton_backup("Email Configuration"):
            config = frappe.get_single("Email Configuration")
            config.master_email_enabled = 1
            config.email_mode = "Paused"
            config.pause_until = None

            self.assertFalse(config.is_email_enabled())

    def test_returns_false_when_paused_until_future(self):
        """Test returns False when paused until future time."""
        with singleton_backup("Email Configuration"):
            config = frappe.get_single("Email Configuration")
            config.master_email_enabled = 1
            config.email_mode = "Paused"
            config.pause_until = add_to_date(now_datetime(), hours=1)

            self.assertFalse(config.is_email_enabled())

    def test_auto_resumes_when_pause_expires(self):
        """Test auto-resumes to Active when pause_until is past."""
        with singleton_backup("Email Configuration"):
            config = frappe.get_single("Email Configuration")
            config.master_email_enabled = 1
            config.email_mode = "Paused"
            config.pause_until = add_to_date(now_datetime(), hours=-1)  # Past

            # Mock db_set to verify auto-resume
            with patch.object(config, "db_set") as mock_db_set:
                result = config.is_email_enabled()

                self.assertTrue(result)
                mock_db_set.assert_called_with("email_mode", "Active")


class TestEmailConfigurationGetNotificationConfig(FrappeTestCase):
    """Test get_notification_config() method."""

    def test_returns_empty_dict_for_unknown_key(self):
        """Test returns empty dict for unknown notification key."""
        with singleton_backup("Email Configuration"):
            config = frappe.get_single("Email Configuration")
            result = config.get_notification_config("nonexistent_key")
            self.assertEqual(result, {})

    def test_returns_full_config_for_known_key(self):
        """Test returns full configuration for known notification key."""
        with singleton_backup("Email Configuration"):
            config = frappe.get_single("Email Configuration")

            # Add a test notification type
            config.notification_types = []
            config.append("notification_types", {
                "notification_key": "test_key",
                "label": "Test Notification",
                "category": "Member",
                "priority": "High",
                "enabled": 1,
                "cooldown_minutes": 30,
                "email_template": "test_template",
                "recipient_policy": "Fixed",
                "fixed_recipients": "admin@test.com",
                "description": "Test description",
            })

            result = config.get_notification_config("test_key")

            self.assertEqual(result["enabled"], True)
            self.assertEqual(result["label"], "Test Notification")
            self.assertEqual(result["category"], "Member")
            self.assertEqual(result["priority"], "High")
            self.assertEqual(result["cooldown_minutes"], 30)
            self.assertEqual(result["email_template"], "test_template")
            self.assertEqual(result["recipient_policy"], "Fixed")
            self.assertEqual(result["fixed_recipients"], "admin@test.com")


class TestEmailConfigurationIsNotificationEnabled(FrappeTestCase):
    """Test is_notification_enabled() method."""

    def test_returns_false_for_disabled_notification(self):
        """Test returns False for disabled notification type."""
        with singleton_backup("Email Configuration"):
            config = frappe.get_single("Email Configuration")

            config.notification_types = []
            config.append("notification_types", {
                "notification_key": "disabled_key",
                "label": "Disabled Notification",
                "category": "Member",
                "enabled": 0,
            })

            self.assertFalse(config.is_notification_enabled("disabled_key"))

    def test_returns_true_for_enabled_notification(self):
        """Test returns True for enabled notification type."""
        with singleton_backup("Email Configuration"):
            config = frappe.get_single("Email Configuration")

            config.notification_types = []
            config.append("notification_types", {
                "notification_key": "enabled_key",
                "label": "Enabled Notification",
                "category": "Member",
                "enabled": 1,
            })

            self.assertTrue(config.is_notification_enabled("enabled_key"))

    def test_returns_false_for_unknown_key(self):
        """Test returns False for unknown notification key."""
        with singleton_backup("Email Configuration"):
            config = frappe.get_single("Email Configuration")
            self.assertFalse(config.is_notification_enabled("unknown_key"))


class TestEmailConfigurationGetRecipientsForCategory(FrappeTestCase):
    """Test get_recipients_for_category() method."""

    def test_returns_system_emails_for_system_category(self):
        """Test returns system_alert_emails for System category."""
        with singleton_backup("Email Configuration"):
            config = frappe.get_single("Email Configuration")
            config.system_alert_emails = "system@test.com, alerts@test.com"

            result = config.get_recipients_for_category("System")
            self.assertEqual(result, ["system@test.com", "alerts@test.com"])

    def test_returns_admin_emails_for_admin_category(self):
        """Test returns admin_notification_emails for Admin category."""
        with singleton_backup("Email Configuration"):
            config = frappe.get_single("Email Configuration")
            config.admin_notification_emails = "admin@test.com"
            config.system_alert_emails = None

            result = config.get_recipients_for_category("Admin")
            self.assertEqual(result, ["admin@test.com"])

    def test_returns_financial_emails_for_payment_category(self):
        """Test returns financial_admin_emails for Payment category."""
        with singleton_backup("Email Configuration"):
            config = frappe.get_single("Email Configuration")
            config.financial_admin_emails = "finance@test.com"

            result = config.get_recipients_for_category("Payment")
            self.assertEqual(result, ["finance@test.com"])

    def test_falls_back_to_role_based_lookup(self):
        """Test falls back to role-based lookup when no category emails."""
        with singleton_backup("Email Configuration"):
            config = frappe.get_single("Email Configuration")
            config.admin_notification_emails = None
            config.fallback_admin_role = "System Manager"

            with patch.object(config, "_get_users_with_role", return_value=["fallback@test.com"]):
                result = config.get_recipients_for_category("Admin")
                self.assertEqual(result, ["fallback@test.com"])


class TestEmailConfigurationHelperMethods(FrappeTestCase):
    """Test helper methods."""

    def test_parse_email_list_handles_empty(self):
        """Test _parse_email_list handles empty input."""
        with singleton_backup("Email Configuration"):
            config = frappe.get_single("Email Configuration")

            self.assertEqual(config._parse_email_list(""), [])
            self.assertEqual(config._parse_email_list(None), [])

    def test_parse_email_list_splits_and_strips(self):
        """Test _parse_email_list properly splits and strips."""
        with singleton_backup("Email Configuration"):
            config = frappe.get_single("Email Configuration")

            result = config._parse_email_list("  a@test.com , b@test.com  , c@test.com  ")
            self.assertEqual(result, ["a@test.com", "b@test.com", "c@test.com"])

    def test_get_users_with_role_returns_emails(self):
        """Test _get_users_with_role returns user emails."""
        with singleton_backup("Email Configuration"):
            config = frappe.get_single("Email Configuration")

            # This depends on actual database state, so we mock it
            with patch("frappe.get_all") as mock_get_all:
                mock_get_all.side_effect = [
                    ["Administrator"],  # First call: Has Role
                    ["admin@test.com"],  # Second call: User emails
                ]

                result = config._get_users_with_role("System Manager")

                # Verify queries were made
                self.assertEqual(mock_get_all.call_count, 2)


class TestEmailConfigurationSchema(FrappeTestCase):
    """Test Email Configuration DocType schema matches code expectations."""

    def test_required_fields_exist_in_doctype(self):
        """Verify all fields referenced in code exist in DocType JSON."""
        doctype_meta = frappe.get_meta("Email Configuration")
        field_names = {f.fieldname for f in doctype_meta.fields}

        required_fields = {
            'master_email_enabled', 'email_mode', 'pause_until',
            'admin_notification_emails', 'financial_admin_emails',
            'system_alert_emails', 'fallback_admin_role',
            'suppress_during_imports', 'notification_types'
        }

        missing = required_fields - field_names
        self.assertEqual(missing, set(), f"Missing fields in Email Configuration DocType: {missing}")

    def test_notification_types_is_table_field(self):
        """Verify notification_types is a Table field for child entries."""
        doctype_meta = frappe.get_meta("Email Configuration")
        field = doctype_meta.get_field("notification_types")

        self.assertIsNotNone(field, "notification_types field not found")
        self.assertEqual(field.fieldtype, "Table")


class TestSendTestEmail(FrappeTestCase):
    """Test send_test_email API function."""

    def test_rejects_invalid_email(self):
        """Test rejects invalid email address."""
        from verenigingen.verenigingen.doctype.email_configuration.email_configuration import (
            send_test_email,
        )

        # Test with invalid email formats
        result = send_test_email("not-an-email")
        self.assertFalse(result["success"])
        self.assertIn("Invalid email address", result["error"])

        result = send_test_email("")
        self.assertFalse(result["success"])

    def test_sends_test_email_via_email_service(self):
        """Test sends test email using EmailService."""
        from verenigingen.verenigingen.doctype.email_configuration.email_configuration import (
            send_test_email,
        )

        with patch("verenigingen.services.communication.email_service.get_email_service") as mock_get_service:
            mock_service = MagicMock()
            mock_service.send_simple_email.return_value = {"success": True}
            mock_get_service.return_value = mock_service

            result = send_test_email("test@example.com")

            self.assertTrue(result["success"])
            mock_service.send_simple_email.assert_called_once()

    def test_handles_email_service_error(self):
        """Test handles error from email service."""
        from verenigingen.verenigingen.doctype.email_configuration.email_configuration import (
            send_test_email,
        )

        with patch("verenigingen.services.communication.email_service.get_email_service") as mock_get_service:
            mock_service = MagicMock()
            mock_service.send_simple_email.return_value = {"success": False, "error": "SMTP failed"}
            mock_get_service.return_value = mock_service

            result = send_test_email("test@example.com")

            self.assertFalse(result["success"])
            self.assertEqual(result["error"], "SMTP failed")


if __name__ == "__main__":
    import unittest
    unittest.main()
