"""VereningingenTestCase.tearDown restores the session user through frappe.set_user (#1600).

A bare ``frappe.session.user = original`` moves the username string only.
``frappe.set_user`` also resets ``local.role_permissions``, ``local.user_perms``,
``local.cache`` and ``session.sid``, so whatever the last user's test built up
leaked into the next test in the same process.

The inner case is driven through ``unittest`` by hand so tearDown has run when we
look. Its methods are not ``test_*``-named, so the module's own collection does
not run them a second time.
"""

import unittest

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase


class _SessionUserProbe(VereningingenTestCase):
    """Dirties the permission caches in the body; the outer test inspects them after tearDown."""

    original_user = None

    def setUp(self):
        super().setUp()
        type(self).original_user = frappe.session.user

    def switched_user_builds_caches(self):
        frappe.set_user("Guest")
        frappe.get_roles("Guest")
        frappe.has_permission("User", "read")
        frappe.local.role_permissions["probe-1600"] = {"stale": True}
        frappe.local.cache["probe-1600"] = True

    def same_user_builds_caches(self):
        """The user never changes, yet the caches are dirty (an 'only act when different' fix misses it)."""
        frappe.get_roles(frappe.session.user)
        frappe.local.role_permissions["probe-1600"] = {"stale": True}
        frappe.local.cache["probe-1600"] = True


def _run_session_user_probe_1600(method_name):
    suite = unittest.TestSuite([_SessionUserProbe(method_name)])
    result = unittest.TestResult()
    suite.run(result)
    return result


class TestTeardownRestoresSessionUser(unittest.TestCase):
    def _assert_restored(self, method_name):
        result = _run_session_user_probe_1600(method_name)
        self.assertEqual([], [t[1] for t in result.errors + result.failures], "probe itself must pass")
        original = _SessionUserProbe.original_user
        self.assertEqual(original, frappe.session.user)
        self.assertEqual(original, frappe.session.sid, "set_user also resets session.sid")
        self.assertNotIn("probe-1600", frappe.local.role_permissions)
        self.assertNotIn("probe-1600", frappe.local.cache)

    def test_user_switched_in_body_is_restored_with_caches_reset(self):
        self._assert_restored("switched_user_builds_caches")

    def test_caches_dirtied_without_a_user_change_are_reset(self):
        self._assert_restored("same_user_builds_caches")
