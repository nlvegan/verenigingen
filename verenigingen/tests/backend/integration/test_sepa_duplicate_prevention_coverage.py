# Copyright (c) 2026, Verenigingen
# For license information, please see license.txt

"""
SEPA Duplicate Prevention - Coverage Sweep (helpers, TTL config, Redis paths)

Complements:
- ``test_sepa_duplicate_prevention_core.py`` (deterministic single-process safety
  contracts, in-memory locks, idempotency exact-once, amount tolerance), and
- ``test_sepa_security_feedback.py`` (Lua release, concurrency, XML hardening).

This module fills the remaining gaps, all exercised as REAL integration tests
against the REAL ``frappe.cache()`` (Redis) and REAL module state:

- ``_get_lock_ttl``: configured-override and every default branch.
- ``_extract_cacheable_result``: non-dict input, payment_entry_name / batch /
  error key extraction + long-error truncation.
- in-memory cache lifecycle: ``_cleanup_expired_cache_entries``, expired-entry
  eviction on read, and size-bounded eviction of oldest entries on write.
- ``_check_redis_required``: the multi-worker fail-fast (throws when Redis locks
  are NOT configured but >1 worker; passes when configured).
- idempotency-lock contention: a held in-memory lock makes a second
  ``execute_idempotent_operation`` raise ``ConcurrentOperationError``.
- the REDIS-BACKED paths, exercised by enabling ``use_redis_locks_for_sepa`` /
  ``use_redis_idempotency_cache`` against the running Redis: distributed
  processing-lock mutual exclusion, idempotency-lock acquire/release, the
  Redis idempotency cache round-trip, and the ``verify_redis_capabilities`` /
  ``check_redis_health`` diagnostics result shape.

NOTE on Redis behaviour: frappe's ``RedisWrapper.get()`` returns *bytes* and the
pooled client exposes ``connection = None`` (no single-connection ``eval``).
These tests therefore assert only the safety-critical facts that hold regardless
(SETNX mutual exclusion, dedup detection firing, result dict shape) and do NOT
assert the bytes-affected fields' truthiness. See the sweep report for the
documented latent defects in the opt-in Redis paths.

test-quality-enforcer: exempt-thread-context-setup
"""

import time
import uuid

import frappe

