"""
Tests for the /brand_management page controller
(verenigingen.templates.pages.brand_management).

This is an admin-only page (Roles.ADMIN_PAIR = System Manager / Verenigingen
Administrator) that surfaces the active Brand Settings and the Owl Theme
integration status. It also exposes has_website_permission for route gating.
"""

import frappe

from verenigingen.templates.pages import brand_management
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.constants import Roles


class TestPageBrandManagement(EnhancedTestCase):
    """Exercise the brand_management page controller's real behavior."""

    def test_get_context_for_admin_user(self):
        """An admin-role user gets the active settings and owl theme status."""
        with self.as_admin_role():
            context = frappe._dict()
            result = brand_management.get_context(context)

        self.assertIs(result, context)
        self.assertEqual(context.no_cache, 1)
        self.assertEqual(context.title, "Brand Management")
        # active_settings comes from get_active_brand_settings(); it must be present
        # (the Brand Settings Single always resolves to a dict-like object).
        self.assertIsNotNone(context.active_settings)
        # owl_theme_status is computed by check_owl_theme_integration().
        self.assertIsNotNone(context.owl_theme_status)

    def test_get_context_denies_non_admin(self):
        """A non-admin logged-in user is rejected with PermissionError."""
        with self.as_role("Verenigingen Member"):
            with self.assertRaises(frappe.PermissionError):
                brand_management.get_context(frappe._dict())

    def test_has_website_permission_guest_denied(self):
        """Guests cannot access the page."""
        self.assertFalse(brand_management.has_website_permission(None, "read", "Guest"))

    def test_has_website_permission_admin_allowed(self):
        """A user holding an ADMIN_PAIR role passes the website permission check."""
        user = self.create_test_user(
            f"brandmgmt.admin.{frappe.generate_hash(length=6)}@test.invalid",
            roles=[Roles.VERENIGINGEN_ADMIN],
        )
        self.assertTrue(brand_management.has_website_permission(None, "read", user.name))

    def test_has_website_permission_plain_user_denied(self):
        """A logged-in user without an admin role is denied."""
        user = self.create_test_user(
            f"brandmgmt.plain.{frappe.generate_hash(length=6)}@test.invalid",
            roles=["Verenigingen Member"],
        )
        self.assertFalse(brand_management.has_website_permission(None, "read", user.name))
