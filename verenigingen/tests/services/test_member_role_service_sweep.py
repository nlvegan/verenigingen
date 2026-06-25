"""
Supplemental real-integration tests for
``verenigingen/services/member/account/member_role_service.py``.

These AUGMENT the existing coverage in
``verenigingen/tests/member/test_member_role_service_extended.py`` and
``test_member_service_coverage.py`` (do not duplicate them). The existing tests
cover: add_member_roles_to_user happy path / role-clearing / volunteer profile /
nonexistent-profile fallback / disabled-user enable; _assign_individual_member_roles
directly; set_member_user_modules block-list + idempotency; create_..._role
insert-on-seeded-site; the singleton accessor.

This sweep targets the remaining uncovered branches:

- ``add_member_roles_to_user`` permission guard: a user lacking User:write is
  rejected via ``frappe.throw`` and the method returns None (the outer try/except
  swallows the PermissionError into a None return + logged error).
- ``add_member_roles_to_user`` exception -> None return for a nonexistent user.
- ``_assign_individual_member_roles`` clear-then-add behaviour (pre-existing
  roles are wiped and only existing member roles are appended).
- ``set_member_user_modules`` error-swallow path for a nonexistent user (logs,
  returns None, never raises).

Real Users / Roles / Role Profiles are created/used; tests run as Administrator
except where a non-privileged context is explicitly required via ``as_user``.
No business-logic mocking.
"""

import frappe

from verenigingen.services.member.account.member_role_service import (
    MemberRoleService,
    get_member_role_service,
)
from verenigingen.tests.utils.base import VereningingenTestCase


