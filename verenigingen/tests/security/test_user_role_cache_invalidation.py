# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Tests for #693: the user role-profile cache (AuthorizationEngine's versioned
Redis cache -- see authorization_engine.get_user_role_profiles) is never
invalidated when a user's roles/role profile change via the normal User.save()
path used by every role-granting service in this app
(ChapterBoardMember.assign_board_member_role, sync_user_role_profile,
member_role_service, ...).

Both existing hooks/doc_events.py handlers miss this:

- "User".on_update -> invalidate_user_role_cache_on_user_update was gated on
  has_value_changed("role_profile_name") alone, which (a) never fires for a
  role APPEND (user.append("roles", ...); user.save()) since that never
  touches role_profile_name, and (b) misses Frappe v16, where role profile
  assignment moves into the role_profiles child table
  (User.move_role_profile_name_to_role_profiles()).
- "Has Role".on_update/on_trash -> invalidate_user_cache_on_user_role_update
  never fires at all for roles changed via the parent User doc: Has Role is a
  child table (istable=1), and doc_events on a child DocType do not dispatch
  for rows saved through the parent -- see hooks/doc_events.py's own CHILD
  TABLES note. Kept as-is; it is the only cover for a Has Role row
  loaded/saved directly.

These tests drive REAL doc_events dispatch (an actual user.save()), not the
static doc_events dict, and assert the real Redis-backed cache entry is gone
afterward -- proof of dispatch, not proof of registration. Run:

  cd ~/frappe-bench && PYTHONPATH=<worktree> bench --site test_site_8 \
    run-tests --app verenigingen \
    --module verenigingen.tests.security.test_user_role_cache_invalidation
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.security.authorization_engine import get_authorization_engine


class TestUserRoleCacheInvalidationOnRoleChange(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.engine = get_authorization_engine()

    def _make_plain_user(self, prefix):
        email = f"{prefix}-{frappe.generate_hash(length=8).lower()}@example.invalid"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": prefix.title(),
                "last_name": "RoleCacheTest",
                "enabled": 1,
            }
        )
        user.insert(ignore_permissions=True)
        self.track_doc("User", user.name)
        return user

    def _prime_cache(self, user_name):
        """Populate the Redis-backed role-profile cache for this user, the way
        any real request would (e.g. an authorization check), and return its
        cache key."""
        self.engine.get_user_role_profiles(user_name)
        cache_key = self.engine._get_versioned_cache_key(user_name)
        self.assertIsNotNone(
            frappe.cache.get_value(cache_key),
            "precondition: cache must be primed before the test can prove invalidation",
        )
        return cache_key

    def _grant_role_via_save(self, user, role):
        """Mirrors ChapterBoardMember.assign_board_member_role /
        member_role_service: append the role on the parent User doc and save --
        the shape every production role-granting path in this app uses."""
        user.append("roles", {"role": role})
        user.save(ignore_permissions=True)

    def _grant_role_profile_via_save(self, user, profile):
        """Mirrors sync_user_role_profile's v16 write shape."""
        user.set("role_profiles", [{"role_profile": profile}])
        user.role_profile_name = profile
        user.save(ignore_permissions=True)

    def _persist_role_withdrawal_via_save(self, user, role):
        """Mirrors ChapterBoardMember.withdraw_board_member_role_if_unseated:
        remove a row from user_doc.roles and save the parent."""
        row = next(d for d in user.roles if d.role == role)
        user.roles.remove(row)
        user.save(ignore_permissions=True)

    def _persist_unrelated_change(self, user):
        user.full_name = "Something Else Entirely"
        user.save(ignore_permissions=True)

    def test_appending_a_role_and_saving_invalidates_the_cache(self):
        """The dominant production shape: ChapterBoardMember.assign_board_member_role,
        BoardManager, member_role_service etc. all grant a role via
        user_doc.append("roles", ...); user_doc.save() -- never touching
        role_profile_name."""
        user = self._make_plain_user("rolecache-append")
        cache_key = self._prime_cache(user.name)

        self._grant_role_via_save(user, "Verenigingen Chapter Board Member")

        self.assertIsNone(
            frappe.cache.get_value(cache_key),
            "role-profile cache must be invalidated when a role is granted via User.save()",
        )

    def test_setting_role_profiles_child_table_invalidates_the_cache(self):
        """Frappe v16: role profile assignment lives in the role_profiles child
        table, not the deprecated role_profile_name Link alone (#693's
        premise: User.move_role_profile_name_to_role_profiles() moves it
        there)."""
        user = self._make_plain_user("rolecache-profile")
        cache_key = self._prime_cache(user.name)

        self._grant_role_profile_via_save(user, "Verenigingen Treasurer")

        self.assertIsNone(
            frappe.cache.get_value(cache_key),
            "role-profile cache must be invalidated when role_profiles changes via User.save()",
        )

    def test_removing_a_role_and_saving_invalidates_the_cache(self):
        """The withdrawal mirror of the append test --
        ChapterBoardMember.withdraw_board_member_role_if_unseated removes a row
        from user_doc.roles and calls user_doc.save()."""
        user = self._make_plain_user("rolecache-remove")
        self._grant_role_via_save(user, "Verenigingen Chapter Board Member")

        cache_key = self._prime_cache(user.name)

        self._persist_role_withdrawal_via_save(user, "Verenigingen Chapter Board Member")

        self.assertIsNone(
            frappe.cache.get_value(cache_key),
            "role-profile cache must be invalidated when a role is withdrawn via User.save()",
        )

    def test_unrelated_field_save_also_invalidates(self):
        """Documents the tradeoff explicitly: the fix invalidates on every User
        save rather than trying to enumerate every field that can carry a role
        change -- Table-field has_value_changed compares child Document
        objects by identity, which is always True/unreliable for a reloaded
        doc-before-save vs. the live doc, so a narrower field gate cannot be
        made reliable. A spurious Redis delete on an unrelated save is cheap;
        a missed one is a security-adjacent staleness bug."""
        user = self._make_plain_user("rolecache-unrelated")
        cache_key = self._prime_cache(user.name)

        self._persist_unrelated_change(user)

        self.assertIsNone(frappe.cache.get_value(cache_key))


if __name__ == "__main__":
    import unittest

    unittest.main()
