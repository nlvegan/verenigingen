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

    def setUp(self):
        """Capture ambient Single/flag state this test depends on.

        Order-dependence guard: these tests read the *current* value of the
        Verenigingen Settings Single (send_chapter_assignment_notifications) as
        their baseline and assert it is unchanged after suppression. They also
        assert the suppression flags start cleared. A co-located test that
        mutated the Single or left a suppress_* flag set would otherwise bleed
        into this test's baseline. Snapshot here, restore in tearDown so the
        test neither inherits nor leaks ambient state.
        """
        super().setUp()
        self._original_chapter_setting = frappe.db.get_single_value(
            "Verenigingen Settings", "send_chapter_assignment_notifications"
        )
        self._original_flags = {
            "suppress_notifications": getattr(frappe.flags, "suppress_notifications", False),
            "suppress_chapter_notifications": getattr(
                frappe.flags, "suppress_chapter_notifications", False
            ),
        }
        # Clear suppression flags so each test starts from a known-inactive state
        # regardless of what a neighbouring test left behind.
        frappe.flags.suppress_notifications = False
        frappe.flags.suppress_chapter_notifications = False

    def tearDown(self):
        """Restore Single value and flags so neighbours see the original state."""
        try:
            # Restore the Single field to its captured value (in DB), in case any
            # test body (e.g. test_settings_save_blocked) managed to persist it.
            current = frappe.db.get_single_value(
                "Verenigingen Settings", "send_chapter_assignment_notifications"
            )
            if current != self._original_chapter_setting:
                frappe.db.set_single_value(
                    "Verenigingen Settings",
                    "send_chapter_assignment_notifications",
                    self._original_chapter_setting,
                )
            # Restore flags
            for flag_name, original_value in self._original_flags.items():
                setattr(frappe.flags, flag_name, original_value)
        finally:
            super().tearDown()

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
        """Suppression context activates the flag and leaves the setting unchanged.

        Note: frappe.get_single() returns a FRESH document each call — it does NOT
        return the same object the context manager mutates in memory — so the CM's
        in-memory `send_chapter_assignment_notifications = 0` is not observable from
        here (and a previous assertion on it only passed when the persisted value
        happened to be 0). The observable, meaningful contract is the suppression
        FLAG (which EmailConfigurationService._is_suppressed checks) plus the
        persisted setting being unchanged once the context exits.
        """
        settings = frappe.get_single("Verenigingen Settings")
        settings.reload()
        baseline = settings.send_chapter_assignment_notifications

        with suppress_chapter_notifications():
            self.assertTrue(frappe.flags.suppress_chapter_notifications)

        self.assertFalse(getattr(frappe.flags, "suppress_chapter_notifications", False))
        settings.reload()
        self.assertEqual(settings.send_chapter_assignment_notifications, baseline)

    def test_settings_save_blocked(self):
        """A save during the suppression context must not corrupt the persisted setting.

        See test_settings_restoration: get_single() does not return the context
        manager's object, so we assert on the persisted value (unchanged) and the
        suppression flag rather than the unobservable in-memory value.
        """
        settings = frappe.get_single("Verenigingen Settings")
        settings.reload()
        baseline = settings.send_chapter_assignment_notifications

        with suppress_chapter_notifications():
            self.assertTrue(frappe.flags.suppress_chapter_notifications)

            # Try to save - should be blocked by ignore_save flag
            try:
                settings.save()
            except Exception:
                # If save raises exception due to ignore_save, that's acceptable
                pass

        # Reload and verify the persisted value was preserved (save did not corrupt it)
        settings.reload()
        self.assertEqual(settings.send_chapter_assignment_notifications, baseline)

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
