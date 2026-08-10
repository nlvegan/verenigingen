"""
Integration tests for authentication/role-checking hooks.

Formerly tests for `utils/security_wrappers.py`. That module was retired on 2026-07-30:
it existed to prevent a vulnerability that does not exist — `frappe.get_roles(None)` does
not return every system role. `frappe/permissions.py:get_roles` returns `[GUEST_ROLE]` for
a falsy user and reaches its all-roles branch only for `"Administrator"`, where returning
every role is correct. The module was adopted by exactly one caller (`auth_hooks.py`, three
sites) which already pre-validated its input, against ~229 direct `frappe.get_roles()` calls
elsewhere, so it was pure maintenance burden.

What survives here is the coverage that was never about the wrappers: that the auth hooks
themselves fail closed on malformed input, and that a well-formed but nonexistent user
resolves to no privileged role. Tests that only asserted wrapper-internal behavior
(parameter rejection, audit logging, wrapper installation) went with the module.
"""

import unittest
from unittest.mock import Mock, patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class AuthHookRoleCheckTests(EnhancedTestCase):
    """The auth hooks must fail closed rather than raise on malformed users."""

    def test_role_checks_reject_malformed_users(self):
        """has_member_role / has_volunteer_role / has_system_access must return False.

        These take a user from session or request context, so they must tolerate every
        shape that context can produce — including the whitespace-only and junk-string
        cases that used to be filtered by the retired wrapper rather than by the hooks
        themselves. Each hook pre-validates its input, so retiring the wrapper cannot
        change these outcomes; this test is what proves that.
        """
        from verenigingen.auth_hooks import has_member_role, has_system_access, has_volunteer_role

        malformed = [None, "", "   ", "None", "null", "undefined", "Guest", 123, [], {}, "x" * 300]

        for check in (has_member_role, has_volunteer_role, has_system_access):
            for user in malformed:
                with self.subTest(check=check.__name__, user=repr(user)):
                    self.assertFalse(check(user), f"{check.__name__}({user!r}) must be False")

    def test_role_checks_return_false_for_real_user_without_the_role(self):
        """A real user lacking the role gets False — not an exception, not True."""
        from verenigingen.auth_hooks import has_member_role, has_system_access, has_volunteer_role

        test_member = self.create_test_member("Security", "Test")

        self.assertFalse(has_member_role(test_member.user))
        self.assertFalse(has_volunteer_role(test_member.user))
        self.assertFalse(has_system_access(test_member.user))

    def test_nonexistent_user_resolves_to_no_privileged_role(self):
        """The security property that actually matters.

        A well-formed but nonexistent user resolves to Frappe's base roles
        (["All", "Guest"]). What must hold is that no privileged role leaks — not that
        the list is empty. Asserted against frappe.get_roles directly because that is
        what the auth hooks now call.
        """
        roles = frappe.get_roles("user_being_created@example.invalid")

        self.assertIsInstance(roles, list)
        privileged = {"System Manager", "Administrator", "Verenigingen Administrator"}
        self.assertEqual(
            set(roles) & privileged,
            set(),
            f"Nonexistent user must not resolve to any privileged role, got {roles}",
        )

    def test_session_creation_hook_survives_malformed_session_user(self):
        """on_session_creation runs on every login and must not raise.

        A raise here breaks login itself, so the hook has to tolerate a session whose
        user is missing, non-string, or the literal "None".
        """
        from verenigingen.auth_hooks import on_session_creation

        for session_user in (None, 123, "None"):
            with self.subTest(session_user=repr(session_user)):
                with patch("frappe.session") as mock_session:
                    mock_session.user = session_user
                    try:
                        on_session_creation(Mock())
                    except Exception as e:
                        self.fail(f"on_session_creation raised for session.user={session_user!r}: {e}")


if __name__ == "__main__":
    unittest.main()
