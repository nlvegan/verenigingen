# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt

"""Real integration tests for verenigingen/utils/portal_customization.py

Covers add_portal_user_roles, which is registered as an update_website_context hook and
therefore runs on EVERY website/portal page render. Its single output is load-bearing:

context["user_roles"] is read directly by templates/includes/web_sidebar.html,
templates/includes/portal_nav.html and templates/pages/chapter_dashboard.html to decide
which navigation entries to show. If this key stops being set, the portal sidebar
silently renders no role-gated links rather than raising.

These tests call the real function against the test DB with no business-logic mocking.
frappe.set_user() exercises the Guest vs authenticated branches; setUp captures the
session user so cleanup can restore it.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.portal_customization import add_portal_user_roles


class TestAddPortalUserRoles(VereningingenTestCase):
    """Behaviour of the update_website_context hook."""

    def setUp(self):
        super().setUp()
        self._original_user = frappe.session.user
        self.addCleanup(frappe.set_user, self._original_user)

    def test_user_roles_exposed_to_templates(self):
        """context['user_roles'] must carry the caller's roles.

        The portal sidebar and nav templates read this key directly; losing it
        silently empties role-gated navigation rather than raising.
        """
        email = "test-portal-roles@example.com"
        self.create_test_user(email, roles=["Verenigingen Member"])
        frappe.set_user(email)
        context = {"path": "member_portal"}

        add_portal_user_roles(context)

        self.assertIn("user_roles", context)
        self.assertIn("Verenigingen Member", context["user_roles"])

    def test_roles_reflect_the_current_user(self):
        """Roles are resolved per user, not cached across sessions."""
        volunteer = "test-portal-volunteer@example.com"
        self.create_test_user(volunteer, roles=["Verenigingen Volunteer"])
        frappe.set_user(volunteer)
        context = {"path": "member_portal"}

        add_portal_user_roles(context)

        self.assertIn("Verenigingen Volunteer", context["user_roles"])
        self.assertNotIn("Verenigingen Member", context["user_roles"])

    def test_guest_does_not_get_user_roles(self):
        """user_roles is only exposed to authenticated users.

        Templates guard with `user_roles or []`, so an unset key degrades to an empty
        navigation rather than an error.
        """
        frappe.set_user("Guest")
        context = {"path": "member_portal"}

        add_portal_user_roles(context)

        self.assertNotIn("user_roles", context)

    def test_returns_the_context(self):
        """update_website_context merges any returned mapping back into the context."""
        frappe.set_user("Guest")
        context = {"path": "member_portal"}

        self.assertIs(add_portal_user_roles(context), context)

    def test_does_not_set_body_class(self):
        """The hook must not emit body classes.

        portal-page / verenigingen-portal / member-portal / volunteer-portal and the
        data_portal_page attribute were removed: no stylesheet in any installed app,
        built asset, or DB-stored theme targets them. The shipped brand CSS
        (sites/<site>/public/css/brand_colors.css) is globally unscoped and is scoped
        instead by the per-template {{ brand_css() }} link.
        """
        email = "test-portal-bodyclass@example.com"
        self.create_test_user(email, roles=["Verenigingen Volunteer"])
        frappe.set_user(email)
        context = {"path": "member_portal"}

        add_portal_user_roles(context)

        self.assertNotIn("body_class", context)
        self.assertNotIn("data_portal_page", context)

    def test_preserves_unrelated_context_keys(self):
        """The hook must not clobber context set by earlier renderers."""
        frappe.set_user("Guest")
        context = {"path": "member_portal", "body_class": "set-by-someone-else"}

        add_portal_user_roles(context)

        self.assertEqual(context["body_class"], "set-by-someone-else")
