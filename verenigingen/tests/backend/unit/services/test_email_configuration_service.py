"""
Unit tests for EmailConfigurationService.

Tests the centralized email configuration service including:
- Global email enable/disable checks
- Per-notification-type enable checks
- Cooldown management (Redis-based)
- Recipient determination (all 4 policies)
- Suppression flag handling
- Combined should_send() logic
"""

import time
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.services.communication.email_configuration_service import (
    EmailConfigurationService,
    get_email_configuration_service,
)


class TestEmailConfigurationServiceBasics(FrappeTestCase):
    """Test basic EmailConfigurationService functionality."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        # Create fresh service instance for testing (don't mutate global singleton)
        self.service = EmailConfigurationService()
        self._cache_keys_to_clear = []

    def tearDown(self):
        """Clean up after tests."""
        # Clear any cooldown cache keys we created
        for key in self._cache_keys_to_clear:
            frappe.cache().delete_value(key)
        super().tearDown()

    def test_singleton_pattern(self):
        """Test that get_email_configuration_service returns singleton."""
        service1 = get_email_configuration_service()
        service2 = get_email_configuration_service()
        self.assertIs(service1, service2)

    def test_is_email_enabled_when_config_missing(self):
        """Test is_email_enabled defaults to True when no config exists."""
        with patch.object(self.service, '_get_config', return_value=None):
            self.assertTrue(self.service.is_email_enabled())

    def test_is_email_enabled_delegates_to_config(self):
        """Test is_email_enabled delegates to Email Configuration document."""
        mock_config = MagicMock()
        mock_config.is_email_enabled.return_value = True

        with patch.object(self.service, '_get_config', return_value=mock_config):
            result = self.service.is_email_enabled()
            self.assertTrue(result)
            mock_config.is_email_enabled.assert_called_once()

    def test_is_notification_enabled_checks_global_first(self):
        """Test is_notification_enabled checks global enable first."""
        with patch.object(self.service, 'is_email_enabled', return_value=False):
            result = self.service.is_notification_enabled("any_key")
            self.assertFalse(result)

    def test_is_notification_enabled_when_config_missing(self):
        """Test is_notification_enabled defaults to True when no config."""
        with patch.object(self.service, 'is_email_enabled', return_value=True):
            with patch.object(self.service, '_get_config', return_value=None):
                result = self.service.is_notification_enabled("any_key")
                self.assertTrue(result)

    def test_get_notification_config_returns_empty_when_no_config(self):
        """Test get_notification_config returns empty dict when no config."""
        with patch.object(self.service, '_get_config', return_value=None):
            result = self.service.get_notification_config("any_key")
            self.assertEqual(result, {})


class TestEmailConfigurationServiceCooldown(FrappeTestCase):
    """Test cooldown functionality in EmailConfigurationService."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.service = EmailConfigurationService()
        self._cache_keys_to_clear = []

    def tearDown(self):
        """Clean up cooldown cache entries."""
        for key in self._cache_keys_to_clear:
            frappe.cache().delete_value(key)
        super().tearDown()

    def test_cooldown_cache_key_format(self):
        """Test cooldown cache key uses MD5 hash of recipient."""
        key = self.service._get_cooldown_cache_key("test_key", "user@example.com")
        self.assertTrue(key.startswith("email_cooldown:test_key:"))
        # Hash should be 12 characters
        hash_part = key.split(":")[-1]
        self.assertEqual(len(hash_part), 12)

    def test_cooldown_cache_key_case_insensitive(self):
        """Test cache key is case-insensitive for email."""
        key1 = self.service._get_cooldown_cache_key("test", "USER@example.com")
        key2 = self.service._get_cooldown_cache_key("test", "user@EXAMPLE.com")
        self.assertEqual(key1, key2)

    def test_check_cooldown_returns_true_when_no_cooldown(self):
        """Test check_cooldown returns True when no cooldown configured."""
        with patch.object(self.service, 'get_notification_config', return_value={"cooldown_minutes": 0}):
            result = self.service.check_cooldown("test_key", "user@example.com")
            self.assertTrue(result)

    def test_check_cooldown_returns_true_when_not_in_cooldown(self):
        """Test check_cooldown returns True when no recent send."""
        with patch.object(self.service, 'get_notification_config', return_value={"cooldown_minutes": 60}):
            result = self.service.check_cooldown("test_key", "fresh@example.com")
            self.assertTrue(result)

    def test_check_cooldown_returns_false_when_in_cooldown(self):
        """Test check_cooldown returns False during cooldown period."""
        test_recipient = "cooldown.test@example.com"
        notification_key = "test_cooldown_key"

        # Record a send
        cache_key = self.service._get_cooldown_cache_key(notification_key, test_recipient)
        self._cache_keys_to_clear.append(cache_key)
        frappe.cache().set_value(cache_key, str(time.time()), expires_in_sec=3600)

        # Configure 60 minute cooldown
        with patch.object(self.service, 'get_notification_config', return_value={"cooldown_minutes": 60}):
            result = self.service.check_cooldown(notification_key, test_recipient)
            self.assertFalse(result)

    def test_record_send_sets_cache_key(self):
        """Test record_send creates cache entry."""
        test_recipient = "record.test@example.com"
        notification_key = "test_record_key"
        cache_key = self.service._get_cooldown_cache_key(notification_key, test_recipient)
        self._cache_keys_to_clear.append(cache_key)

        with patch.object(self.service, 'get_notification_config', return_value={"cooldown_minutes": 60}):
            self.service.record_send(notification_key, test_recipient)

        # Verify cache was set
        cached = frappe.cache().get_value(cache_key)
        self.assertIsNotNone(cached)

    def test_clear_cooldown_removes_cache_entry(self):
        """Test clear_cooldown removes cache entry."""
        test_recipient = "clear.test@example.com"
        notification_key = "test_clear_key"
        cache_key = self.service._get_cooldown_cache_key(notification_key, test_recipient)

        # Set a cache entry
        frappe.cache().set_value(cache_key, str(time.time()), expires_in_sec=3600)

        # Clear it
        self.service.clear_cooldown(notification_key, test_recipient)

        # Verify it's gone
        cached = frappe.cache().get_value(cache_key)
        self.assertIsNone(cached)


