# Copyright (c) 2026, Veganisme.org and contributors
# For license information, please see license.txt

"""
Extended tests for MemberRoleService — exercises the real role/module
assignment behaviour that the smoke tests in test_member_service_coverage.py
do not pin:

- add_member_roles_to_user: assigns a role profile via the v16 role_profiles
  child table, clears pre-existing roles, falls back to individual role
  assignment when the requested profile does not exist.
- _assign_individual_member_roles: fallback path adds Verenigingen Member / All.
- set_member_user_modules: blocks every module except the member allow-list.

Runs against real User / Role / Role Profile docs as Administrator.
"""

import frappe

from verenigingen.services.member.account.member_role_service import (
    MemberRoleService,
    get_member_role_service,
)
from verenigingen.tests.utils.base import VereningingenTestCase


class TestMemberRoleServiceExtended(VereningingenTestCase):
    """Cover the role-profile / module assignment branches of MemberRoleService."""

    def setUp(self):
        super().setUp()
        self.service = MemberRoleService()
        self.h = frappe.generate_hash(length=6)

    def _make_user(self, roles=None):
        email = f"mrolesvc.{self.h}.{frappe.generate_hash(length=4)}@test.invalid"
        user = self.create_test_user(email, roles=roles)
        self.track_doc("User", user.name)
        return user

    def _profile_names(self, user_name):
        """Role profile names attached to the user via the v16 child table."""
        return frappe.get_all(
            "User Role Profile",
            filters={"parent": user_name, "parenttype": "User"},
            pluck="role_profile",
        )

    def _require_role_profiles(self):
        """add_member_roles_to_user assigns via the Frappe v16 ``role_profiles`` child
        table (and these tests read the ``User Role Profile`` child doctype). Both are
        absent on older Frappe (e.g. the CI runner), where the production append raises
        ``'NoneType' has no attribute 'options'``. Skip there; these run on the v16
        dev/prod sites. The version-agnostic fallback is covered by
        ``test_assign_individual_roles_directly``."""
        if not frappe.get_meta("User").has_field("role_profiles"):
            self.skipTest("requires Frappe v16 User.role_profiles child table")

    # ============================================================ add_member_roles_to_user

    def test_add_default_profile_assigns_via_child_table(self):
        # No explicit profile -> defaults to "Verenigingen Member" and writes it
        # to the role_profiles child table (the v16 canonical store).
        self._require_role_profiles()
        user = self._make_user()
        with self.assertNoErrorLog():
            result = self.service.add_member_roles_to_user(user.name)
        self.assertEqual(result, user.name)
        self.assertIn("Verenigingen Member", self._profile_names(user.name))

    def test_add_roles_clears_preexisting_roles(self):
        # The method intentionally clears ALL existing roles before applying the
        # member profile (member accounts should hold only member roles).
        self._require_role_profiles()
        user = self._make_user(roles=["System Manager"])
        self.assertIn("System Manager", [r.role for r in user.roles])

        self.service.add_member_roles_to_user(user.name)

        refreshed = frappe.get_doc("User", user.name)
        roles_after = [r.role for r in refreshed.roles]
        self.assertNotIn("System Manager", roles_after)

    def test_add_volunteer_profile_when_specified(self):
        self._require_role_profiles()
        user = self._make_user()
        result = self.service.add_member_roles_to_user(
            user.name, role_profile_name="Verenigingen Volunteer"
        )
        self.assertEqual(result, user.name)
        self.assertIn("Verenigingen Volunteer", self._profile_names(user.name))

    def test_add_nonexistent_profile_falls_back_to_individual_roles(self):
        # When the requested Role Profile does not exist, the method falls back to
        # _assign_individual_member_roles, which adds Verenigingen Member + All
        # directly (no role profile written). Still skipped pre-v16 because the
        # final assertion reads the User Role Profile child doctype.
        self._require_role_profiles()
        user = self._make_user()
        result = self.service.add_member_roles_to_user(
            user.name, role_profile_name="NoSuchProfile-XYZ"
        )
        self.assertEqual(result, user.name)
        refreshed = frappe.get_doc("User", user.name)
        roles_after = [r.role for r in refreshed.roles]
        self.assertIn("Verenigingen Member", roles_after)
        self.assertIn("All", roles_after)
        # No role profile was assigned in the fallback path.
        self.assertNotIn("NoSuchProfile-XYZ", self._profile_names(user.name))

    def test_add_roles_enables_disabled_user(self):
        self._require_role_profiles()
        user = self._make_user()
        frappe.db.set_value("User", user.name, "enabled", 0)
        self.service.add_member_roles_to_user(user.name)
        self.assertEqual(frappe.db.get_value("User", user.name, "enabled"), 1)

    # ============================================================ _assign_individual_member_roles

    def test_assign_individual_roles_directly(self):
        user = self._make_user(roles=["System Manager"])
        result = self.service._assign_individual_member_roles(user.name)
        self.assertEqual(result, user.name)
        refreshed = frappe.get_doc("User", user.name)
        roles_after = [r.role for r in refreshed.roles]
        self.assertIn("Verenigingen Member", roles_after)
        self.assertIn("All", roles_after)
        # Pre-existing System Manager role is cleared.
        self.assertNotIn("System Manager", roles_after)

    # ============================================================ set_member_user_modules

    def test_set_member_user_modules_blocks_non_allowed(self):
        user = self._make_user()
        self.service.set_member_user_modules(user.name)

        refreshed = frappe.get_doc("User", user.name)
        blocked = {b.module for b in refreshed.block_modules}
        allowed = {"Verenigingen", "Core", "Desk", "Home"}

        # None of the member allow-list modules are blocked.
        self.assertEqual(blocked & allowed, set())

        # At least one real module outside the allow-list IS blocked (e.g. the
        # Accounts/Selling/etc. modules ERPNext seeds). Derive from DB so the
        # assertion stays correct regardless of which apps are installed.
        all_modules = {m.name for m in frappe.get_all("Module Def", fields=["name"])}
        expected_blocked = all_modules - allowed
        if expected_blocked:
            self.assertTrue(
                blocked & expected_blocked,
                msg="Expected at least one non-allow-list module to be blocked",
            )

    def test_set_member_user_modules_idempotent(self):
        # Running twice must not accumulate duplicate block_modules rows or crash.
        user = self._make_user()
        self.service.set_member_user_modules(user.name)
        first = len(frappe.get_doc("User", user.name).block_modules)
        self.service.set_member_user_modules(user.name)
        second = len(frappe.get_doc("User", user.name).block_modules)
        self.assertEqual(first, second)

    # ============================================================ create_verenigingen_member_role

    def test_create_member_role_when_already_exists_raises(self):
        """create_verenigingen_member_role has NO exists-guard -- it always attempts an
        insert, so on a seeded site (role present) it fails rather than silently no-ops.
        This exercises the real insert + failure-handling path; the failed insert rolls
        back, leaving the shared role untouched."""
        self.assertTrue(frappe.db.exists("Role", "Verenigingen Member"))
        with self.assertRaises(Exception):
            self.service.create_verenigingen_member_role()
        # The pre-existing shared role is unaffected by the failed attempt.
        self.assertTrue(frappe.db.exists("Role", "Verenigingen Member"))

    # ============================================================ singleton

    def test_singleton_accessor(self):
        self.assertIsInstance(get_member_role_service(), MemberRoleService)
