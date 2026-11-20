"""
#2642: the idempotency marker written by ``execute_idempotent_operation`` lives
in the cache (Redis, or the in-process dict), outside the DB transaction.  A
transaction rolled back after the marker was written (a 1213 deadlock victim,
for instance) used to leave the marker claiming the operation was done, so the
retry was served the cached result and the real work never happened.

These tests drive a REAL database write and a REAL ``frappe.db.rollback()``, run
the retry, and assert on the cache state directly (not on query counts, and not
on ``frappe.cache().get`` bytes shapes).  Both backends are covered: the
in-process dict (the default) and Redis (``use_redis_idempotency_cache``).

test-quality-enforcer: exempt-thread-context-setup
"""

import uuid

import frappe

import verenigingen.api.sepa_duplicate_prevention as sdp
from verenigingen.api.sepa_duplicate_prevention import (
    ConcurrentOperationError,
    _get_cached_result,
    execute_idempotent_operation,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class _IdempotencyRollbackBase:
    """Mixin: the tests, parametrised by a backend subclass."""

    use_redis = False

    def setUp(self):
        super().setUp()
        self._orig_cache = frappe.conf.get("use_redis_idempotency_cache")
        if self.use_redis:
            frappe.conf["use_redis_idempotency_cache"] = True
        else:
            frappe.conf.pop("use_redis_idempotency_cache", None)
        self.key = f"idem2642_{uuid.uuid4().hex}"
        self.title = f"idem2642-{uuid.uuid4().hex}"

    def tearDown(self):
        sdp._operation_cache.pop(self.key, None)
        try:
            frappe.cache().delete(f"sepa_idempotency:{self.key}")
        except Exception:
            pass
        if self._orig_cache is None:
            frappe.conf.pop("use_redis_idempotency_cache", None)
        else:
            frappe.conf["use_redis_idempotency_cache"] = self._orig_cache
        super().tearDown()

    def _marker_present(self):
        found, _ = _get_cached_result(self.key, ttl=60)
        return found

    def _op(self, counter):
        """A real DB write: the row exists only if the transaction survives."""

        def op():
            counter["runs"] += 1
            frappe.get_doc({"doctype": "Note", "title": self.title, "content": "x"}).insert()
            return {"success": True, "payment_entry": "PE-2642"}

        return op

    def _create_committed_operation(self, op):
        """Run ``op`` and commit its transaction (writes no rows, so nothing leaks)."""
        execute_idempotent_operation(self.key, op, ttl=60)
        frappe.db.commit()

    def _note_exists(self):
        return bool(frappe.db.exists("Note", {"title": self.title}))

    def test_rolled_back_operation_is_not_marked_done_and_retry_runs(self):
        counter = {"runs": 0}
        op = self._op(counter)

        execute_idempotent_operation(self.key, op, ttl=60)
        self.assertTrue(self._note_exists())
        self.assertTrue(self._marker_present(), "marker is set while the transaction is open")

        frappe.db.rollback()  # e.g. the 1213 deadlock victim
        self.assertFalse(self._note_exists(), "the DB write was really rolled back")

        self.assertFalse(
            self._marker_present(), "a rolled-back operation must not stay marked done in the cache"
        )
        execute_idempotent_operation(self.key, op, ttl=60)
        self.assertEqual(counter["runs"], 2, "the retry must re-run the rolled-back operation")
        self.assertTrue(self._note_exists(), "the retry's write is present")

    def test_in_flight_and_uncommitted_duplicates_are_still_refused(self):
        counter = {"runs": 0}
        op = self._op(counter)
        seen = {}

        def outer():
            # the first caller is in flight and holds the lock: a second concurrent caller is refused
            try:
                execute_idempotent_operation(self.key, op, ttl=60)
            except ConcurrentOperationError:
                seen["refused"] = True
            return op()

        execute_idempotent_operation(self.key, outer, ttl=60)
        self.assertTrue(seen.get("refused"), "a concurrent duplicate must be refused while in flight")
        self.assertEqual(counter["runs"], 1, "the duplicate never ran")

        # after the first returned but before commit: a duplicate is served the marker, not re-run
        execute_idempotent_operation(self.key, op, ttl=60)
        self.assertEqual(counter["runs"], 1, "an uncommitted-but-live operation is not run twice")

    def test_committed_operation_stays_marked_across_a_later_unrelated_rollback(self):
        counter = {"runs": 0}

        def op():
            counter["runs"] += 1
            return {"success": True, "payment_entry": "PE-2642-COMMITTED"}

        self._create_committed_operation(op)
        frappe.db.rollback()  # a later, unrelated rollback must not clear it

        self.assertTrue(self._marker_present(), "committed work stays marked done")
        execute_idempotent_operation(self.key, op, ttl=60)
        self.assertEqual(counter["runs"], 1, "a committed operation is not re-run")


class TestIdempotencyRollbackInProcessCache(_IdempotencyRollbackBase, EnhancedTestCase):
    use_redis = False


class TestIdempotencyRollbackRedisCache(_IdempotencyRollbackBase, EnhancedTestCase):
    use_redis = True

    def test_redis_marker_lives_in_redis_not_the_dict(self):
        """Control: this class really exercises the Redis backend."""
        execute_idempotent_operation(self.key, lambda: {"success": True}, ttl=60)
        self.assertNotIn(self.key, sdp._operation_cache)
        self.assertTrue(self._marker_present())