import verenigingen.api.sepa_duplicate_prevention as sdp
from verenigingen.api.sepa_duplicate_prevention import (
    DEFAULT_BATCH_LOCK_TTL,
    DEFAULT_LOCK_TTL,
    ConcurrentOperationError,
    _acquire_idempotency_lock,
    _check_redis_required,
    _cleanup_expired_cache_entries,
    _extract_cacheable_result,
    _get_cached_result,
    _get_lock_ttl,
    _release_idempotency_lock,
    _set_cached_result,
    acquire_processing_lock,
    check_redis_health,
    execute_idempotent_operation,
    generate_idempotency_key,
    release_processing_lock,
    verify_redis_capabilities,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _purge_key(key):
    """Drop a key from every in-memory structure so tests never poison siblings."""
    sdp._operation_cache.pop(key, None)
    sdp._processing_locks.pop(key, None)
    sdp._lock_tokens.pop(key, None)
    sdp._idempotency_lock_tokens.pop(key, None)


# =============================================================================
# _get_lock_ttl - configured override + every default branch
# =============================================================================


class TestGetLockTTL(EnhancedTestCase):
    """Operators can tune TTLs via site config; otherwise per-operation defaults apply."""

    def tearDown(self):
        frappe.conf.pop("sepa_lock_ttl_batch", None)
        super().tearDown()

    def test_configured_override_wins(self):
        frappe.conf["sepa_lock_ttl_batch"] = 4242
        self.assertEqual(_get_lock_ttl("batch"), 4242)

    def test_configured_override_is_coerced_to_int(self):
        frappe.conf["sepa_lock_ttl_batch"] = "777"
        self.assertEqual(_get_lock_ttl("batch"), 777)

    def test_default_for_each_known_operation(self):
        self.assertEqual(_get_lock_ttl("default"), DEFAULT_LOCK_TTL)
        self.assertEqual(_get_lock_ttl("batch"), DEFAULT_BATCH_LOCK_TTL)
        self.assertEqual(_get_lock_ttl("reconciliation"), DEFAULT_BATCH_LOCK_TTL)
        self.assertEqual(_get_lock_ttl("mandate"), DEFAULT_LOCK_TTL)

    def test_unknown_operation_falls_back_to_default_lock_ttl(self):
        self.assertEqual(_get_lock_ttl("totally_unknown_op"), DEFAULT_LOCK_TTL)

    def test_no_arg_uses_default(self):
        self.assertEqual(_get_lock_ttl(), DEFAULT_LOCK_TTL)


# =============================================================================
# _extract_cacheable_result - minimal projection of each identifier key
# =============================================================================


class TestExtractCacheableResult(EnhancedTestCase):
    """Only essential identifiers survive into the cache; everything else is dropped."""

    def test_non_dict_input_becomes_success_flag(self):
        # A truthy non-dict -> success True; a falsy non-dict -> success False.
        self.assertEqual(_extract_cacheable_result("anything"), {"success": True, "cached": True})
        self.assertEqual(_extract_cacheable_result(0), {"success": False, "cached": True})

    def test_payment_entry_key_extracted(self):
        out = _extract_cacheable_result({"success": True, "payment_entry": "PE-1", "noise": "x" * 50})
        self.assertEqual(out["payment_entry"], "PE-1")
        self.assertTrue(out["cached"])
        self.assertNotIn("noise", out)

    def test_payment_entry_name_key_extracted(self):
        out = _extract_cacheable_result({"payment_entry_name": "PE-NAME-9"})
        self.assertEqual(out["payment_entry_name"], "PE-NAME-9")

    def test_batch_key_extracted(self):
        out = _extract_cacheable_result({"batch": "BATCH-77"})
        self.assertEqual(out["batch"], "BATCH-77")

    def test_error_key_stringified_and_truncated(self):
        long_error = "E" * 500
        out = _extract_cacheable_result({"success": False, "error": long_error})
        self.assertFalse(out["success"])
        self.assertEqual(len(out["error"]), 200, "Long errors must be truncated to 200 chars")


# =============================================================================
# In-memory cache lifecycle: expiry cleanup, expired-on-read, size-bounded write
# =============================================================================


class TestInMemoryCacheLifecycle(EnhancedTestCase):
    """The bounded in-memory idempotency cache must self-clean by TTL and by size."""

    def setUp(self):
        super().setUp()
        self._keys = []
        self._orig_max = sdp._MAX_CACHE_ENTRIES

    def tearDown(self):
        sdp._MAX_CACHE_ENTRIES = self._orig_max
        for k in self._keys:
            _purge_key(k)
        super().tearDown()

    def _seed(self, key, age_seconds, ttl):
        """Place an entry whose timestamp is `age_seconds` in the past."""
        sdp._operation_cache[key] = ({"success": True}, time.time() - age_seconds, ttl)
        self._keys.append(key)

    def test_cleanup_removes_only_expired_entries(self):
        fresh = f"fresh_{uuid.uuid4().hex}"
        stale = f"stale_{uuid.uuid4().hex}"
        self._seed(fresh, age_seconds=1, ttl=3600)
        self._seed(stale, age_seconds=100, ttl=10)  # 100s old, 10s TTL -> expired
        with sdp._cache_mutex:
            _cleanup_expired_cache_entries()
        self.assertIn(fresh, sdp._operation_cache)
        self.assertNotIn(stale, sdp._operation_cache, "Expired entry must be purged")

    def test_expired_entry_is_dropped_on_read(self):
        key = f"exp_{uuid.uuid4().hex}"
        self._seed(key, age_seconds=100, ttl=5)  # expired
        found, result = _get_cached_result(key)
        self.assertFalse(found)
        self.assertIsNone(result)
        self.assertNotIn(key, sdp._operation_cache, "Read must evict the expired entry")

    def test_fresh_entry_is_returned_on_read(self):
        key = f"hit_{uuid.uuid4().hex}"
        self._seed(key, age_seconds=1, ttl=3600)
        found, result = _get_cached_result(key)
        self.assertTrue(found)
        self.assertEqual(result, {"success": True})

    def test_size_bound_evicts_oldest_on_write(self):
        # Shrink the cap so we can trigger the size-bounded eviction cheaply.
        sdp._MAX_CACHE_ENTRIES = 12
        # Fill to the cap with NON-expired entries of increasing age (oldest first).
        for i in range(12):
            k = f"bulk_{i}_{uuid.uuid4().hex}"
            # age decreases as i grows -> entry 0 is the oldest.
            self._seed(k, age_seconds=(20 - i), ttl=3600)
        oldest_key = self._keys[0]
        self.assertEqual(len(sdp._operation_cache), 12)

        # One more write must trim the oldest 12//10 == 1 entries, then insert.
        new_key = f"new_{uuid.uuid4().hex}"
        self._keys.append(new_key)
        _set_cached_result(new_key, {"success": True, "payment_entry": "PE-EVICT"})

        self.assertIn(new_key, sdp._operation_cache, "Newest entry must be stored")
        self.assertNotIn(oldest_key, sdp._operation_cache, "Oldest entry must be evicted")
        self.assertLessEqual(len(sdp._operation_cache), 12, "Cache must stay within the bound")


# =============================================================================
# _check_redis_required - multi-worker fail-fast
# =============================================================================


class TestCheckRedisRequiredMultiWorker(EnhancedTestCase):
    """In a multi-worker deployment without Redis locks, SEPA processing must refuse to run."""

    def setUp(self):
        super().setUp()
        self._orig_in_test = frappe.flags.in_test
        self._orig_dev = frappe.conf.get("developer_mode")
        self._orig_workers = frappe.conf.get("gunicorn_workers")
        self._orig_redis = frappe.conf.get("use_redis_locks_for_sepa")

    def tearDown(self):
        # Restore EVERYTHING and reset the once-per-request guard flag.
        frappe.flags.in_test = self._orig_in_test
        self._restore("developer_mode", self._orig_dev)
        self._restore("gunicorn_workers", self._orig_workers)
        self._restore("use_redis_locks_for_sepa", self._orig_redis)
        sdp._redis_requirement_checked = False
        super().tearDown()

    @staticmethod
    def _restore(key, value):
        if value is None:
            frappe.conf.pop(key, None)
        else:
            frappe.conf[key] = value

    def _arm_multiworker_non_dev(self):
        # The function early-returns under the test harness and in developer_mode;
        # disable both so the real multi-worker branch is reached.
        frappe.flags.in_test = False
        frappe.conf["developer_mode"] = 0
        frappe.conf["gunicorn_workers"] = 4
        sdp._redis_requirement_checked = False

    def test_throws_when_multiworker_without_redis_locks(self):
        self._arm_multiworker_non_dev()
        frappe.conf.pop("use_redis_locks_for_sepa", None)
        with self.assertRaises(frappe.ValidationError) as ctx:
            _check_redis_required()
        self.assertIn("Redis locks", str(ctx.exception))

    def test_passes_when_multiworker_with_redis_locks(self):
        self._arm_multiworker_non_dev()
        frappe.conf["use_redis_locks_for_sepa"] = True
        # Must NOT raise.
        self.assertIsNone(_check_redis_required())

    def test_skipped_under_test_harness(self):
        # With in_test True (default here), the multi-worker check is a no-op even
        # with workers configured and no Redis -> proves the harness escape hatch.
        frappe.flags.in_test = True
        frappe.conf["gunicorn_workers"] = 8
        frappe.conf.pop("use_redis_locks_for_sepa", None)
        sdp._redis_requirement_checked = False
        self.assertIsNone(_check_redis_required())


# =============================================================================
# Idempotency-lock contention (in-memory) -> ConcurrentOperationError
# =============================================================================


class TestIdempotencyLockContention(EnhancedTestCase):
    """A held idempotency lock blocks a second executor when no cached result exists."""

    def setUp(self):
        super().setUp()
        self.key = generate_idempotency_key("bank-x", "batch-x", f"op-{uuid.uuid4().hex}")
        self._held_token = None

    def tearDown(self):
        if self._held_token:
            _release_idempotency_lock(self.key, self._held_token)
        _purge_key(self.key)
        super().tearDown()

    def test_second_executor_raises_when_lock_held_and_cache_empty(self):
        # Acquire the lock OUT OF BAND (simulating "another worker holds it").
        self._held_token = _acquire_idempotency_lock(self.key)
        self.assertIsNotNone(self._held_token, "Precondition: lock must be acquirable")

        # A re-acquire while held must be refused (covers the in-memory still-active branch).
        self.assertIsNone(_acquire_idempotency_lock(self.key), "Held lock must refuse re-acquire")

        ran = {"n": 0}

        def op():
            ran["n"] += 1
            return {"success": True}

        # execute cannot get the lock, cache is empty -> ConcurrentOperationError, op never runs.
        with self.assertRaises(ConcurrentOperationError):
            execute_idempotent_operation(self.key, op)
        self.assertEqual(ran["n"], 0, "Operation must not run while another worker holds the lock")


# =============================================================================
# REDIS-BACKED paths (opt-in flags ON, real frappe.cache())
# =============================================================================


class _RedisEnabledTestCase(EnhancedTestCase):
    """Base: enable the opt-in Redis flags against the REAL cache, restore on teardown."""

    def setUp(self):
        super().setUp()
        self._orig_locks = frappe.conf.get("use_redis_locks_for_sepa")
        self._orig_cache = frappe.conf.get("use_redis_idempotency_cache")
        frappe.conf["use_redis_locks_for_sepa"] = True
        frappe.conf["use_redis_idempotency_cache"] = True
        self._redis_keys = []

    def tearDown(self):
        cache = frappe.cache()
        for k in self._redis_keys:
            try:
                cache.delete(k)
            except Exception:
                pass
        self._restore("use_redis_locks_for_sepa", self._orig_locks)
        self._restore("use_redis_idempotency_cache", self._orig_cache)
        # Reset the once-per-request / verification module flags.
        sdp._redis_requirement_checked = False
        sdp._redis_capabilities_verified = False
        super().tearDown()

    @staticmethod
    def _restore(key, value):
        if value is None:
            frappe.conf.pop(key, None)
        else:
            frappe.conf[key] = value


class TestRedisProcessingLockMutualExclusion(_RedisEnabledTestCase):
    """The distributed lock's core guarantee: a held resource cannot be double-acquired."""

    def setUp(self):
        super().setUp()
        self.resource_type = "test_redis_batch"
        self.resource_id = f"RLOCK-{uuid.uuid4().hex}"
        self._redis_keys.append(sdp._get_redis_lock_key(self.resource_type, self.resource_id))
        self._lock_mem_key = f"{self.resource_type}:{self.resource_id}"

    def tearDown(self):
        # Always release and purge so leftover Redis/in-memory state can't bleed.
        try:
            release_processing_lock(self.resource_type, self.resource_id)
        except Exception:
            pass
        _purge_key(self._lock_mem_key)
        super().tearDown()

    def test_redis_lock_blocks_concurrent_acquire(self):
        first = acquire_processing_lock(self.resource_type, self.resource_id, timeout=30)
        self.assertTrue(first, "First acquire on a free resource must succeed (Redis SETNX)")

        # SETNX guarantees the second acquire fails while the key exists.
        second = acquire_processing_lock(self.resource_type, self.resource_id, timeout=30)
        self.assertFalse(second, "A held Redis lock MUST block a concurrent acquire (double-debit guard)")

    def test_release_actually_frees_the_lock(self):
        acquire_processing_lock(self.resource_type, self.resource_id, timeout=30)
        # Exercises _release_redis_lock end-to-end (ownership-token lookup +
        # atomic compare-and-delete on the client). Must not raise.
        release_processing_lock(self.resource_type, self.resource_id)

        # Regression (cache.connection fix): the atomic Lua release runs on the
        # client itself. Before the fix, cache.connection was None so the atomic
        # path was skipped and the bytes-buggy fallback never matched the token —
        # the lock leaked until its TTL. Proof it is truly freed: re-acquire works.
        reacquired = acquire_processing_lock(self.resource_type, self.resource_id, timeout=30)
        self.assertTrue(reacquired, "After release the resource must be immediately re-acquirable (no TTL leak)")


class TestRedisIdempotencyCacheRoundTrip(_RedisEnabledTestCase):
    """With the Redis idempotency cache on, a stored result is detected on the next read."""

    def setUp(self):
        super().setUp()
        self.key = f"redis_idem_{uuid.uuid4().hex}"
        self._redis_keys.append(f"sepa_idempotency:{self.key}")

    def test_set_then_get_detects_existing_result(self):
        # Before: nothing cached.
        found_before, _ = _get_cached_result(self.key, ttl=60)
        self.assertFalse(found_before)

        _set_cached_result(self.key, {"success": True, "payment_entry": "PE-REDIS"}, ttl=60)

        # After: the Redis cache reports the operation as already done (dedup fires).
        found_after, result_after = _get_cached_result(self.key, ttl=60)
        self.assertTrue(found_after, "Redis idempotency cache must detect the stored result")
        # Regression (bytes-vs-str fix): the Redis path must return a parsed dict
        # with the same shape as the in-memory path, not raw JSON bytes. Before the
        # fix this came back as b'{"success": true, ...}'.
        self.assertIsInstance(result_after, dict, "Redis cache hit must deserialize to a dict")
        self.assertTrue(result_after["success"])
        self.assertEqual(result_after["payment_entry"], "PE-REDIS")


class TestRedisIdempotencyLock(_RedisEnabledTestCase):
    """The Redis SETNX idempotency lock acquires, then releases cleanly."""

    def setUp(self):
        super().setUp()
        self.key = f"redis_lock_{uuid.uuid4().hex}"
        self._redis_keys.append(f"sepa_idempotency_lock:{self.key}")
        self._token = None

    def tearDown(self):
        if self._token:
            try:
                _release_idempotency_lock(self.key, self._token)
            except Exception:
                pass
        _purge_key(self.key)
        super().tearDown()

    def test_acquire_returns_token_and_release_runs(self):
        self._token = _acquire_idempotency_lock(self.key, timeout=5)
        self.assertIsNotNone(self._token, "Redis idempotency lock must be acquirable on a free key")
        self.assertIsInstance(self._token, str)
        # Release exercises the Redis compare-and-delete branch; must not raise.
        _release_idempotency_lock(self.key, self._token)
        self._token = None


class TestRedisDiagnosticsShape(_RedisEnabledTestCase):
    """verify_redis_capabilities / check_redis_health produce well-formed reports when enabled."""

    def test_capability_report_shape_and_setnx_supported(self):
        result = verify_redis_capabilities()
        for k in (
            "redis_available",
            "set_nx_ex_supported",
            "eval_supported",
            "basic_ops_supported",
            "issues",
            "verified",
        ):
            self.assertIn(k, result)
        self.assertIsInstance(result["issues"], list)
        self.assertIsInstance(result["verified"], bool)
        # SETNX semantics genuinely work on the real Redis (correct fact, bytes-independent).
        self.assertTrue(result["set_nx_ex_supported"], "Real Redis must support SETNX (nx/ex) semantics")
        # Regression (bytes-vs-str + cache.connection fixes): against a real,
        # working Redis the probe must now report every capability as supported and
        # the overall verdict as verified. Before the fix, get() returned bytes
        # (basic_ops False) and cache.connection was None (eval False), so a healthy
        # Redis was reported broken.
        self.assertTrue(result["basic_ops_supported"], "Working Redis get()/set() must verify (bytes decode)")
        self.assertTrue(result["redis_available"])
        self.assertTrue(result["eval_supported"], "Lua eval() runs on the client itself (cache.connection is None)")
        self.assertTrue(result["verified"], f"Healthy Redis must verify; issues={result['issues']}")

    def test_health_report_shape_when_configured(self):
        result = check_redis_health()
        for k in ("healthy", "redis_configured", "redis_reachable", "capabilities_verified", "message"):
            self.assertIn(k, result)
        self.assertTrue(result["redis_configured"], "Flag is on -> health check must report it configured")
        self.assertIsInstance(result["message"], str)
        self.assertTrue(result["message"], "A configured health check must explain its verdict")
        # Regression (bytes-vs-str fix): the ping round-trip (set "ping", read it
        # back) compares the decoded value, so a reachable Redis now reports
        # reachable + healthy instead of failing on b"ping" != "ping".
        self.assertTrue(result["redis_reachable"], "A reachable Redis must report redis_reachable=True")
        self.assertTrue(result["healthy"], f"A reachable, capable Redis must be healthy; msg={result['message']}")
