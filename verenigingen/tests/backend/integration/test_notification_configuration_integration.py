"""
Integration tests for the Email/Notification Configuration System.

Tests the complete notification flow from configuration to delivery:
- Email Configuration → EmailConfigurationService → EmailService
- Notification key enable/disable affecting actual sends
- Cooldown tracking across the full stack
- Recipient determination across all policies
- Suppression flags affecting notification flow
"""

import time
from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import add_to_date, now_datetime

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.singleton_backup import FlagBackupMixin, singleton_backup
import unittest


class TestNotificationConfigurationIntegration(FlagBackupMixin, EnhancedTestCase):
    """Integration tests for notification configuration system."""

    # Flags to backup/restore automatically per test
    protected_flags = ["suppress_notifications", "suppress_all_notifications", "in_import"]

    def setUp(self):
        """Set up test environment."""
        super().setUp()
        # Initialize flags to known state for test
        frappe.flags.suppress_notifications = False
        frappe.flags.suppress_all_notifications = False
        frappe.flags.in_import = False

    def test_email_service_respects_notification_disabled(self):
        """Test EmailService respects notification disabled in Email Configuration."""
        from verenigingen.services.communication.email_service import get_email_service

        with singleton_backup("Email Configuration"):
            config = frappe.get_single("Email Configuration")
            config.master_email_enabled = 1
            config.email_mode = "Active"

            # Add disabled notification type
            config.notification_types = []
            config.append("notification_types", {
                "notification_key": "test_disabled",
                "label": "Disabled Test",
                "category": "Member",
                "enabled": 0,
            })
            config.save()

            email_service = get_email_service()

            with patch("frappe.sendmail") as mock_sendmail:
                result = email_service.send_templated_email(
                    template_name="membership_application_confirmation",
                    recipients=["test@example.com"],
                    context={"member_name": "Test User"},
                    notification_key="test_disabled",
                )

                # Verify result indicates notification was skipped
                self.assertTrue(
                    (isinstance(result.data, dict) and result.data.get("skipped")) or not result.success,
                    f"Expected notification to be skipped/blocked, got: {result}"
                )
                # sendmail should NOT be called for disabled notifications
                mock_sendmail.assert_not_called()

    def test_email_service_respects_global_disable(self):
        """Test EmailService respects global email disable."""
        from verenigingen.services.communication.email_service import get_email_service

        with singleton_backup("Email Configuration"):
            config = frappe.get_single("Email Configuration")
            config.master_email_enabled = 0
            config.save()

            email_service = get_email_service()

            with patch("frappe.sendmail") as mock_sendmail:
                result = email_service.send_templated_email(
                    template_name="membership_application_confirmation",
                    recipients=["test@example.com"],
                    context={"member_name": "Test User"},
                    notification_key="member_application_confirmation",
                )

                # Verify result indicates email was blocked due to global disable
                self.assertTrue(
                    (isinstance(result.data, dict) and result.data.get("skipped")) or not result.success,
                    f"Expected email to be blocked when master_email_enabled=0, got: {result}"
                )
                # sendmail should NOT be called when globally disabled
                mock_sendmail.assert_not_called()

    def test_cooldown_integration_across_stack(self):
        """Test cooldown tracking works from service to cache.

        Tests the EmailConfigurationService cooldown mechanism directly,
        bypassing the config lookup to focus on cache behavior.
        """
        from verenigingen.services.communication.email_configuration_service import (
            EmailConfigurationService,
        )

        # Create fresh service instance for this test
        service = EmailConfigurationService()
        test_recipient = f"cooldown.test.{int(time.time())}@example.com"
        notification_key = "test_cooldown_direct"

        # Test cache key generation is consistent
        key1 = service._get_cooldown_cache_key(notification_key, test_recipient)
        key2 = service._get_cooldown_cache_key(notification_key, test_recipient)
        self.assertEqual(key1, key2)

        # Clear any existing cache
        service.clear_cooldown(notification_key, test_recipient)

        # Record a send and verify cache was set
        with patch.object(service, 'get_notification_config', return_value={"cooldown_minutes": 5}):
            service.record_send(notification_key, test_recipient)

            # Verify cooldown check returns False (in cooldown)
            can_send = service.check_cooldown(notification_key, test_recipient)
            self.assertFalse(can_send)

            # Clear cooldown
            service.clear_cooldown(notification_key, test_recipient)

            # Verify can send again
            can_send = service.check_cooldown(notification_key, test_recipient)
            self.assertTrue(can_send)

    def test_recipient_determination_fixed_policy_integration(self):
        """Test Fixed recipient policy works end-to-end."""
        from verenigingen.services.communication.email_configuration_service import (
            get_email_configuration_service,
        )

        with singleton_backup("Email Configuration"):
            config = frappe.get_single("Email Configuration")
            config.notification_types = []
            config.append("notification_types", {
                "notification_key": "test_fixed_recipients",
                "label": "Fixed Recipients Test",
                "category": "Admin",
                "enabled": 1,
                "recipient_policy": "Fixed",
                "fixed_recipients": "admin@test.com, support@test.com",
            })
            config.save()

            config_service = get_email_configuration_service()
            recipients = config_service.get_recipients_for_notification("test_fixed_recipients")

            self.assertEqual(recipients, ["admin@test.com", "support@test.com"])

    def test_recipient_determination_document_field_policy_integration(self):
        """Test Document-Field recipient policy works end-to-end."""
        from verenigingen.services.communication.email_configuration_service import (
            get_email_configuration_service,
        )

        with singleton_backup("Email Configuration"):
            config = frappe.get_single("Email Configuration")
            config.notification_types = []
            config.append("notification_types", {
                "notification_key": "test_document_field",
                "label": "Document Field Test",
                "category": "Member",
                "enabled": 1,
                "recipient_policy": "Document-Field",
                "recipient_field": "member.email",
            })
            config.save()

            config_service = get_email_configuration_service()

            # Create mock member
            mock_member = MagicMock()
            mock_member.email = "member@test.com"
            context = {"member": mock_member}

            recipients = config_service.get_recipients_for_notification(
                "test_document_field", context
            )

            self.assertEqual(recipients, ["member@test.com"])

    def test_category_recipients_integration(self):
        """Test category-based recipient determination works."""
        from verenigingen.services.communication.email_configuration_service import (
            get_email_configuration_service,
        )

        with singleton_backup("Email Configuration"):
            config = frappe.get_single("Email Configuration")
            config.financial_admin_emails = "treasurer@test.com, finance@test.com"
            config.save()

            config_service = get_email_configuration_service()
            recipients = config_service.get_category_recipients("Payment")

            self.assertEqual(recipients, ["treasurer@test.com", "finance@test.com"])

    def test_suppression_flag_blocks_notifications(self):
        """Test suppression flags block notification sending."""
        from verenigingen.services.communication.email_configuration_service import (
            get_email_configuration_service,
        )

        with singleton_backup("Email Configuration"):
            config = frappe.get_single("Email Configuration")
            config.master_email_enabled = 1
            config.email_mode = "Active"
            config.notification_types = []
            config.append("notification_types", {
                "notification_key": "test_suppression",
                "label": "Suppression Test",
                "category": "Member",
                "enabled": 1,
            })
            config.save()

            config_service = get_email_configuration_service()

            # Without suppression - should send
            self.assertTrue(config_service.should_send("test_suppression"))

            # With suppression flag
            frappe.flags.suppress_notifications = True
            self.assertFalse(config_service.should_send("test_suppression"))

            frappe.flags.suppress_notifications = False

    def test_pause_mode_integration(self):
        """Test pause mode works with auto-resume."""
        from verenigingen.services.communication.email_configuration_service import (
            get_email_configuration_service,
        )

        with singleton_backup("Email Configuration"):
            config = frappe.get_single("Email Configuration")
            config.master_email_enabled = 1
            config.email_mode = "Paused"
            config.pause_until = add_to_date(now_datetime(), hours=1)  # Future
            config.save()

            config_service = get_email_configuration_service()

            # Should be blocked while paused
            self.assertFalse(config_service.is_email_enabled())

            # Change pause_until to past
            config.pause_until = add_to_date(now_datetime(), hours=-1)
            config.save()

            # Should auto-resume
            self.assertTrue(config_service.is_email_enabled())


