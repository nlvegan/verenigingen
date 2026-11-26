# Copyright (c) 2026, Foppe de Haan and Contributors
# See license.txt

"""
The Verenigingen tile on the desk's Apps screen (``/desk`` with Desktop Settings = Apps).

That screen is built solely from the ``add_to_apps_screen`` hook, surfaced per user as
``frappe.boot.get_app_data()[].on_apps_screen``. Without the hook the app has no tile at all.

Who sees the tile is deliberately narrower than who can open the workspace: the
``Verenigingen Volunteer`` role carries desk access, so every volunteer is a System User, and an
"every desk user" gate (ERPNext's) would put the tile in front of all of them. (A member-only
user is a Website User since #2860 and never reaches the desk at all.) The denied cases below are
therefore real System Users -- a volunteer, and a member who also holds a generic desk role -- so
that gate fails them.
"""

from pathlib import Path

import frappe
from frappe.boot import get_app_data

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

ALLOWED_ROLES = [
    "Verenigingen Administrator",
    "Verenigingen Staff",
    "Verenigingen Treasurer",
    "Verenigingen Financial Manager",
    "Verenigingen Chapter Board Member",
    "Verenigingen National Board Member",
    "Verenigingen Member Manager",
    "Verenigingen Auditor",
]

# role -> the roles the denied user holds. A member-only user is a Website User (#2860), so the
# member case adds "Desk User" to make it a real desk user the tile gate has to refuse.
DENIED_USERS = {
    "Verenigingen Member": ["Verenigingen Member", "Desk User"],
    "Verenigingen Volunteer": ["Verenigingen Volunteer"],
}


def _verenigingen_entry():
    return next(app for app in get_app_data() if app["app_name"] == "verenigingen")


class TestAppsScreenEntry(EnhancedTestCase):
    def _user_with_role(self, role, extra_roles=()):
        # "Verenigingen Member Manager" exists on the production copy but ships with no fixture.
        if not frappe.db.exists("Role", role):
            frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert()
        slug = frappe.scrub(role).replace("_", "-")
        return self.create_test_user(f"apps-screen-{slug}@example.com", roles=[role, *extra_roles])

    def test_administrator_gets_a_tile_that_leads_to_the_workspace(self):
        entry = _verenigingen_entry()

        self.assertTrue(entry["on_apps_screen"])
        self.assertEqual(entry["app_title"], "Verenigingen")
        self.assertEqual(entry["app_route"], "/desk/verenigingen")
        self.assertTrue(frappe.db.exists("Workspace", "Verenigingen"))

    def test_logo_is_a_shipped_asset(self):
        logo = _verenigingen_entry()["app_logo_url"]

        prefix = "/assets/verenigingen/"
        self.assertTrue(logo.startswith(prefix), logo)
        public = Path(frappe.get_app_path("verenigingen", "public"))
        self.assertTrue((public / logo[len(prefix) :]).is_file(), logo)

    def test_staff_board_and_finance_roles_see_the_tile(self):
        for role in ALLOWED_ROLES:
            user = self._user_with_role(role)
            with self.subTest(role=role), self.as_user(user.name):
                self.assertTrue(_verenigingen_entry()["on_apps_screen"])

    def test_members_and_volunteers_do_not_see_the_tile(self):
        for role, roles in DENIED_USERS.items():
            user = self._user_with_role(role, extra_roles=[r for r in roles if r != role])
            with self.subTest(role=role):
                # Control: a desk user, so a "not a Website User" gate would show them the tile.
                self.assertEqual(frappe.db.get_value("User", user.name, "user_type"), "System User")
                with self.as_user(user.name):
                    self.assertFalse(_verenigingen_entry()["on_apps_screen"])

    def test_a_member_only_user_is_a_website_user_and_sees_no_tile(self):
        # #2860: the member role has no desk access, so a member-only account is a Website User.
        user = self._user_with_role("Verenigingen Member")
        self.assertEqual(frappe.db.get_value("User", user.name, "user_type"), "Website User")
        with self.as_user(user.name):
            self.assertFalse(_verenigingen_entry()["on_apps_screen"])
