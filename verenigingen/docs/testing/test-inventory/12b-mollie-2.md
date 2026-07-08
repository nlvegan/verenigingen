# Test Inventory 12b — Mollie payments app, part 2

Read-only classification of every `def test_*` method across the 22 assigned files
in `verenigingen/verenigingen_payments/mollie/tests/`. Each method assigned ONE
primary type by dominant intent: HAPPY (nominal success), UNHAPPY (expects
error/throw/rejection/validation-failure), EDGE (boundary, empty/null, duplicate,
idempotency, retry/rollback, malformed data, clamp/cap, degradation), OTHER
(smoke / no-assertion / tautological / debug script).

Base class note: almost all use `EnhancedTestCase` (Enhanced Test Factory, real
DB, only the Mollie SDK boundary faked). Four orchestrator/logic files use plain
`unittest.TestCase` with `object.__new__` + boundary fakes: `*_orchestrator_unit`,
`*_orchestrator_flow_unit`, `*_orchestrator_sweep` (mixed), and the validation/
decimal/sanitization classes in `test_payment_entry_factory.py`.

## Per-file breakdown

| File | Total | Happy | Unhappy | Edge | Other |
|------|-------|-------|---------|------|-------|
| test_mollie_debug_service.py | 34 | 14 | 14 | 6 | 0 |
| test_mollie_error_recovery_unit.py | 28 | 7 | 3 | 18 | 0 |
| test_mollie_monitoring_api_unit.py | 17 | 12 | 1 | 4 | 0 |
| test_mollie_payment_db_integration.py | 7 | 3 | 0 | 4 | 0 |
| test_mollie_payment_orchestrator_flow_unit.py | 27 | 9 | 6 | 12 | 0 |
| test_mollie_payment_orchestrator_sweep.py | 19 | 8 | 6 | 5 | 0 |
| test_mollie_payment_orchestrator_unit.py | 19 | 8 | 1 | 10 | 0 |
| test_mollie_payment_processing.py | 26 | 6 | 12 | 8 | 0 |
| test_mollie_payments_debug.py | 16 | 10 | 2 | 3 | 1 |
| test_mollie_payments_debug_unit.py | 21 | 4 | 11 | 6 | 0 |
| test_mollie_portal_endpoints_live.py | 7 | 5 | 1 | 1 | 0 |
| test_mollie_portal_endpoints_unit.py | 9 | 2 | 4 | 3 | 0 |
| test_mollie_portal_subscription_query_unit.py | 16 | 5 | 4 | 7 | 0 |
| test_mollie_subscription_recreation_unit.py | 37 | 13 | 14 | 10 | 0 |
| test_mollie_sync_unit.py | 14 | 3 | 5 | 4 | 2 |
| test_order_payment_processor_integration.py | 15 | 5 | 2 | 8 | 0 |
| test_payment_context_resolver.py | 14 | 7 | 0 | 0 | 7 |
| test_payment_entry_factory_db.py | 18 | 11 | 1 | 6 | 0 |
| test_payment_entry_factory.py | 25 | 8 | 7 | 10 | 0 |
| test_payment_entry.py | 1 | 0 | 0 | 0 | 1 |
| test_payment_processors_extra.py | 14 | 5 | 3 | 6 | 0 |
| test_payment_processors.py | 18 | 14 | 1 | 3 | 0 |
| **DOMAIN TOTALS** | **402** | **159** | **98** | **134** | **11** |

## Observations

- **Balanced happy/unhappy/edge overall (159/98/134).** The suite is genuinely
  behavior-testing, not coverage-padding — the large orchestrator + error-recovery
  files skew heavily to EDGE (idempotency, circuit-breaker state machine, retry/
  backoff, TOCTOU invoice revalidation, partial-doc degradation, clamps/caps),
  which is appropriate for financial reconciliation code.

- **One live / skip-gated file:** `test_mollie_portal_endpoints_live.py` (7 tests)
  hits Mollie's REAL test API and `skipTest`s in CI when `mollie_test_secret_key`
  is absent — so all 7 are effectively no-ops in CI. Several DB-integration tests
  also `skipTest` when the site lacks a suitable Bank Account / submitted Sales
  Invoice (`test_mollie_payment_db_integration.py`, `test_mollie_payment_processing.py`,
  `test_order_payment_processor_integration.py`).

- **`test_payment_context_resolver.py` is the weak spot (7 of 14 = OTHER).** Six
  methods set up genuine EDGE scenarios (malformed metadata, invalid-JSON
  description, `None` payment data, empty metadata, nonexistent target) but contain
  NO assertions — only comments like "The key is that it doesn't crash" /
  "ready for when validation is added". `test_context_validation` builds invalid
  contexts and asserts nothing. `test_payment_context_creation` is a tautological
  dataclass attribute round-trip. These inflate coverage without pinning behavior.

- **`test_payment_entry.py` is a debug script, not a test (1 method = OTHER).**
  Module-level `test_payment_entry_creation()` (no class, no assertions) prints to
  stdout, wraps everything in try/except returning bool, and depends on HARDCODED
  production records (`Assoc-Dnt-2025-00752`, a real `tr_...` id) and a hardcoded
  `webhook.user@veganisme.org`. It will not exercise anything on a clean test site
  and should be deleted or rewritten.

- **`test_mollie_sync_unit.py` — 2 assertion-free smoke tests:**
  `test_cancel_from_active_logs_without_email` and `test_reactivation_branch` just
  call `_handle_subscription_status_change` and assert nothing beyond "must not
  raise". Real branch is exercised but the outcome is unverified.

- **Mock-into-tautology watch (mostly benign):** `test_mollie_payments_debug.py`'s
  `test_get_balance_info_delegates` (flagged OTHER) is pure pass-through — mock
  returns a value, test asserts the same value back, no coercion logic. The sibling
  balance-endpoint tests are fine (they assert real int/bool/date coercion). In
  `test_payment_processors.py`, `TestMembershipPaymentProcessor.test_process_successful_payment`
  mocks the factory and asserts `hasattr(member, "payment_history")` (always true) —
  weak but classified HAPPY on its stronger `result.success` assertion.

- **Strong regression-guard density:** many EDGE/UNHAPPY tests explicitly pin
  fixed bugs (docstrings call them out): `add_hours`→`add_to_date` ImportError,
  `RetryConfig` AttributeError in self-test, cache-bytes JSON counter deser,
  `email_ids` child-table AttributeError, `custom_member` phantom column, UTC
  signature-date, MolliePaymentError/MollieWebhookError isinstance ordering. These
  are meaningful, not padding.

No missing or zero-method files among the 22 (smallest real content is
`test_payment_entry.py` with its single OTHER debug function).