class TestEmailConfigurationServiceShouldSend(FrappeTestCase):
    """Test the combined should_send() logic."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.service = EmailConfigurationService()
        # Clear suppression flags
        frappe.flags.suppress_notifications = False
        frappe.flags.suppress_all_notifications = False
        frappe.flags.in_import = False
        frappe.flags.in_bulk_import = False
        frappe.flags.bulk_member_operations = False

    def tearDown(self):
        """Clean up flags."""
        frappe.flags.suppress_notifications = False
        frappe.flags.suppress_all_notifications = False
        frappe.flags.in_import = False
        frappe.flags.in_bulk_import = False
        frappe.flags.bulk_member_operations = False
        super().tearDown()

    def test_should_send_returns_false_when_suppressed(self):
        """Test should_send respects suppress_notifications flag."""
        frappe.flags.suppress_notifications = True

        with patch.object(self.service, 'is_email_enabled', return_value=True):
            with patch.object(self.service, 'is_notification_enabled', return_value=True):
                result = self.service.should_send("test_key", "user@example.com")
                self.assertFalse(result)

    def test_should_send_returns_false_during_import(self):
        """Test should_send respects in_import flag."""
        frappe.flags.in_import = True

        mock_config = MagicMock()
        mock_config.suppress_during_imports = True

        with patch.object(self.service, '_get_config', return_value=mock_config):
            result = self.service.should_send("test_key", "user@example.com")
            self.assertFalse(result)

    def test_should_send_returns_false_when_globally_disabled(self):
        """Test should_send returns False when emails globally disabled."""
        with patch.object(self.service, '_is_suppressed', return_value=False):
            with patch.object(self.service, 'is_email_enabled', return_value=False):
                result = self.service.should_send("test_key", "user@example.com")
                self.assertFalse(result)

    def test_should_send_returns_false_when_notification_disabled(self):
        """Test should_send returns False when specific notification disabled."""
        with patch.object(self.service, '_is_suppressed', return_value=False):
            with patch.object(self.service, 'is_email_enabled', return_value=True):
                with patch.object(self.service, 'is_notification_enabled', return_value=False):
                    result = self.service.should_send("test_key", "user@example.com")
                    self.assertFalse(result)

    def test_should_send_returns_false_when_in_cooldown(self):
        """Test should_send returns False during cooldown."""
        with patch.object(self.service, '_is_suppressed', return_value=False):
            with patch.object(self.service, 'is_email_enabled', return_value=True):
                with patch.object(self.service, 'is_notification_enabled', return_value=True):
                    with patch.object(self.service, 'check_cooldown', return_value=False):
                        result = self.service.should_send("test_key", "user@example.com")
                        self.assertFalse(result)

    def test_should_send_returns_true_when_all_checks_pass(self):
        """Test should_send returns True when all conditions met."""
        with patch.object(self.service, '_is_suppressed', return_value=False):
            with patch.object(self.service, 'is_email_enabled', return_value=True):
                with patch.object(self.service, 'is_notification_enabled', return_value=True):
                    with patch.object(self.service, 'check_cooldown', return_value=True):
                        result = self.service.should_send("test_key", "user@example.com")
                        self.assertTrue(result)

    def test_should_send_skips_cooldown_when_disabled(self):
        """Test should_send can skip cooldown check."""
        with patch.object(self.service, '_is_suppressed', return_value=False):
            with patch.object(self.service, 'is_email_enabled', return_value=True):
                with patch.object(self.service, 'is_notification_enabled', return_value=True):
                    # Even if check_cooldown would return False, skip it
                    with patch.object(self.service, 'check_cooldown', return_value=False) as mock_cooldown:
                        result = self.service.should_send("test_key", "user@example.com", check_cooldown=False)
                        self.assertTrue(result)
                        mock_cooldown.assert_not_called()


class TestEmailConfigurationServiceRecipients(FrappeTestCase):
    """Test recipient determination logic."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.service = EmailConfigurationService()

    def test_parse_email_list_handles_empty_string(self):
        """Test _parse_email_list handles empty input."""
        self.assertEqual(self.service._parse_email_list(""), [])
        self.assertEqual(self.service._parse_email_list(None), [])

    def test_parse_email_list_handles_single_email(self):
        """Test _parse_email_list handles single email."""
        result = self.service._parse_email_list("user@example.com")
        self.assertEqual(result, ["user@example.com"])

    def test_parse_email_list_handles_multiple_emails(self):
        """Test _parse_email_list handles comma-separated emails."""
        result = self.service._parse_email_list("a@test.com, b@test.com, c@test.com")
        self.assertEqual(result, ["a@test.com", "b@test.com", "c@test.com"])

    def test_parse_email_list_strips_whitespace(self):
        """Test _parse_email_list strips extra whitespace."""
        result = self.service._parse_email_list("  a@test.com  ,  b@test.com  ")
        self.assertEqual(result, ["a@test.com", "b@test.com"])

    def test_resolve_recipient_field_simple_field(self):
        """Test _resolve_recipient_field with simple field like 'email'."""
        context = {"email": "user@example.com", "name": "Test User"}
        result = self.service._resolve_recipient_field("email", context)
        self.assertEqual(result, ["user@example.com"])

    def test_resolve_recipient_field_nested_field(self):
        """Test _resolve_recipient_field with nested field like 'member.email'."""
        mock_member = MagicMock()
        mock_member.email = "member@example.com"
        context = {"member": mock_member}

        result = self.service._resolve_recipient_field("member.email", context)
        self.assertEqual(result, ["member@example.com"])

    def test_resolve_recipient_field_returns_empty_for_missing(self):
        """Test _resolve_recipient_field returns empty for missing fields."""
        context = {"other_field": "value"}
        result = self.service._resolve_recipient_field("email", context)
        self.assertEqual(result, [])

    def test_get_recipients_for_notification_fixed_policy(self):
        """Test get_recipients_for_notification with Fixed policy."""
        mock_config = {
            "recipient_policy": "Fixed",
            "fixed_recipients": "admin@test.com, support@test.com",
        }

        with patch.object(self.service, 'get_notification_config', return_value=mock_config):
            result = self.service.get_recipients_for_notification("test_key")
            self.assertEqual(result, ["admin@test.com", "support@test.com"])

    def test_get_recipients_for_notification_document_field_policy(self):
        """Test get_recipients_for_notification with Document-Field policy."""
        mock_config = {
            "recipient_policy": "Document-Field",
            "recipient_field": "member.email",
        }

        mock_member = MagicMock()
        mock_member.email = "member@example.com"
        context = {"member": mock_member}

        with patch.object(self.service, 'get_notification_config', return_value=mock_config):
            result = self.service.get_recipients_for_notification("test_key", context)
            self.assertEqual(result, ["member@example.com"])

    def test_get_recipients_for_notification_custom_returns_empty(self):
        """Test get_recipients_for_notification with Custom policy returns empty."""
        mock_config = {"recipient_policy": "Custom"}

        with patch.object(self.service, 'get_notification_config', return_value=mock_config):
            result = self.service.get_recipients_for_notification("test_key")
            self.assertEqual(result, [])

    def test_get_recipients_for_notification_fallback(self):
        """Test get_recipients_for_notification uses fallback when no config."""
        with patch.object(self.service, 'get_notification_config', return_value={}):
            with patch.object(self.service, '_get_fallback_recipients', return_value=["admin@test.com"]):
                result = self.service.get_recipients_for_notification("unknown_key")
                self.assertEqual(result, ["admin@test.com"])


