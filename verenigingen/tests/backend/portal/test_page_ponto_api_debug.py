"""
Tests for the /ponto_api_debug page controller
(verenigingen.templates.pages.ponto_api_debug).

This is a role-gated admin debug page for the Ponto (Ibanity) payment
integration. Access is restricted via has_ponto_debug_access. The CRUD-style
helpers operate on real "Ponto Payment Link" documents; only the external
Ponto/Ibanity HTTP boundary (test_connection / test_mtls_connection /
refresh_status) hits the network, so those are not driven against a live API
here — CI has no Ponto credentials.
"""

import frappe

from verenigingen.templates.pages import ponto_api_debug as page
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.constants import Roles


class TestPagePontoApiDebug(EnhancedTestCase):
    """Exercise the Ponto API debug page controller."""

    def _make_payment_link(self, **overrides):
        """Create a real Ponto Payment Link in Draft via the controller endpoint.

        Uses the page's own create_payment_link as a privileged user so we
        exercise real document creation (not a fixture short-circuit).
        """
        with self.as_admin_role():
            result = page.create_payment_link(
                amount=overrides.get("amount", 25.0),
                description=overrides.get("description", "Test dues link"),
                payment_type=overrides.get("payment_type", "One-Time"),
                creditor_name=overrides.get("creditor_name", "Test Org BV"),
                creditor_iban=overrides.get("creditor_iban", "NL02ABNA0123456789"),
            )
        self.assertTrue(result.get("success"), result)
        self.track_doc("Ponto Payment Link", result["name"])
        return result

    # ------------------------------------------------------------------
    # Access control
    # ------------------------------------------------------------------
    def test_has_ponto_debug_access_for_admin(self):
        with self.as_admin_role():
            self.assertTrue(page.has_ponto_debug_access())

    def test_has_ponto_debug_access_denied_for_member(self):
        with self.as_role("Verenigingen Member"):
            self.assertFalse(page.has_ponto_debug_access())

    def test_get_context_denies_non_privileged(self):
        with self.as_role("Verenigingen Member"):
            with self.assertRaises(frappe.PermissionError):
                page.get_context(frappe._dict())

    def test_get_context_for_admin(self):
        """A privileged user gets the title, csrf token, and reference lists."""
        with self.as_admin_role():
            context = frappe._dict()
            result = page.get_context(context)

        self.assertIs(result, context)
        self.assertEqual(context.no_cache, 1)
        self.assertEqual(context.title, "Ponto API Debug")
        self.assertTrue(context.csrf_token)
        # ponto_configured is a bool; recent_payment_links is always a list.
        self.assertIn(context.ponto_configured, (True, False))
        self.assertIsInstance(context.recent_payment_links, list)
        # A description template default is always provided.
        self.assertTrue(context.description_template)

    # ------------------------------------------------------------------
    # create_payment_link
    # ------------------------------------------------------------------
    def test_create_payment_link_success(self):
        result = self._make_payment_link(amount=42.5, description="Annual dues")
        self.assertEqual(result["amount"], 42.5)
        self.assertEqual(result["description"], "Annual dues")
        self.assertEqual(result["payment_type"], "One-Time")
        # New link starts in Draft.
        self.assertEqual(result["status"], "Draft")
        self.assertTrue(frappe.db.exists("Ponto Payment Link", result["name"]))

    def test_create_payment_link_rejects_invalid_amount(self):
        """A non-numeric amount yields a structured error, not an exception."""
        with self.as_admin_role():
            result = page.create_payment_link(
                amount="not-a-number",
                description="Bad amount",
                creditor_name="Test Org BV",
                creditor_iban="NL02ABNA0123456789",
            )
        self.assertFalse(result["success"])
        self.assertIn("Invalid amount", result["error"])

    def test_create_payment_link_rejects_non_positive_amount(self):
        with self.as_admin_role():
            result = page.create_payment_link(
                amount=0,
                description="Zero amount",
                creditor_name="Test Org BV",
                creditor_iban="NL02ABNA0123456789",
            )
        self.assertFalse(result["success"])
        self.assertIn("greater than zero", result["error"])

    def test_create_payment_link_denied_for_member(self):
        """A non-privileged user is denied by the @standard_api security gate.

        The decorator enforces the FINANCIAL operation level BEFORE the function
        body runs and raises a (Verenigingen) PermissionError, which subclasses
        frappe.PermissionError.
        """
        with self.as_role("Verenigingen Member"):
            with self.assertRaises(frappe.PermissionError):
                page.create_payment_link(
                    amount=10,
                    description="x",
                    creditor_name="Test Org BV",
                    creditor_iban="NL02ABNA0123456789",
                )

    # ------------------------------------------------------------------
    # list / details
    # ------------------------------------------------------------------
    def test_list_payment_links_includes_created(self):
        created = self._make_payment_link(description="Listable link")
        with self.as_admin_role():
            result = page.list_payment_links(limit=50)
        self.assertTrue(result["success"])
        names = {link["name"] for link in result["links"]}
        self.assertIn(created["name"], names)

    def test_list_payment_links_status_filter(self):
        created = self._make_payment_link(description="Draft filter link")
        with self.as_admin_role():
            result = page.list_payment_links(limit=50, status_filter="Draft")
        self.assertTrue(result["success"])
        self.assertIn(created["name"], {link["name"] for link in result["links"]})
        # Every returned link must satisfy the filter.
        for link in result["links"]:
            self.assertEqual(link["status"], "Draft")

    def test_list_payment_links_denied_for_member(self):
        with self.as_role("Verenigingen Member"):
            with self.assertRaises(frappe.PermissionError):
                page.list_payment_links()

    def test_get_payment_link_details_success(self):
        created = self._make_payment_link(amount=12.0, description="Detail link")
        with self.as_admin_role():
            result = page.get_payment_link_details(created["name"])
        self.assertTrue(result["success"])
        self.assertEqual(result["name"], created["name"])
        self.assertEqual(result["amount"], 12.0)
        self.assertEqual(result["currency"], "EUR")
        self.assertEqual(result["docstatus"], 0)

    def test_get_payment_link_details_denied_for_member(self):
        created = self._make_payment_link(description="Protected detail link")
        with self.as_role("Verenigingen Member"):
            with self.assertRaises(frappe.PermissionError):
                page.get_payment_link_details(created["name"])

    def test_submit_payment_link_denied_for_member(self):
        created = self._make_payment_link(description="Submit-protected link")
        with self.as_role("Verenigingen Member"):
            with self.assertRaises(frappe.PermissionError):
                page.submit_payment_link(created["name"])
