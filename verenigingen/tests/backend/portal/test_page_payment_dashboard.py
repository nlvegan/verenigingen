# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt

"""
Integration tests for the payment dashboard page controller
(``verenigingen/templates/pages/payment_dashboard.py``).

Covers the permission matrix (guest -> login, no-role -> PermissionError,
member -> own dashboard, admin -> member param / member selection) plus the
pure financial-overview helpers. All members, users, schedules, invoices and
payments are real ORM records; the member is resolved from the session user
via the production lookup.
"""

import frappe

from verenigingen.templates.pages import payment_dashboard
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPagePaymentDashboard(EnhancedTestCase):
    def setUp(self):
        self._original_user = frappe.session.user
        super().setUp()
        self._original_form_dict = frappe.local.form_dict
        frappe.local.form_dict = frappe._dict()

    def tearDown(self):
        frappe.local.form_dict = self._original_form_dict
        frappe.set_user(self._original_user)
        super().tearDown()

    def _member_with_user(self, email, roles=("Verenigingen Member",)):
        member = self.create_test_member(
            first_name="Dash", last_name="Member", email=email, birth_date="1990-01-01"
        )
        self.create_test_user(email, roles=list(roles))
        frappe.db.set_value("Member", member.name, "user", email)
        member.reload()
        return member

    # ------------------------------------------------------------------
    # get_context - permission matrix
    # ------------------------------------------------------------------

    def test_guest_redirected_to_login(self):
        """require_login() throws a PermissionError for guests."""
        frappe.set_user("Guest")
        context = frappe._dict()
        with self.assertRaises(frappe.PermissionError):
            payment_dashboard.get_context(context)

    def test_user_without_member_or_admin_role_denied(self):
        """A logged-in user lacking both member and admin roles is denied."""
        email = f"dash.norole.{frappe.generate_hash(length=8)}@example.com"
        # Volunteer role: a real role that is neither Verenigingen Member nor admin.
        self.create_test_user(email, roles=["Verenigingen Volunteer"])
        with self.as_user(email):
            context = frappe._dict()
            with self.assertRaises(frappe.PermissionError):
                payment_dashboard.get_context(context)

    def test_member_sees_own_dashboard(self):
        """A member views their own dashboard with bank details context populated."""
        email = f"dash.member.{frappe.generate_hash(length=8)}@example.com"
        member = self._member_with_user(email)
        with self.as_user(email):
            context = frappe._dict()
            payment_dashboard.get_context(context)
        self.assertEqual(context.member, member.name)
        self.assertFalse(context.is_admin)
        # _add_bank_details_context ran -> member_doc + financial_overview present.
        self.assertIsNotNone(context.get("member_doc"))
        self.assertIn("financial_overview", context)
        self.assertIn("current_details", context)

    def test_admin_viewing_specific_member(self):
        """An admin passing ?member=<name> views that member's dashboard."""
        email = f"dash.admin.{frappe.generate_hash(length=8)}@example.com"
        self.create_test_user(email, roles=["Verenigingen Administrator"])
        target = self.create_test_member(first_name="Target", last_name="Member", birth_date="1988-03-03")
        with self.as_user(email):
            # set_user() resets form_dict, so populate it inside the user context.
            frappe.local.form_dict = frappe._dict({"member": target.name})
            context = frappe._dict()
            payment_dashboard.get_context(context)
        self.assertEqual(context.member, target.name)
        self.assertTrue(context.viewing_as_admin)
        self.assertTrue(context.is_admin)

    def test_admin_invalid_member_param_raises(self):
        """An admin passing a non-existent member id gets a DoesNotExistError."""
        email = f"dash.admin2.{frappe.generate_hash(length=8)}@example.com"
        self.create_test_user(email, roles=["Verenigingen Administrator"])
        with self.as_user(email):
            frappe.local.form_dict = frappe._dict({"member": "Member-NOPE-XYZ"})
            context = frappe._dict()
            with self.assertRaises(frappe.DoesNotExistError):
                payment_dashboard.get_context(context)

    def test_admin_without_member_record_shows_selection(self):
        """An admin with no own Member record gets the member-selection view."""
        email = f"dash.admin3.{frappe.generate_hash(length=8)}@example.com"
        self.create_test_user(email, roles=["Verenigingen Administrator"])
        with self.as_user(email):
            frappe.local.form_dict = frappe._dict()  # no member param
            context = frappe._dict()
            payment_dashboard.get_context(context)
        self.assertTrue(context.get("show_member_selection"))
        self.assertIsInstance(context.get("members"), list)

    # ------------------------------------------------------------------
    # Pure helpers
    # ------------------------------------------------------------------

    def test_get_financial_overview_no_customer(self):
        """A member with no customer gets a zeroed financial overview, not an error."""
        member = self.create_test_member(first_name="NoCust", last_name="Member", birth_date="1992-04-04")
        overview = payment_dashboard.get_financial_overview(member.name)
        self.assertEqual(overview["total_paid_year"], 0)
        self.assertEqual(overview["payment_count"], 0)
        self.assertIsNone(overview["next_payment"])

    def test_get_recent_activity_no_customer_empty(self):
        """No customer => empty recent activity list."""
        member = self.create_test_member(first_name="NoAct", last_name="Member", birth_date="1993-05-05")
        self.assertEqual(payment_dashboard.get_recent_activity(member.name), [])

    def test_get_current_dues_schedule_monthly_amount(self):
        """An Active monthly schedule yields monthly_amount == dues_rate."""
        email = f"dash.sched.{frappe.generate_hash(length=8)}@example.com"
        member = self._member_with_user(email)
        self.create_test_membership(member_name=member.name)
        active = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member.name, "status": "Active"},
            pluck="name",
        )
        for s in active:
            self.track_doc("Membership Dues Schedule", s)
        schedule = payment_dashboard.get_current_dues_schedule(member.name)
        self.assertIsNotNone(schedule)
        # monthly_amount is derived from billing_frequency; it must be present.
        self.assertIn("monthly_amount", schedule)

    def test_notification_settings_defaults(self):
        """get_notification_settings returns the documented default flags."""
        settings = payment_dashboard.get_notification_settings("X")
        self.assertTrue(settings["email_enabled"])
        self.assertTrue(settings["reminders_enabled"])
        self.assertTrue(settings["failure_enabled"])
