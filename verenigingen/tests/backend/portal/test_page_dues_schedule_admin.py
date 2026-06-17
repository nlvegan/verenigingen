"""
Tests for the /dues_schedule_admin page controller
(verenigingen.templates.pages.dues_schedule_admin).

Requires "Membership Dues Schedule" create permission. Surfaces a preview of
members missing dues schedules plus aggregate statistics, and exposes a
high-security trigger_auto_creation endpoint.
"""

import frappe

from verenigingen.templates.pages import dues_schedule_admin as page
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.constants import Roles


class TestPageDuesScheduleAdmin(EnhancedTestCase):
    """Exercise the dues schedule admin page controller."""

    def test_get_context_for_privileged_user(self):
        """A user with create permission gets preview + stats."""
        with self.as_admin_role():
            if not frappe.has_permission("Membership Dues Schedule", "create"):
                self.skipTest("Admin role lacks Membership Dues Schedule create on this site")
            context = frappe._dict()
            result = page.get_context(context)

        self.assertIs(result, context)
        self.assertEqual(context.no_cache, 1)
        self.assertFalse(context.show_sidebar)
        self.assertEqual(context.title, "Dues Schedule Administration")
        # preview_members is a list (possibly empty) of members missing schedules.
        self.assertIsInstance(context.preview_members, list)
        # stats carries the documented keys produced by get_dues_schedule_stats.
        self.assertIn("total_active_members", context.stats)
        self.assertIn("members_without_schedules", context.stats)
        self.assertIn("total_schedules", context.stats)

    def test_get_context_denies_member(self):
        """A plain member without create permission is rejected."""
        with self.as_role("Verenigingen Member"):
            if frappe.has_permission("Membership Dues Schedule", "create"):
                self.skipTest("Member unexpectedly has create permission on this site")
            with self.assertRaises(frappe.PermissionError):
                page.get_context(frappe._dict())

    def test_get_dues_schedule_stats_shape_and_consistency(self):
        """get_dues_schedule_stats returns integer counts that are internally consistent."""
        stats = page.get_dues_schedule_stats()
        for key in (
            "total_active_members",
            "members_with_schedules",
            "members_without_schedules",
            "total_schedules",
            "active_schedules",
            "schedule_templates",
        ):
            self.assertIn(key, stats)
            self.assertIsInstance(stats[key], int)
            self.assertGreaterEqual(stats[key], 0)

        # Active + template schedules cannot exceed the total number of schedules.
        self.assertLessEqual(stats["active_schedules"], stats["total_schedules"])
        self.assertLessEqual(stats["schedule_templates"], stats["total_schedules"])
