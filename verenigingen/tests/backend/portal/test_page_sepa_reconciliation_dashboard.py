"""
Tests for the /sepa_reconciliation_dashboard page controller
(verenigingen.templates.pages.sepa_reconciliation_dashboard).

Requires login and "Bank Transaction" read permission. Also exposes
has_website_permission gating the route to banking/accounting roles.
"""

import frappe

from verenigingen.templates.pages import sepa_reconciliation_dashboard as page
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.constants import Roles


class TestPageSepaReconciliationDashboard(EnhancedTestCase):
    """Exercise the SEPA reconciliation dashboard page controller."""

    def test_get_context_for_accounts_manager(self):
        """A user with banking read permission gets a populated context."""
        # System Manager has Bank Transaction read in standard installs and is a
        # banking role per has_website_permission; use it as the privileged actor.
        with self.as_role(Roles.SYSTEM_MANAGER):
            context = frappe._dict()
            result = page.get_context(context)

        self.assertIs(result, context)
        self.assertEqual(context.no_cache, 1)
        self.assertEqual(context.title, "SEPA Reconciliation Dashboard")
        self.assertFalse(context.show_sidebar)

    def test_get_context_denies_user_without_bank_permission(self):
        """A plain member without Bank Transaction read is rejected."""
        with self.as_role("Verenigingen Member"):
            if frappe.has_permission("Bank Transaction", "read"):
                self.skipTest("Member unexpectedly has Bank Transaction read on this site")
            with self.assertRaises(frappe.PermissionError):
                page.get_context(frappe._dict())

    def test_has_website_permission_guest_denied(self):
        self.assertFalse(page.has_website_permission(None, "read", "Guest"))

    def test_has_website_permission_banking_role_allowed(self):
        """A System Manager (listed banking role) passes website permission."""
        user = self.create_test_user(
            f"sepa.recon.{frappe.generate_hash(length=6)}@test.invalid",
            roles=[Roles.SYSTEM_MANAGER],
        )
        self.assertTrue(page.has_website_permission(None, "read", user.name))

    def test_has_website_permission_plain_user_denied(self):
        user = self.create_test_user(
            f"sepa.recon.plain.{frappe.generate_hash(length=6)}@test.invalid",
            roles=["Verenigingen Member"],
        )
        self.assertFalse(page.has_website_permission(None, "read", user.name))