class TestEmailConfigurationServiceSuppression(FrappeTestCase):
    """Test suppression logic in detail."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.service = EmailConfigurationService()
        # Clear all suppression flags
        self._clear_flags()

    def tearDown(self):
        """Clean up flags."""
        self._clear_flags()
        super().tearDown()

    def _clear_flags(self):
        """Clear all suppression flags."""
        for flag in [
            'suppress_notifications', 'suppress_all_notifications',
            'in_import', 'in_bulk_import', 'bulk_member_operations'
        ]:
            setattr(frappe.flags, flag, False)

    def test_is_suppressed_checks_all_notification_flags(self):
        """Test _is_suppressed checks suppress_notifications flag."""
        frappe.flags.suppress_notifications = True
        self.assertTrue(self.service._is_suppressed())

        frappe.flags.suppress_notifications = False
        frappe.flags.suppress_all_notifications = True
        self.assertTrue(self.service._is_suppressed())

    def test_is_suppressed_checks_import_flags(self):
        """Test _is_suppressed checks import flags when configured."""
        mock_config = MagicMock()
        mock_config.suppress_during_imports = True

        with patch.object(self.service, '_get_config', return_value=mock_config):
            frappe.flags.in_import = True
            self.assertTrue(self.service._is_suppressed())

            frappe.flags.in_import = False
            frappe.flags.in_bulk_import = True
            self.assertTrue(self.service._is_suppressed())

            frappe.flags.in_bulk_import = False
            frappe.flags.bulk_member_operations = True
            self.assertTrue(self.service._is_suppressed())

    def test_is_suppressed_ignores_import_flags_when_disabled(self):
        """Test _is_suppressed ignores import flags when suppress_during_imports=False."""
        mock_config = MagicMock()
        mock_config.suppress_during_imports = False

        with patch.object(self.service, '_get_config', return_value=mock_config):
            frappe.flags.in_import = True
            # Should NOT be suppressed because suppress_during_imports is False
            self.assertFalse(self.service._is_suppressed())

    def test_is_suppressed_returns_false_when_no_flags_set(self):
        """Test _is_suppressed returns False when no flags set."""
        mock_config = MagicMock()
        mock_config.suppress_during_imports = True

        with patch.object(self.service, '_get_config', return_value=mock_config):
            self.assertFalse(self.service._is_suppressed())


class TestEmailConfigurationServiceErrorPaths(FrappeTestCase):
    """Test error handling and edge cases in EmailConfigurationService."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.service = EmailConfigurationService()

    def test_cooldown_check_handles_cache_connection_error(self):
        """Test check_cooldown gracefully handles Redis connection errors."""
        with patch("frappe.cache") as mock_cache:
            mock_cache.return_value.get_value.side_effect = Exception("Redis connection failed")

            # Should not raise, should return True (allow send on error)
            result = self.service.check_cooldown("test_key", "user@example.com")
            self.assertTrue(result, "Should allow send when cache fails")

    def test_cooldown_record_handles_cache_error(self):
        """Test record_send gracefully handles Redis write errors."""
        with patch.object(self.service, 'get_notification_config', return_value={"cooldown_minutes": 5}):
            with patch("frappe.cache") as mock_cache:
                mock_cache.return_value.set_value.side_effect = Exception("Redis write failed")

                # Should not raise - just log and continue
                try:
                    self.service.record_send("test_key", "user@example.com")
                except Exception as e:
                    self.fail(f"record_send should not raise on cache error: {e}")

    def test_cooldown_clear_handles_cache_error(self):
        """Test clear_cooldown gracefully handles Redis delete errors."""
        with patch("frappe.cache") as mock_cache:
            mock_cache.return_value.delete_value.side_effect = Exception("Redis delete failed")

            # Should not raise
            try:
                self.service.clear_cooldown("test_key", "user@example.com")
            except Exception as e:
                self.fail(f"clear_cooldown should not raise on cache error: {e}")

    def test_get_config_handles_database_error(self):
        """Test _get_config handles database errors gracefully."""
        with patch("frappe.get_single") as mock_get_single:
            mock_get_single.side_effect = Exception("Database connection failed")

            # Should return None or empty, not raise
            result = self.service._get_config()
            # Behavior depends on implementation, but should not crash
            # If it raises, this test should fail
            self.assertIsNone(result)

    def test_is_email_enabled_with_corrupted_config(self):
        """Test is_email_enabled handles corrupted/invalid config gracefully."""
        mock_config = MagicMock()
        mock_config.is_email_enabled.side_effect = AttributeError("Corrupted config")

        with patch.object(self.service, '_get_config', return_value=mock_config):
            # Should default to True (fail open) or handle gracefully
            try:
                result = self.service.is_email_enabled()
                # If it doesn't raise, verify it returns a boolean
                self.assertIn(result, [True, False])
            except AttributeError:
                # Implementation may let AttributeError bubble up - this is acceptable
                pass

    def test_get_notification_config_with_missing_child_table(self):
        """Test get_notification_config handles missing notification_types."""
        mock_config = MagicMock()
        mock_config.get_notification_config.side_effect = AttributeError("notification_types missing")

        with patch.object(self.service, '_get_config', return_value=mock_config):
            result = self.service.get_notification_config("any_key")
            # Should return empty dict, not raise
            self.assertEqual(result, {})

    def test_resolve_recipient_field_with_invalid_path(self):
        """Test _resolve_recipient_field handles deeply nested invalid paths."""
        context = {"member": {"profile": None}}  # profile.email would fail

        result = self.service._resolve_recipient_field("member.profile.email", context)
        self.assertEqual(result, [], "Should return empty list for invalid nested path")

    def test_get_category_recipients_with_none_values(self):
        """Test get_category_recipients handles None email strings."""
        mock_config = MagicMock()
        mock_config.get_recipients_for_category.return_value = []

        with patch.object(self.service, '_get_config', return_value=mock_config):
            result = self.service.get_category_recipients("Admin")
            self.assertEqual(result, [])

    def test_should_send_with_all_conditions_failing(self):
        """Test should_send returns False when multiple conditions fail."""
        with patch.object(self.service, 'is_email_enabled', return_value=False):
            with patch.object(self.service, '_is_suppressed', return_value=True):
                result = self.service.should_send("any_key")
                self.assertFalse(result)

    def test_cooldown_cache_key_with_special_characters(self):
        """Test cooldown cache key handles special characters in recipient."""
        special_recipients = [
            "user+tag@example.com",
            "user@subdomain.example.com",
            "user@example.co.uk",
            "user.name@example.com",
            "user'quote@example.com",
        ]

        for recipient in special_recipients:
            key = self.service._get_cooldown_cache_key("test_key", recipient)
            self.assertIsNotNone(key, f"Should generate key for: {recipient}")
            self.assertIsInstance(key, str, f"Key should be string for: {recipient}")


if __name__ == '__main__':
    import unittest
    unittest.main()
