"""#782: `cache_with_ttl` must not serve one user's result to another.

The key was `func.__name__` + hash(args), with no session in it. Every no-argument
call therefore collided on one key, and because a cache hit returns *before* the
function body runs, any session read or permission check inside that body was
skipped for every caller after the first.

Measured before the fix, read-only on a production data copy:

    A: user owns Assoc-Member-2026-01-33713 -> resolved ...33713   OK
    B: user owns Assoc-Member-2026-01-33584 -> resolved ...33713   MISMATCH

Three of the decorator's four call sites were in that shape: `get_member_from_user`
(one member's payment dashboard resolving to another), `get_chapter_dashboard_data`
and `format_member_address` (both carrying their access check inside the cached
body, so a hit bypassed it).
"""

import unittest

import frappe

from verenigingen.utils.error_handling import cache_with_ttl


class TestCacheWithTTLIsPerUser(unittest.TestCase):
    def setUp(self):
        self._original_user = frappe.session.user

    def tearDown(self):
        frappe.session.user = self._original_user

    def test_two_users_do_not_share_a_no_argument_result(self):
        """The measured #782 shape: a no-arg call keyed only on args."""
        calls = []

        @cache_with_ttl(ttl=300)
        def whoami():
            calls.append(frappe.session.user)
            return frappe.session.user

        frappe.session.user = "alice@example.com"
        self.assertEqual(whoami(), "alice@example.com")

        frappe.session.user = "bob@example.com"
        self.assertEqual(
            whoami(),
            "bob@example.com",
            "bob received alice's cached result -- the cache key is missing the session user",
        )
        self.assertEqual(calls, ["alice@example.com", "bob@example.com"])

    def test_a_permission_check_inside_the_body_still_runs_for_a_second_user(self):
        """A cache hit returns before the body, so an in-body check must not be skipped.

        This is the `get_chapter_dashboard_data` / `format_member_address` shape,
        and it is the more serious half of #782: not a wrong answer, but an
        authorization check that never executes.
        """
        body_ran = []

        @cache_with_ttl(ttl=300)
        def board_only(chapter):
            body_ran.append(frappe.session.user)
            if frappe.session.user != "allowed@example.com":
                raise frappe.PermissionError("You don't have access to this chapter")
            return {"chapter": chapter, "secret": "board-only payload"}

        frappe.session.user = "allowed@example.com"
        self.assertEqual(board_only("Amsterdam")["secret"], "board-only payload")

        frappe.session.user = "stranger@example.com"
        with self.assertRaises(frappe.PermissionError):
            board_only("Amsterdam")

        self.assertEqual(
            body_ran,
            ["allowed@example.com", "stranger@example.com"],
            "the cached body was skipped for the second user, taking its permission check with it",
        )

    def test_the_cache_still_caches(self):
        """Control: without this, a decorator that never caches would pass the two above."""
        calls = []

        @cache_with_ttl(ttl=300)
        def counted():
            calls.append(1)
            return len(calls)

        frappe.session.user = "alice@example.com"
        self.assertEqual(counted(), 1)
        self.assertEqual(counted(), 1, "second call for the same user should be served from cache")
        self.assertEqual(calls, [1], "the body ran twice -- caching is broken, not just scoped")

    def test_per_user_false_still_shares_across_users(self):
        """The opt-out an argument-only reference list uses (skills list, #782)."""
        calls = []

        @cache_with_ttl(ttl=300, per_user=False)
        def shared_reference_list():
            calls.append(frappe.session.user)
            return ["skill-a", "skill-b"]

        frappe.session.user = "alice@example.com"
        self.assertEqual(shared_reference_list(), ["skill-a", "skill-b"])
        frappe.session.user = "bob@example.com"
        self.assertEqual(shared_reference_list(), ["skill-a", "skill-b"])
        self.assertEqual(calls, ["alice@example.com"], "per_user=False should share one entry")


if __name__ == "__main__":
    unittest.main()
