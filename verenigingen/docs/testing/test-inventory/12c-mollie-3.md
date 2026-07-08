# Test Inventory — DOMAIN P1c: Mollie payments app, part 3 (webhooks / subscriptions / settlement / refunds)

Read-only classification of every `def test_*` method across 24 assigned files.
Primary type per method: HAPPY (nominal success), UNHAPPY (expects error/throw/reject/
signature-fail), EDGE (empty/null/duplicate/idempotency/concurrency/malformed/retry/
missing-config/fallback), OTHER (smoke/tautology/skipped/perf/debug-no-assert).

Convention notes applied: webhook signature-verification-fail = UNHAPPY; duplicate/replay
delivery + idempotency = EDGE; rate-limit(429)/503-retryable/graceful-not-found = EDGE;
missing-input→None guard = EDGE, but explicit validation-error-logged/throw = UNHAPPY.

## Per-file breakdown

| File | Total | Happy | Unhappy | Edge | Other |
|---|---|---|---|---|---|
| tests/test_payment_service_unit.py | 13 | 8 | 3 | 2 | 0 |
| tests/test_payment_type_router_integration.py | 8 | 5 | 2 | 1 | 0 |
| tests/test_payment_webhook_db_helpers.py | 15 | 6 | 2 | 7 | 0 |
| tests/test_payment_webhook_helpers_unit.py | 40 | 25 | 2 | 13 | 0 |
| tests/test_payment_webhook_sweep.py | 11 | 3 | 5 | 3 | 0 |
| tests/test_refund_chargeback_integration.py | 7 | 2 | 3 | 2 | 0 |
| tests/test_refund_chargeback.py | 7 | 4 | 1 | 1 | 1 |
| tests/test_settlement_bank_transaction_processor_unit.py | 19 | 10 | 5 | 4 | 0 |
| tests/test_settlement_processor_db_integration.py | 3 | 2 | 0 | 1 | 0 |
| tests/test_subscription_creation.py | 1 | 0 | 0 | 0 | 1 |
| tests/test_subscription_fixes.py | 2 | 0 | 0 | 0 | 2 |
| tests/test_subscription_persona.py | 0 | 0 | 0 | 0 | 0 |
| tests/test_subscription_service_list.py | 5 | 3 | 1 | 1 | 0 |
| tests/test_subscription_service_live.py | 8 | 6 | 0 | 2 | 0 |
| tests/test_unified_payment_api_webhook.py | 13 | 3 | 4 | 6 | 0 |
| tests/test_webhook_directly.py | 1 | 0 | 0 | 0 | 1 |
| tests/test_webhook_integration_comprehensive.py | 8 | 0 | 1 | 2 | 5 |
| tests/test_webhooks_api.py | 10 | 6 | 4 | 0 | 0 |
| tests/test_webhook_security_live.py | 12 | 2 | 7 | 2 | 1 |
| tests/test_webhook_wrapper_unified_sweep.py | 8 | 3 | 3 | 2 | 0 |
| tests/test_webhook_wrapper_unified_unit.py | 19 | 7 | 6 | 5 | 1 |
| api/test_payment_webhook_coverage.py | 11 | 7 | 0 | 4 | 0 |
| services/shared/test_payment_entry_factory_coverage.py | 22 | 13 | 1 | 8 | 0 |
| utils/test_helpers.py | 2 | 0 | 0 | 0 | 2 |
| **DOMAIN TOTALS** | **245** | **115** | **50** | **66** | **14** |

## Observations

- **Webhook-signature security is thoroughly covered and non-tautological.** Three
  files pin genuine HMAC-SHA256 accept/reject with real digests, no mock of the
  comparison: `test_payment_webhook_sweep.py` (strict `_validate_webhook_signature`,
  5 UNHAPPY rejects: missing/no-secret/wrong-secret/tampered/garbage),
  `test_webhook_security_live.py` (live `verify_mollie_webhook_signature` — tampered
  body, wrong secret, unsigned-accept, test-signature-bypass-only-in-test-mode, plus a
  constant-time timing-attack measurement classed OTHER), and the strict-path subset in
  `test_payment_webhook_db_helpers.py`. These are the strongest tests in the domain.

- **Live / skip-gated files** (real Mollie test API, skip when no key configured):
  `test_subscription_service_live.py` (8, skips via `ensure_mollie_test_credentials`)
  and `test_webhook_security_live.py` (12 — "live" in intent but runs on any site by
  toggling `allow_mollie_test_mode`, so not actually skipped). `test_refund_chargeback*.py`
  and `test_settlement_*` use fakes/`object.__new__`, not the live API.

- **Four files are NOT real automated tests (14 of the 14 OTHER methods concentrate
  here)**: `test_subscription_creation.py`, `test_subscription_fixes.py`,
  `test_webhook_directly.py` are module-level debug scripts (print/traceback, hit real
  Mollie API, zero assertions). `utils/test_helpers.py` (2 `test_*`) and
  `test_subscription_persona.py` (0 `test_*`) are whitelisted dev-utility/persona modules
  misfiled under `test_*.py`. `test_webhook_integration_comprehensive.py` adds 3
  `@unittest.skip`'d obsolete workflow tests + 2 perf-only tests.

- **Mock-into-tautology risk is LOW in the `*_unit`/`*_sweep`/`*_coverage` files.** They
  consistently stub only the SDK / GL-writer / idempotency boundary via `object.__new__`
  + `SimpleNamespace`/fakes and run real service logic (real classifier, real Settlement
  model math, real Donation child-table Link validation on save). The one weak spot is
  `test_webhook_wrapper_unified_unit.py::test_get_unified_webhook_service_is_singleton`
  (OTHER, `assertIs` identity smoke). `test_refund_chargeback.py` mocks `MolliePaymentService`
  legitimately (external), and its `test_refund_performance_baselines` (OTHER) asserts only
  `assertQueryCount`/timing, not correctness.

- **Idempotency / duplicate-replay is a first-class concern across the domain** (large
  EDGE share, 66/245). Every refund/reversal/settlement/payment-history path has an
  explicit duplicate-delivery or already-processed test
  (`test_payment_history_idempotency`, `test_batch_skips_history_row_that_already_exists`,
  `test_already_processed`, `test_already_processed_reversal_is_idempotent`, etc.).

- **HTTP status-mapping contract is well-pinned** in `test_unified_payment_api_webhook.py`
  and `test_webhooks_api.py`: 429 rate-limit (EDGE), 503 retryable (EDGE), 400 known-error,
  403 security-error, 500 unexpected+generic-message-no-leak (UNHAPPY). Two named
  regression guards worth noting: chargeback wrong-class-name ImportError
  (`test_service_result_returned`) and the `webhook_url` AttributeError health-check fix.

## Missing / zero-method files
- `tests/test_subscription_persona.py` — **0 `def test_*` methods.** It is an interactive
  test-persona helper (`create_emma_subscription_persona`, `create_subscription_for_emma`,
  etc., all `@frappe.whitelist`/`@development_only_api`), not a runnable test module despite
  the `test_` filename.
- `utils/test_helpers.py` — only 2 of its 7 functions match `test_*`
  (`test_mollie_subscription_creation`, `test_mollie_webhook_simulation`); both are
  whitelisted dev utilities with `msgprint`/no assertions (classed OTHER). Not a TestCase.
