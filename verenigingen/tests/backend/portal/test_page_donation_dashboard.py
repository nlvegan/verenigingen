"""
Tests for the donation dashboard page controller
(verenigingen.templates.pages.donation_dashboard).

get_context enforces read permission on Donation + Periodic Donation Agreement,
short-circuits when ANBI functionality is disabled, and otherwise delegates to
DonationDashboardService for the dashboard payload (catching/logging service
errors into context.error).
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPageDonationDashboard(EnhancedTestCase):
    """Real-data tests for the donation dashboard context handler."""

    def setUp(self):
        super().setUp()
        self._anbi_original = frappe.db.get_single_value("Verenigingen Settings", "enable_anbi_functionality")

    def tearDown(self):
        frappe.db.set_value(
            "Verenigingen Settings",
            "Verenigingen Settings",
            "enable_anbi_functionality",
            self._anbi_original,
        )
        super().tearDown()

    def _set_anbi(self, enabled):
        frappe.db.set_value(
            "Verenigingen Settings",
            "Verenigingen Settings",
            "enable_anbi_functionality",
            1 if enabled else 0,
        )

    def test_permission_denied_for_plain_member(self):
        """A plain member without Donation read permission is rejected."""
        from verenigingen.templates.pages.donation_dashboard import get_context

        member = self.create_test_member(
            first_name="Dash",
            last_name="NoPerm",
            email=f"dash-noperm-{frappe.generate_hash()[:8]}@example.com",
            birth_date="1990-01-01",
        )
        email = member.email
        if not frappe.db.exists("User", email):
            user = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": "Dash",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            )
            user.insert()

        with self.as_user(email):
            with self.assertRaises(frappe.PermissionError):
                get_context(frappe._dict())

    def test_anbi_disabled_short_circuits(self):
        """With ANBI off, the page reports anbi_disabled and skips the service."""
        from verenigingen.templates.pages.donation_dashboard import get_context

        self._set_anbi(False)
        admin = self.ensure_test_admin_user()

        with self.as_user(admin.email):
            ctx = frappe._dict()
            get_context(ctx)

        self.assertTrue(ctx.get("anbi_disabled"))
        # Service data must NOT have been loaded.
        self.assertNotIn("recent_donations", ctx)

    def test_anbi_enabled_loads_dashboard_data(self):
        """With ANBI on and read permission, the service payload is merged in."""
        from verenigingen.templates.pages.donation_dashboard import get_context

        self._set_anbi(True)
        admin = self.ensure_test_admin_user()

        with self.as_user(admin.email):
            ctx = frappe._dict()
            get_context(ctx)

        self.assertEqual(ctx.no_cache, 1)
        self.assertNotIn("anbi_disabled", ctx)
        # Keys produced by DonationDashboardService.get_dashboard_context().
        self.assertIn("anbi_minimum_reportable_amount", ctx)
        self.assertIn("recent_donations", ctx)
        self.assertIn("total_donations_amount", ctx)
        # No error path was hit.
        self.assertNotIn("error", ctx)