class TestMemberRoleServiceSweep(VereningingenTestCase):
    """Cover the permission-guard / exception / skip branches of MemberRoleService."""

    def setUp(self):
        super().setUp()
        self.service = MemberRoleService()
        self.h = frappe.generate_hash(length=6)

    def _make_user(self, roles=None, user_type="System User"):
        email = f"mrolesweep.{self.h}.{frappe.generate_hash(length=4)}@test.invalid"
        user = self.create_test_user(email, roles=roles)
        if user_type and user.user_type != user_type:
            frappe.db.set_value("User", user.name, "user_type", user_type)
        self.track_doc("User", user.name)
        return user

    def _profile_names(self, user_name):
        return frappe.get_all(
            "User Role Profile",
            filters={"parent": user_name, "parenttype": "User"},
            pluck="role_profile",
        )

    # =============================================== add_member_roles_to_user: permission guard

    def test_add_roles_without_user_write_permission_returns_none(self):
        # A context WITHOUT User:write must not be able to assign member roles. The
        # method's guard (frappe.has_permission("User", "write")) fires, raises
        # frappe.throw, and the outer except swallows it into a None return (logging
        # the failure as an Error Log).
        #
        # NOTE on contract: frappe.has_permission("User", "write") with NO doc is a
        # doctype-level check that returns True for ANY authenticated user, because
        # every user can write their OWN User doc (self-service / if_owner). It only
        # returns False for the Guest/unauthenticated context. So the genuine
        # unprivileged context that exercises this guard is Guest, not an ordinary
        # (role-less) system user -- the latter still passes the guard. Verified in
        # console: a role-less system user has_permission("User","write") -> True;
        # Guest -> False.
        target = self._make_user()

        # The guard's failure path logs an Error Log before returning None; mark it
        # expected so the automatic tearDown check ignores it.
        self.expectErrorLog("Insufficient permissions")
        with self.as_user("Guest"):
            # Guest lacks User:write; the guard fires and the method returns None
            # rather than assigning anything.
            self.assertFalse(frappe.has_permission("User", "write"))
            result = self.service.add_member_roles_to_user(target.name)

        self.assertIsNone(result)
        # No role profile was assigned to the target.
        self.assertNotIn("Verenigingen Member", self._profile_names(target.name))

    # =============================================== add_member_roles_to_user: exception -> None

    def test_add_roles_for_nonexistent_user_returns_none(self):
        # frappe.get_doc("User", <missing>) raises DoesNotExistError inside the try;
        # the broad except logs and returns None (the documented failure contract).
        # expectErrorLog() is NOT a context manager -- it registers the expected
        # Error Log so the automatic tearDown check ignores the swallowed failure.
        self.expectErrorLog()
        result = self.service.add_member_roles_to_user("ghost-user-zzz@nope.invalid")
        self.assertIsNone(result)

    # =============================================== _assign_individual_member_roles: skip branch

    def test_assign_individual_clears_then_adds_existing_roles(self):
        # _assign_individual_member_roles iterates ["Verenigingen Member", "All"],
        # clears ALL pre-existing roles first, then appends the member roles that
        # exist in the Role table. Both roles exist on a seeded site, so this
        # asserts the clear-then-add behaviour: the prior privileged role is gone
        # and exactly the existing member roles are present (every assigned role is
        # a real Role doc).
        user = self._make_user(roles=["System Manager"])
        result = self.service._assign_individual_member_roles(user.name)
        self.assertEqual(result, user.name)

        refreshed = frappe.get_doc("User", user.name)
        roles_after = {r.role for r in refreshed.roles}
        # Both member roles exist on this site and were added.
        self.assertIn("Verenigingen Member", roles_after)
        self.assertIn("All", roles_after)
        # Pre-existing privileged role was cleared.
        self.assertNotIn("System Manager", roles_after)
        # Only roles that actually exist as Role docs are present.
        for role in roles_after:
            self.assertTrue(frappe.db.exists("Role", role), msg=f"phantom role assigned: {role}")

    # =============================================== set_member_user_modules: error-swallow

    def test_set_modules_for_nonexistent_user_swallows_and_returns_none(self):
        # set_member_user_modules wraps everything in try/except, logging and
        # returning None on failure (it must never break the ACR pipeline). A
        # nonexistent user makes frappe.get_doc raise; the method must swallow it.
        # expectErrorLog() registers the expected Error Log (it is not a context
        # manager); the method logs the swallowed failure and returns None.
        self.expectErrorLog()
        result = self.service.set_member_user_modules("ghost-user-zzz@nope.invalid")
        self.assertIsNone(result)

    def test_set_modules_blocks_all_but_allowed(self):
        # The success path returns None (it mutates the user, no return value) and
        # blocks every Module Def EXCEPT the allow-list (Verenigingen, Core, Desk,
        # Home). Assert ALL allowed modules are absent from block_modules AND at
        # least one non-allowed module that exists on the site IS blocked -- so the
        # test fails if the method blocked nothing (or blocked an allowed module).
        allowed = {"Verenigingen", "Core", "Desk", "Home"}
        user = self._make_user()
        with self.assertNoErrorLog():
            result = self.service.set_member_user_modules(user.name)
        self.assertIsNone(result)

        blocked = {b.module for b in frappe.get_doc("User", user.name).block_modules}
        # None of the allow-listed modules may be blocked.
        for mod in allowed:
            self.assertNotIn(mod, blocked, msg=f"allow-listed module wrongly blocked: {mod}")
        # A real, non-allowed Module Def must be blocked (proves blocking happened).
        non_allowed = [
            m.name
            for m in frappe.get_all("Module Def", filters={"name": ["not in", list(allowed)]}, fields=["name"])
        ]
        self.assertTrue(non_allowed, "site must have at least one non-allowed Module Def")
        self.assertTrue(
            blocked, "set_member_user_modules blocked nothing -- restriction did not run"
        )
        # Every non-allowed Module Def is blocked.
        for mod in non_allowed:
            self.assertIn(mod, blocked, msg=f"non-allowed module not blocked: {mod}")

    # =============================================== singleton / construction

    def test_singleton_accessor_returns_service(self):
        svc = get_member_role_service()
        self.assertIsInstance(svc, MemberRoleService)
        self.assertEqual(svc.service_name, "MemberRoleService")