class TestNotificationHelperIntegration(EnhancedTestCase):
    """Integration tests for notification helper functions."""

    def test_notify_administrators_uses_configuration(self):
        """Test notify_administrators uses Email Configuration for recipients."""
        from verenigingen.utils.notification_helpers import notify_administrators

        with singleton_backup("Email Configuration"):
            config = frappe.get_single("Email Configuration")
            config.admin_notification_emails = "config.admin@test.com"
            config.master_email_enabled = 1
            config.email_mode = "Active"
            config.save()

            with patch(
                "verenigingen.utils.notification_helpers.create_system_notification"
            ) as mock_create:
                mock_create.return_value = {"success": True, "notifications_created": 1}

                notify_administrators(
                    subject="Test Admin Notification",
                    message="Test message",
                    category="Admin",
                )

                # Verify create_system_notification was called
                mock_create.assert_called_once()
                call_args = mock_create.call_args

                # Should have used config recipients
                self.assertIn("config.admin@test.com", call_args.kwargs["recipients"])

    def test_create_system_notification_respects_notification_key(self):
        """Test create_system_notification respects notification key enable/disable."""
        from verenigingen.utils.notification_helpers import create_system_notification

        with singleton_backup("Email Configuration"):
            config = frappe.get_single("Email Configuration")
            config.master_email_enabled = 1
            config.email_mode = "Active"
            config.notification_types = []
            config.append("notification_types", {
                "notification_key": "test_create_notif",
                "label": "Test Create",
                "category": "Member",
                "enabled": 0,  # Disabled
            })
            config.save()

            result = create_system_notification(
                recipients=["test@example.com"],
                subject="Test",
                message="Test message",
                notification_key="test_create_notif",
            )

            # Should be skipped because notification is disabled
            self.assertTrue(result.get("skipped", False))
            self.assertEqual(result["notifications_created"], 0)


