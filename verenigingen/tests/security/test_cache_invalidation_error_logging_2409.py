"""#2409: a failed security-cache invalidation must be RECORDED, not only logged.

A failed `APISecurityFramework.invalidate_user_role_cache` leaves a revoked role effective
until the cached entry's TTL, and `frappe.logger()` output is not captured anywhere readable.
The four hooks keep their "never fail the save" contract and now write an Error Log row;
a deadlock/timeout is re-raised so the caller can retry.

Mock justified: a Redis failure cannot be produced for real from one session; it is injected
at the boundary the hooks call (invalidate_user_role_cache). The hooks' except handlers are real.
"""

from contextlib import ExitStack
from unittest import mock

import frappe
from frappe.exceptions import QueryDeadlockError

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.security import cache_invalidation as ci
from verenigingen.utils.security.authorization_engine import AuthorizationEngine

USER_T = "Security cache: user role cache invalidation failed"
PROFILE_T = "Security cache: all-users role cache invalidation failed"
HASROLE_T = "Security cache: role assignment cache invalidation failed"
MIGRATE_T = "Security cache: clearing security caches on migrate failed"
BOOM = "redis-down-2409"


def _redis_down(exc):
    """Fail only the Redis writes the invalidation really performs (the per-user key delete and the
    version bump for all users); every other cache call, including the ones Error Log's own insert
    makes, passes through to the real cache."""
    stack = ExitStack()
    for name in ("delete_value", "set_value"):
        real = getattr(frappe.cache, name)

        def flaky(key, *args, _real=real, **kwargs):
            if str(key).startswith("user_role_profiles_v") or key == AuthorizationEngine.CACHE_VERSION_KEY:
                raise exc
            return _real(key, *args, **kwargs)

        # Mock justified: infrastructure failure (Redis) cannot be produced for real from one session;
        # the hooks, APISecurityFramework and the engine's invalidation all stay real.
        stack.enter_context(mock.patch.object(frappe.cache, name, flaky))
    return stack


class TestCacheInvalidationErrorLogging2409(EnhancedTestCase):
    def _rows(self, title):
        return frappe.get_all("Error Log", filters={"method": title}, fields=["name", "error"], order_by="creation asc")

    def _assert_recorded(self, title, call, *needles):
        self.expectErrorLog(title)
        before = self._rows(title)
        with _redis_down(RuntimeError(BOOM)):
            call()  # must not raise: the save is never failed by a cache problem
        rows = self._rows(title)
        self.assertEqual(len(rows), len(before) + 1, "expected exactly one new Error Log row")
        for needle in (BOOM, "Traceback") + needles:
            self.assertIn(needle, rows[-1].error)

    def test_user_hook_failure_is_recorded(self):
        self._assert_recorded(USER_T, lambda: ci.invalidate_user_role_cache_on_user_update(
            frappe._dict(name="u-2409@example.invalid"), "on_update"), "u-2409@example.invalid")

    def test_role_profile_hook_failure_is_recorded(self):
        self._assert_recorded(PROFILE_T, lambda: ci.invalidate_all_user_caches_on_role_profile_update(
            frappe._dict(name="RP-2409"), "on_update"), "RP-2409")

    def test_has_role_hook_failure_is_recorded(self):
        self._assert_recorded(HASROLE_T, lambda: ci.invalidate_user_cache_on_user_role_update(
            frappe._dict(parent="u-2409@example.invalid", parenttype="User"), "on_update"), "u-2409@example.invalid")

    def test_migrate_clear_failure_is_recorded(self):
        self._assert_recorded(MIGRATE_T, ci.clear_security_caches_on_migrate)

    def test_control_successful_invalidation_records_nothing(self):
        titles = (USER_T, PROFILE_T, HASROLE_T, MIGRATE_T)
        before = {t: len(self._rows(t)) for t in titles}
        ci.invalidate_user_role_cache_on_user_update(frappe._dict(name="u"), "on_update")
        ci.invalidate_all_user_caches_on_role_profile_update(frappe._dict(name="RP"), "on_update")
        ci.invalidate_user_cache_on_user_role_update(frappe._dict(parent="u", parenttype="User"), "on_update")
        self.assertEqual({t: len(self._rows(t)) for t in titles}, before)

    def test_hooks_survive_log_error_itself_raising(self):
        """Recording is best-effort: if Error Log cannot be written (e.g. a Redis TimeoutError inside
        log_error's own cache access), the hook must still not fail the save."""
        # Mock justified: infrastructure failure inside frappe.log_error cannot be produced for real.
        with _redis_down(RuntimeError(BOOM)), mock.patch.object(frappe, "log_error", side_effect=OSError("log-2409")):
            ci.invalidate_user_role_cache_on_user_update(frappe._dict(name="u"), "on_update")
            ci.invalidate_all_user_caches_on_role_profile_update(frappe._dict(name="RP"), "on_update")
            ci.invalidate_user_cache_on_user_role_update(frappe._dict(parent="u", parenttype="User"), "on_update")

    def test_deadlock_is_reraised_not_swallowed(self):
        """Defensive, not reachable today: the live handlers do Redis-only work, no frappe.db."""
        with _redis_down(QueryDeadlockError()):
            with self.assertRaises(QueryDeadlockError):
                ci.invalidate_user_role_cache_on_user_update(frappe._dict(name="u"), "on_update")
            with self.assertRaises(QueryDeadlockError):
                ci.invalidate_all_user_caches_on_role_profile_update(frappe._dict(name="RP"), "on_update")
            with self.assertRaises(QueryDeadlockError):
                ci.invalidate_user_cache_on_user_role_update(frappe._dict(parent="u", parenttype="User"), "on_update")
            with self.assertRaises(QueryDeadlockError):
                ci.clear_security_caches_on_migrate()
