# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt

"""
Integration tests for the payment plans page controller
(``verenigingen/templates/pages/payment_plans.py``).

The page is members-only: it redirects guests to /login, blocks logged-in
users with no Member record, and otherwise surfaces the member's active dues
schedules. All members/users/dues schedules are real ORM records; the member
is resolved from frappe.session.user via the production lookup utility.
"""

import frappe

from verenigingen.templates.pages import payment_plans
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPagePaymentPlans(EnhancedTestCase):
    def setUp(self):
        self._original_user = frappe.session.user
        super().setUp()

    def tearDown(self):
        frappe.set_user(self._original_user)
        super().tearDown()

    def _member_with_user(self, email):
        member = self.create_test_member(
            first_name="Plans", last_name="Member", email=email, birth_date="1990-01-01"
        )
        self.create_test_user(email, roles=["Verenigingen Member"])
        frappe.db.set_value("Member", member.name, "user", email)
        member.reload()
        return member

    def test_guest_is_redirected_to_login(self):
        """A guest visitor triggers the login Redirect."""
        frappe.set_user("Guest")
        context = frappe._dict()
        with self.assertRaises(frappe.Redirect):
            payment_plans.get_context(context)
        # The controller stores the login target on flags before raising.
        self.assertEqual(frappe.local.flags.redirect_location, "/login")

    def test_logged_in_without_member_record_shows_no_member(self):
        """A logged-in user with no Member record gets the no_member message."""
        email = f"plans.nomember.{frappe.generate_hash(length=8)}@example.com"
        self.create_test_user(email, roles=["Verenigingen Member"])
        with self.as_user(email):
            context = frappe._dict()
            payment_plans.get_context(context)
        self.assertTrue(context.get("no_member"))
        self.assertIsNotNone(context.get("message"))

    def test_member_without_schedules(self):
        """A member with no active dues schedules has has_dues_schedules False."""
        email = f"plans.member.{frappe.generate_hash(length=8)}@example.com"
        member = self._member_with_user(email)
        with self.as_user(email):
            context = frappe._dict()
            payment_plans.get_context(context)
        self.assertEqual(context.member, member.name)
        self.assertEqual(context.member_name, member.full_name)
        self.assertFalse(context.has_dues_schedules)
        self.assertEqual(context.dues_schedules, [])

    def test_member_with_active_schedule_listed(self):
        """A member with an active membership (-> active dues schedule) lists it.

        Creating a real Membership auto-creates the Active Membership Dues
        Schedule via the production after_insert hook; the page must surface it.
        """
        email = f"plans.sched.{frappe.generate_hash(length=8)}@example.com"
        member = self._member_with_user(email)
        self.create_test_membership(member_name=member.name)

        active = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member.name, "status": "Active"},
            pluck="name",
        )
        self.assertTrue(active, "expected the membership to auto-create an active schedule")
        for s in active:
            self.track_doc("Membership Dues Schedule", s)

        with self.as_user(email):
            context = frappe._dict()
            payment_plans.get_context(context)
        self.assertTrue(context.has_dues_schedules)
        listed = {s["name"] for s in context.dues_schedules}
        self.assertTrue(listed.intersection(set(active)))
