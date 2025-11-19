"""
Tests for bulk operation notification suppression context managers.

Verifies that:
1. Flags are properly restored after context exits
2. Settings are properly restored after context exits
3. Cleanup happens even when exceptions occur
4. Settings cannot be accidentally persisted during context
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.utils.notification_suppression import (
    is_bulk_operation_active,
    suppress_all_notifications,
    suppress_chapter_notifications,
)


class TestNotificationSuppression(FrappeTestCase):
    """Test bulk operation notification suppression context managers."""

    def test_basic_chapter_suppression(self):
        """Test basic chapter notification suppression."""
        # Ensure clean initial state
        self.assertFalse(is_bulk_operation_active())

        with suppress_chapter_notifications():
            # Should be active within context
            self.assertTrue(is_bulk_operation_active())
            self.assertTrue(frappe.flags.suppress_chapter_notifications)

        # Should be restored after context
        self.assertFalse(is_bulk_operation_active())
        self.assertFalse(getattr(frappe.flags, "suppress_chapter_notifications", False))

    def test_exception_cleanup(self):
        """Test cleanup happens even with exceptions."""
        try:
            with suppress_chapter_notifications():
                self.assertTrue(frappe.flags.suppress_chapter_notifications)
                raise ValueError("Test exception")
        except ValueError:
            pass

        # Flag should be restored despite exception
        self.assertFalse(getattr(frappe.flags, "suppress_chapter_notifications", False))
        self.assertFalse(is_bulk_operation_active())

    def test_settings_restoration(self):
        """Test settings are properly restored after context."""
        settings = frappe.get_single("Verenigingen Settings")
        original_value = settings.send_chapter_assignment_notifications

        with suppress_chapter_notifications():
            # Verify in-memory change
            self.assertEqual(settings.send_chapter_assignment_notifications, 0)

        # Reload and verify restoration
        settings.reload()
        self.assertEqual(settings.send_chapter_assignment_notifications, original_value)

    def test_settings_save_blocked(self):
        """Test that settings cannot be accidentally saved during context."""
        settings = frappe.get_single("Verenigingen Settings")
        original_value = settings.send_chapter_assignment_notifications

        with suppress_chapter_notifications():
            # Settings have been modified in memory
            self.assertEqual(settings.send_chapter_assignment_notifications, 0)

            # Try to save - should be blocked by ignore_save flag
            try:
                settings.save()
            except Exception:
                # If save raises exception due to ignore_save, that's acceptable
                pass

        # Reload and verify original value was preserved (save was blocked)
        settings.reload()
        self.assertEqual(settings.send_chapter_assignment_notifications, original_value)

    def test_all_notifications_suppression(self):
        """Test aggressive all-notifications suppression."""
        self.assertFalse(is_bulk_operation_active())

        with suppress_all_notifications():
            # Both flags should be active
            self.assertTrue(frappe.flags.suppress_notifications)
            self.assertTrue(frappe.flags.suppress_chapter_notifications)
            self.assertTrue(is_bulk_operation_active())

        # All flags should be restored
        self.assertFalse(getattr(frappe.flags, "suppress_notifications", False))
        self.assertFalse(getattr(frappe.flags, "suppress_chapter_notifications", False))
        self.assertFalse(is_bulk_operation_active())

    def test_is_bulk_operation_active_helper(self):
        """Test bulk operation detection helper."""
        # Initially inactive
        self.assertFalse(is_bulk_operation_active())

        # Active with chapter suppression
        with suppress_chapter_notifications():
            self.assertTrue(is_bulk_operation_active())

        # Active with all notifications suppression
        with suppress_all_notifications():
            self.assertTrue(is_bulk_operation_active())

        # Inactive after exit
        self.assertFalse(is_bulk_operation_active())
