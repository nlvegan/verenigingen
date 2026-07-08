# Domain I1 — Shared Infrastructure / Framework / Performance: Test Inventory

Read-only classification of every `def test_*` method across the 24 assigned
files (2 infrastructure, 5 optimization, 4 performance, 13 utils). Each method
tagged HAPPY (nominal success) / UNHAPPY (expects error/throw/rejection) / EDGE
(boundary, empty/null, duplicate, concurrency, idempotency, missing, retry) /
OTHER (smoke/import-safety/tautology, or perf test asserting only timing).

**3 files contain zero test methods** (base-class or helper-module
definitions, not TestCases): `test_base_framework.py`,
`test_environment_validator.py`, `test_config.py`.

## Per-file breakdown

| File | Total | Happy | Unhappy | Edge | Other |
|------|-------|-------|---------|------|-------|
| services/infrastructure/tests/test_base_service_and_metrics.py | 46 | 22 | 5 | 19 | 0 |
| services/infrastructure/tests/test_service_infrastructure.py | 11 | 9 | 1 | 1 | 0 |
| tests/backend/optimization/test_chapter_dashboard_api.py | 1 | 0 | 0 | 0 | 1 |
| tests/backend/optimization/test_member_management.py | 1 | 0 | 0 | 0 | 1 |
| tests/backend/optimization/test_payment_dashboard.py | 1 | 0 | 0 | 0 | 1 |
| tests/backend/optimization/test_sepa_batch_ui.py | 1 | 0 | 0 | 0 | 1 |
| tests/backend/optimization/test_sepa_reconciliation.py | 1 | 0 | 0 | 0 | 1 |
| tests/backend/performance/test_api_optimization.py | 12 | 6 | 4 | 2 | 0 |
| tests/backend/performance/test_api_performance.py | 9 | 0 | 0 | 0 | 9 |
| tests/backend/performance/test_member_bulk_optimization.py | 6 | 2 | 0 | 4 | 0 |
| tests/backend/performance/test_performance_edge_cases.py | 12 | 0 | 0 | 4 | 8 |
| tests/utils/test_base_framework.py | 0 | 0 | 0 | 0 | 0 |
| tests/utils/test_background_jobs.py | 28 | 13 | 4 | 10 | 1 |
| tests/utils/test_db_advisory_lock.py | 30 | 14 | 3 | 13 | 0 |
| tests/utils/test_error_log_guard.py | 12 | 4 | 2 | 6 | 0 |
| tests/utils/test_environment_validator.py | 0 | 0 | 0 | 0 | 0 |
| tests/utils/test_field_encryption.py | 11 | 5 | 0 | 6 | 0 |
| tests/utils/test_config.py | 0 | 0 | 0 | 0 | 0 |
| tests/utils/test_settings_utils.py | 23 | 17 | 0 | 4 | 2 |
| tests/utils/test_analytics_engine.py | 9 | 8 | 1 | 0 | 0 |
| tests/utils/test_api_classifier.py | 51 | 38 | 2 | 11 | 0 |
| tests/utils/test_optimized_queries_coverage.py | 49 | 9 | 23 | 17 | 0 |
| **DOMAIN TOTALS** | **314** | **147** | **45** | **97** | **25** |

## Observations

- **The 5 optimization files are dead weight — identical copy-paste smoke
  scripts.** Each contains one module-level `def test_optimized_endpoints()`
  (not a TestCase method, so a `bench run-tests` / unittest loader never
  collects it). They only `print()` timings and `print("All tests passed!")`;
  the sole "assertion" is a bare `try/except Exception` that prints on error
  and swallows it. Zero real assertions across all five. All 5 → OTHER.

- **`test_api_performance.py` is almost entirely tautological (9/9 OTHER).**
  Most tests build a local dict/list, do arithmetic on hardcoded numbers
  (`avg_time == 62.5`, `hit_rate == 50.0`, error-rate `== 5.0`), or spin up
  `ThreadPoolExecutor` over `time.sleep()` — exercising Python stdlib, not any
  Verenigingen code. `test_rate_limiting_enforcement` explicitly asserts the
  `rate_limit` decorator is a no-op pass-through stub, and
  `test_performance_threshold_alerts` patches `frappe.log_error` but never
  asserts on it (comment: "would log"). No behavioral coverage of production.

- **`test_performance_edge_cases.py` splits perf-timing-only (8 OTHER) vs. real
  concurrency (4 EDGE).** The OTHER tests assert only `duration < Ns` plus a
  not-None sanity check (memory is deliberately *observed, not asserted* per
  in-code notes about flaky `psutil` system-wide readings);
  `test_operation_timeouts`/`test_resource_limit_handling` operate on local
  lists/sleeps with no production code. The 4 EDGE tests genuinely exercise
  threaded create/read-write/pooling contention with progress + error-bound
  assertions.

- **The strongest files are the newer, correctness-oriented sweeps.**
  `test_optimized_queries_coverage.py` (49 tests) recomputes each optimized
  JOIN/aggregate against an independent flat query and pins exact values
  (guarding a real payment-fan-out DISTINCT bug); it is also injection-heavy
  (23 UNHAPPY ValueError guards). `test_api_classifier.py` (51) drives real AST
  parsing + a full scan of the live `api/` tree with invariant checks
  (breakdowns sum to total). `test_background_jobs.py` and
  `test_db_advisory_lock.py` assert concrete cache/DB side effects and lock
  state transitions rather than mock call counts.

- **`test_base_service_and_metrics.py` (46 tests) is Edge-rich (19)** because
  it systematically covers boundaries: error-rate health thresholds, LRU/idle
  eviction caps, empty-percentile metrics, idempotent begin/no-op commit, and
  savepoint rollback. Solid unit coverage of the service base classes.

- **Mild weak spots to flag, not tautologies:** `test_analytics_engine.py` is
  8/9 HAPPY "contract" tests that mostly assert dict-key presence +
  `assertNotIn("error", result)` (structure checks) — though 2 are genuine
  regression guards (owner-column, LIKE `%` escaping) that seed rows and assert
  they surface. In `test_settings_utils.py`,
  `test_default_days_back_limit_constant` just pins a literal (`== 1825`) and
  `test_clear_settings_cache_no_raise` is a no-raise smoke — both OTHER.

## Missing / non-collectible files

- `tests/utils/test_base_framework.py` — defines the `VerenigingenTestCase`
  base class only; no `test_*` methods.
- `tests/utils/test_environment_validator.py` — defines a plain
  `TestEnvironmentValidator` helper class (`validate_*` methods + CLI `main()`),
  not a unittest TestCase; no `test_*` methods.
- `tests/utils/test_config.py` — global test-config helper module
  (`setup_global_test_config`, `mock_sendmail`, monkey-patch on import); no
  `test_*` methods.
- All 5 `tests/backend/optimization/*` files: the single `test_*` in each is a
  module-level function outside any TestCase, so standard collection skips it
  (counted here as OTHER per the "classify every def test_*" instruction).