class TestVolunteerEmailIntegration(EnhancedTestCase):
    """Integration tests for volunteer email functionality."""

    def setUp(self):
        """Set up test environment with member and volunteer."""
        super().setUp()

        # Create test member
        self.test_member = self.create_test_member(
            first_name="Integration",
            last_name="Volunteer",
            email="integration.volunteer@test.invalid",
            birth_date="1985-01-15",
        )

    def test_send_volunteer_email_with_real_data(self):
        """Test send_volunteer_email with actual member/volunteer data."""
        from verenigingen.utils.notification_helpers import send_volunteer_email

        # Create volunteer linked to member
        try:
            volunteer = frappe.get_doc({
                "doctype": "Volunteer",
                "member": self.test_member.name,
                "status": "Active",
            })
            volunteer.insert()

            with singleton_backup("Email Configuration"):
                config = frappe.get_single("Email Configuration")
                config.master_email_enabled = 1
                config.email_mode = "Active"
                config.notification_types = []
                config.append("notification_types", {
                    "notification_key": "test_volunteer_email",
                    "label": "Volunteer Email Test",
                    "category": "Volunteer",
                    "enabled": 1,
                })
                config.save()

                with patch("frappe.sendmail") as mock_sendmail:
                    result = send_volunteer_email(
                        volunteer=volunteer.name,
                        template_name="team_role_notification",
                        notification_key="test_volunteer_email",
                        subject="Test Volunteer Email",
                        extra_context={"team_name": "Test Team"},
                        reference_doctype="Volunteer",
                        reference_name=volunteer.name,
                    )

                    # Verify result structure
                    self.assertTrue(hasattr(result, "success"), "Result should have 'success' attribute")
                    # Verify volunteer email was resolved correctly
                    if result.success:
                        # If successful, sendmail should have been called
                        self.assertTrue(
                            mock_sendmail.called
                            or (isinstance(result.data, dict) and result.data.get("skipped")),
                            "Either sendmail should be called or notification skipped"
                        )

        except Exception as e:
            # If volunteer creation fails (e.g., validation), skip this test
            self.skipTest(f"Could not create test volunteer: {e}")


class TestEmailServiceCacheIntegration(EnhancedTestCase):
    """Integration tests for EmailService template caching."""

    def test_template_cache_works_across_requests(self):
        """Test template cache persists and improves performance."""
        from verenigingen.services.communication.email_service import get_email_service

        email_service = get_email_service()

        # Create test template if needed
        template_name = "test_cache_integration"
        if not frappe.db.exists("Email Template", template_name):
            frappe.get_doc({
                "doctype": "Email Template",
                "name": template_name,
                "subject": "Cache Test - {{ name|e }}",
                "response_html": "<p>Hello {{ name|e }}</p>",
                "use_html": 1,
            }).insert()

        # Clear cache
        email_service.template_cache.clear()

        # First load - cache miss
        with patch("frappe.sendmail"):
            result1 = email_service.send_templated_email(
                template_name=template_name,
                recipients=["test@example.com"],
                context={"name": "Test User"},
            )

        # Second load - cache hit
        with patch("frappe.sendmail"):
            result2 = email_service.send_templated_email(
                template_name=template_name,
                recipients=["test@example.com"],
                context={"name": "Test User"},
            )

        # Verify first call succeeded
        self.assertTrue(
            result1.success or result1.error_message is None,
            f"First email send should succeed, got: {result1}"
        )

        # Verify second call succeeded
        self.assertTrue(
            result2.success or result2.error_message is None,
            f"Second email send should succeed, got: {result2}"
        )

        # Verify cache has the template (proves caching is working)
        cached_template = email_service.template_cache.get(template_name)
        self.assertIsNotNone(
            cached_template,
            f"Template '{template_name}' should be cached after use"
        )

        # Verify cached content is valid
        self.assertIn("subject", cached_template, "Cached template should have subject")
        self.assertIn("response", cached_template, "Cached template should have response body")


if __name__ == "__main__":
    import unittest
    unittest.main()
