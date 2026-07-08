# Domain A2 — Member Approval / Application / Creation: Test Inventory

Read-only classification of every `def test_*` method across the membership-application/approval/creation service tests and the MijnRood `event_application` sync-service tests. HAPPY = nominal success; UNHAPPY = expects error/throw/failure-result/rejection; EDGE = boundary/empty/null/duplicate/idempotency/malformed/concurrency/routing-fallback; OTHER = smoke/config-assertion/tautological/stub.

## Per-file breakdown

| File | Total | Happy | Unhappy | Edge | Other |
|------|-------|-------|---------|------|-------|
| services/test_application_approval_correlator.py | 8 | 2 | 0 | 6 | 0 |
| services/test_application_helpers.py | 39 | 25 | 6 | 8 | 0 |
| services/test_application_payments.py | 12 | 6 | 1 | 5 | 0 |
| services/test_member_approval_service.py | 12 | 5 | 3 | 4 | 0 |
| services/test_membership_application_service.py | 18 | 11 | 3 | 3 | 1 |
| services/test_membership_creation_service.py | 23 | 6 | 8 | 8 | 1 |
| services/test_member_account_coverage_supplement.py | 28 | 14 | 2 | 12 | 0 |
| services/test_member_import_service.py | 14 | 5 | 0 | 5 | 4 |
| services/test_membership_import_payment_period.py | 10 | 5 | 0 | 5 | 0 |
| services/test_field_sync_integration.py | 10 | 5 | 0 | 3 | 2 |
| services/test_operation_result_migration.py | 7 | 5 | 1 | 1 | 0 |
| event_application/test_volunteer_sync_service.py | 44 | 17 | 9 | 18 | 0 |
| event_application/test_mapping_service.py | 16 | 6 | 1 | 9 | 0 |
| event_application/test_termination_sync_service.py | 6 | 1 | 1 | 4 | 0 |
| event_application/test_member_sync_service.py | 10 | 4 | 2 | 4 | 0 |
| event_application/test_application_sync_service.py | 23 | 11 | 1 | 10 | 1 |
| event_application/test_related_records_orchestrator.py | 31 | 11 | 1 | 19 | 0 |
| **DOMAIN TOTALS** | **311** | **139** | **39** | **124** | **9** |

## Observations

- **Balanced coverage overall.** 139 happy / 39 unhappy / 124 edge is a healthy shape for a sync/approval domain — nearly every method has a companion missing/empty/idempotent-branch test. The high EDGE count is driven by the MijnRood `event_application` suites, which systematically test every short-circuit guard (missing member/volunteer/division, already-on-board/team, empty payloads, idempotent re-apply).

- **Base classes.** The domain-logic suites use `EnhancedTestCase` (real-DB factory) almost exclusively. Three CSV-import files (`test_member_import_service.py`, `test_membership_import_payment_period.py`, `test_operation_result_migration.py`) use Frappe's plain `FrappeTestCase`; the first two are legitimately mock/pure-unit (advisory locks, dispatcher routing with `MagicMock` member docs).

- **OTHER / weak tests worth flagging:**
  - `test_application_sync_service.py::TestPromoteApplicationMember::test_returns_failure_when_import_service_returns_skipped` — body is `pass`, asserts nothing (explicit self-admitted structural stub deferring to another suite).
  - `test_member_import_service.py` has 4 weak tests: `test_lock_constants_are_sensible` / `test_get_lock_config_returns_tuple` (assert constants are in a range / are a tuple — config smoke), and especially `test_exponential_backoff_formula` (recomputes `base*2^i` itself then asserts the sequence doubles — **tautological**, exercises no production code). `test_mijnrood_strategies_are_consistent` asserts on a static class constant.
  - `test_field_sync_integration.py`: `test_user_to_member_sync_email` and `test_reverse_lookup_uses_correct_column` only inspect the sync-config dict (existence/key names) rather than executing a sync — config assertions, not behavior. (Note the file's own docstring claims the latter is "the exact test that would have caught the bug," but it only reads config, not runtime SQL — that regression is actually covered by the sibling `test_actual_sql_query_executes` / real save tests.)
  - `test_membership_application_service.py` and `test_membership_creation_service.py` each carry a singleton-accessor identity test (`assertIs` / `assertIsInstance`) — low-value but harmless.

- **Notable UNHAPPY gaps (services with no negative-path coverage):**
  - `test_membership_import_payment_period.py` (0 unhappy) — the `frappe.ValidationError` cases are all routed to the graceful-fallback (EDGE) path; there is no test asserting a resolution error is ever surfaced to the operator.
  - `test_field_sync_integration.py` (0 unhappy) — bidirectional Member↔User sync has no test for a failing/rejected sync (e.g. invalid User, permission failure); only the graceful missing-link edge.
  - `test_member_import_service.py` (0 unhappy) — advisory-lock code has no test for lock-acquisition *failure/timeout* (contention path), only success + reentrant + configurable-constant assertions.

- **Strong negative/edge concentration in the sync layer.** `test_volunteer_sync_service.py` (9 unhappy) and `test_membership_creation_service.py` (8 unhappy) carry the domain's throw/rejection coverage — input-validation throws (None/wrong-doctype/negative/non-numeric dues rate) and role/chapter/team "does-not-exist" error messages. The correlator (`test_application_approval_correlator.py`) is almost entirely EDGE (6/8): every mismatch/ambiguity/no-match veto branch is tested, but its two success paths are the only HAPPY cases and it fully mocks `_load_candidates`/`_emit_approved_event` (dedup/pairing logic tested in isolation, not against real Sync Events).

- **All 17 listed files exist; none missing.**

## Classification notes on ambiguous calls (for auditor transparency)

- "Returns-failure-dict when *empty* payload" (e.g. `apply_approved` / `apply_new_membership_application` with `new_data={}`) → classified **EDGE** (empty-input boundary is the trigger). "Returns-failure when *no linked member found*" (a lookup miss/rejection) → classified **UNHAPPY**.
- Idempotent "already exists / already on board / already approved / already queued" skips returning `None`/success → **EDGE** (idempotency), not UNHAPPY.
- Dispatcher tests that mock downstream methods and assert call-routing (e.g. `_apply_role_actions`, `_create_related_records`, `_handle_*_change`) → **HAPPY** when verifying the nominal fan-out; **EDGE** when verifying a "no-transition / empty-config / missing-arg-warns" branch.
- `test_exponential_backoff_formula` counted OTHER (tautological). `test_returns_failure_when_import_service_returns_skipped` counted OTHER (empty `pass` body).
