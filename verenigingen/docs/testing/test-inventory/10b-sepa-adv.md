# Domain A10b — SEPA Sequence-Type / Performance / Security / Weekly Features

Read-only test-method inventory. 15 files, all present, all under `verenigingen/tests/sepa/`.
195 `test_*` methods classified by dominant intent (HAPPY / UNHAPPY / EDGE / OTHER).

Classification rules applied:
- Query-count / N+1-elimination assertions with a real behavioral outcome → HAPPY (nominal, verified efficient) or EDGE (when the assertion is about a missing/non-existent lookup or a deliberately-forced N+1 pattern).
- Pure timing-threshold tests with no functional outcome → OTHER (performance-timing-only).
- Permission/CSRF **denial of a well-formed but unauthorized request** (usually `assertRaises`) → UNHAPPY.
- **Malformed/invalid/empty/None input** handling (even when it raises) → EDGE.
- FRST/RCUR/FNAL transitions, mixed-sequence batches, concurrency/locks, duplicates, boundary lengths → EDGE.
- Heavily `try/except pass` "integration exists" tests, instantiate-only smoke, tautological branch asserts, skipped → OTHER.

## Per-file breakdown

| File | Total | Happy | Unhappy | Edge | Other |
|------|------:|------:|--------:|-----:|------:|
| test_sepa_integration_performance.py | 7 | 2 | 1 | 2 | 2 |
| test_sepa_integration_real.py | 10 | 8 | 0 | 2 | 0 |
| test_sepa_optimizations_integration.py | 11 | 7 | 0 | 1 | 3 |
| test_sepa_option_ac_workflow.py | 10 | 4 | 1 | 2 | 3 |
| test_sepa_payment_notifications_integration.py | 15 | 11 | 0 | 4 | 0 |
| test_sepa_performance_optimization.py | 3 | 2 | 0 | 1 | 0 |
| test_sepa_performance_optimizations.py | 15 | 9 | 3 | 1 | 2 |
| test_sepa_performance_regression.py | 9 | 0 | 0 | 1 | 8 |
| test_sepa_realistic_business_scenarios.py | 9 | 1 | 2 | 6 | 0 |
| test_sepa_security_comprehensive.py | 32 | 21 | 5 | 4 | 2 |
| test_sepa_sequence_type_compliance.py | 5 | 0 | 0 | 5 | 0 |
| test_sepa_sequence_type_validation.py | 9 | 1 | 3 | 5 | 0 |
| test_sepa_week3_features.py | 21 | 6 | 2 | 8 | 5 |
| test_sepa_week4_monitoring.py | 27 | 22 | 0 | 5 | 0 |
| test_sepa_week4_r5_parity.py | 12 | 9 | 0 | 1 | 2 |
| **DOMAIN TOTALS** | **195** | **103** | **17** | **48** | **27** |

## Notable per-method calls (OTHER + non-obvious)

- **integration_performance**: `memory_efficiency_large_batch` + `recommendations_generation` → OTHER (asserts only under `if metrics:` / logs count, may assert nothing). `error_to_recovery_workflow` → UNHAPPY (`assertRegex` on SEPA validation error, `self.fail` if none).
- **optimizations_integration**: `database_indexes_presence` → OTHER (`@unittest.skip`, module removed). `performance_improvements` → OTHER (timing < 1.0 only). `monthly_batch_creation_optimization` → OTHER (no-crash smoke).
- **option_ac_workflow**: `01_processor_initialization` (init smoke), `05_dutch_payroll_timing_logic` (tautological — asserts the branch it just took), `10_integration_completeness` (import-safety) → OTHER.
- **performance_regression**: 8/9 are pure timing-threshold (OTHER); only `concurrent_access_performance` → EDGE (real 5-thread concurrency). None assert a functional outcome — this whole file is a perf gate.
- **performance_optimizations**: `processor_uses_performance_optimizer` (singleton-attached smoke) + `batch_creation_with_optimization` ("important thing is integration exists, not that it works" — try/except swallow) → OTHER.
- **week3_features**: `batch_creation_with_race_protection` + `rollback_operation_creation` → OTHER (try/except that prints exceptions as "valuable behavior", weak `isinstance` asserts; `rollback_operation_creation` has a latent bug: `assertIn` on `result` inside the `except` branch where `result` is unbound). `rollback_manager_initialization` + `end_to_end_batch_processing` → OTHER (instantiate-only). `performance_characteristics` → OTHER (timing).
- **week4_r5_parity**: enum-alias identity checks (`AlertSeverity is Severity`, `NotificationPriority is PriorityLevel`) → OTHER (near-tautological); enum-value + DB-table + dispatch parity → HAPPY.

