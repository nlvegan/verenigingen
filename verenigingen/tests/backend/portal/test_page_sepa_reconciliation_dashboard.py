"""
Tests for the /sepa_reconciliation_dashboard page controller
(verenigingen.templates.pages.sepa_reconciliation_dashboard).

Requires login and "Bank Transaction" read permission; get_context is the
only access gate (Frappe does not dispatch has_website_permission for
template pages).
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
        # banking role per get_context's permission check; use it as the privileged actor.
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