## Observations

1. **Sequence-type coverage is strong and correct-minded.** The two dedicated files (`sequence_type_compliance`, `sequence_type_validation`) plus `realistic_business_scenarios::test_sepa_sequence_type_transitions` and `optimizations_integration`/`performance_regression` batch-seq tests give real FRST→RCUR lifecycle coverage: compliance file is all-EDGE real-DB integration (mixed FRST/RCUR → two PmtInf, single-seq byte-stability, 35-char PmtInfId truncation, confirmed-collection advances FRST→RCUR, failed-collection stays FRST). `sequence_type_validation` correctly splits critical-error (UNHAPPY, RCUR-on-first-use throws) from warning/auto-assign (EDGE). This is the highest-quality cluster in the domain.

2. **Performance-test rigor is bimodal.** Two genuinely rigorous styles: `assertQueryCount(N)` tests (`performance_optimization.py`, `performance_optimizations.py::TestBatchPerformanceOptimizer`) assert hard query ceilings against real seeded data — meaningful N+1 regression guards. But `performance_regression.py` is almost entirely wall-clock timing thresholds (`< 0.5s`, `< 2.0s`) against empty/near-empty tables — environment-fragile and asserting little behavioral (8/9 → OTHER). `realistic_business_scenarios::test_query_optimization_effectiveness` hedges with `query_count if hasattr(...) else estimate` fallbacks, weakening its >50%-reduction claim.

3. **Security file leans HAPPY-heavy but has real denial coverage.** `security_comprehensive.py` (32 tests) is 21 HAPPY, yet the security-critical assertions exist: `@require_sepa_permission` regression class (documents a real (operation, level) arg-swap that denied every non-admin), audit-log immutability (non-admin delete blocked), authorization-denial audit trail, and malformed/None CSRF-token rejection. Weak spot: `test_secure_api_endpoint_full_stack` is a try/except that passes on either success OR a security exception (OTHER — asserts nothing definite).

4. **Heavy reliance on EnhancedTestCase / VereningingenTestCase.** Base classes split roughly: real-DB integration files (`sequence_type_compliance`, `week4_monitoring`, `option_ac_workflow`, `performance_regression`, `sequence_type_validation`) use `VereningingenTestCase`; the optimizer/monitor/notification unit-ish files use `EnhancedTestCase`. `payment_notifications_integration` and parts of `week3_features` are MagicMock-mandate / patched-`send_sepa_email` tests (external-boundary stubs, not business-logic mocks) — legitimate but they mean those "notification" HAPPY tests exercise formatting/routing, not persistence.

5. **A pocket of low-value characterization/smoke.** 27 OTHER total concentrate in `performance_regression` (8 timing), `week3_features` (5 hedged/smoke), and the enum-alias parity checks. `week3_features::test_batch_creation_with_race_protection` and `test_rollback_operation_creation` explicitly print exceptions as "valuable for debugging" and assert only `isinstance(str(e), str)` — they cannot fail on a real regression; `rollback_operation_creation` additionally references an unbound `result` in its except branch.

6. **EDGE is the largest non-HAPPY bucket (48)** and is well-earned: SEPA's edge surface (mixed sequence types, closed/expired mandates, weekend/past collection dates, duplicate invoices, rate-limited alerts, partial-batch failures, malformed IBAN masking, unknown recipient groups) is genuinely exercised rather than only happy-path smoke.

## Missing files
None — all 15 assigned files exist and were audited.
