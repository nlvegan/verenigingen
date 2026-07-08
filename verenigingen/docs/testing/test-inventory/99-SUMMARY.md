# Services-Layer Test Suite Inventory — Consolidated Summary

> **Note:** This summary's prose covers Phases 1–2 (services layers, 5,295 methods). Since it
> was written, Phases 1b (infra), 1c (security), 3 (tests/payment + backend/components), 4
> (member/portal/chapter/integration), 5 (e_boekhouden), 6 (report/unit/donor/api), 7
> (backend/unit/api+validation+integration) and 8 (co-located doctype controllers +
> mijnrood_sync) were added — **grand total now 1,132 files · 20,180 methods**
> (Happy 41.0% / Unhappy 16.7% / Edge 35.5% / Other 6.8%). Only bucket C (~130 `tests/`
> subtree files) remains. See `00-TRACKER.md` for the current board and `HANDOFF.md` for
> the full picture, gap-filling targets, and how to resume.

Scope audited: **services layers** of the main app (`verenigingen/services/*` and
their tests in `tests/services`, `tests/sepa`, `tests/backend/unit/services`,
`tests/integration/services`, `tests/unit/services`) and the **payments app**
(`verenigingen_payments/*` — Mollie, ING Checkout, Ponto, SEPA-XML, shared utils).

18 domains · **305 test files** · **5,295 test methods** classified as
Happy / Unhappy / Edge / Other.

## Type distribution

| Segment | Files | Total | Happy | Unhappy | Edge | Other |
|---------|------:|------:|------:|--------:|-----:|------:|
| Phase 1 — main app services | 205 | 3,540 | 1,555 (44%) | 579 (16%) | 1,193 (34%) | 213 (6%) |
| Phase 2 — payments app | 100 | 1,755 | 713 (41%) | 358 (20%) | 596 (34%) | 88 (5%) |
| **TOTAL** | **305** | **5,295** | **2,268 (43%)** | **937 (18%)** | **1,789 (34%)** | **301 (6%)** |

**Headline: the suite is happy/edge dominant and unhappy-light (18%).** Roughly
2 in 5 tests exercise the nominal path, 1 in 3 walk boundaries/guards, but only
~1 in 6 assert a genuine error/throw/rejection — and even that is unevenly
distributed.

## Cross-cutting findings

### 1. Unhappy-path coverage clusters in validators, thin everywhere else
Negative-path tests concentrate in the guard/validator/permission services
(eligibility checker, invoice-generator branches, payment/batch validation, SEPA
input validation, mandate-api, ING mandate-api). **Core money-path services have
near-zero unhappy tests**: both member fee-change-history suites, payment-history
realdb, billing-date, bank-reconciliation-coverage. Where services return
`False`/`0`/error-dicts instead of raising, the negative surface got counted EDGE
— so the real gap is *asserted failure/rollback behavior* on the persistence path.

### 2. A recurring weak pattern: "returns_operation_result" / "never_throws"
Across `backend/unit/services/*_api.py` and several Mollie/donation files, many
HAPPY tests only assert `"success" in result` or hide real checks behind
`if result["success"]:`, so they pass even when the call fails. The
`test_*_never_throws_exceptions` loops often assert only `assertIsNotNone(result.success)`
(always a bool → cannot fail). High coverage, low regression-catching power.

### 3. ~301 OTHER tests — the concrete weak/dead spots to triage first
- **Debug scripts masquerading as tests** (module-level `test_*()`, print+try/except→bool, hit real API / hardcoded prod records, zero asserts): `tests/services/test_donation_refactoring_integration.py`, `sepa/test_enhanced_sepa_integration.py`, mollie `test_payment_entry.py`, `test_subscription_creation.py`, `test_subscription_fixes.py`, `test_webhook_directly.py`. **Recommend delete/rewrite.**
- **Zero-`test_*` files misfiled as tests**: mollie `test_subscription_persona.py`, `utils/test_helpers.py`, `fixtures/test_factory.py` (factory, expected).
- **Tautologies / can't-fail**: `backend/unit/services/test_approval_unification.py` (17/17 AST-string/`getattr` refactor asserts), `test_payment_context_resolver.py` (7/14 assertion-free "doesn't crash"), `verenigingen_payments/tests/test_api_regression.py` (14/15 `isinstance` OR-exception tolerant; `hasattr(...__name__)` disjunct always true), payment_history `test_determine_payment_status_*` (asserts MagicMock's own attrs), `sepa_audit_log` `assertTrue(True)` placeholder, `sepa_mandate_comprehensive` 5 save-then-assert-nothing placeholders, `test_payment_validation_service.py::test_bic_required_but_missing` (0 assertions).
- **Perf tests with no behavioral assert**: `sepa/test_sepa_performance_regression.py` (8/9 wall-clock thresholds on empty tables — environment-fragile).

### 4. Strongest clusters (high-value, genuinely behavioral)
- **Webhook signature security** (Mollie sweep/live, Ponto RS512-JWKS with real RSA keypair, ING HMAC) — real crypto runs end-to-end, full reject matrix. Best tests in the payments app.
- **Payments shared-utils** (`utils_shared/` backoff, money, sliding_window, xml_helpers) — dependency-free, adversarial, known-vector.
- **Real-DB integration suites**: chapter_management_service, member_approval_service_coverage (IBAN-dedup regression), co-located `services/billing/*`, dd_batch/bank-reconciliation (documented paid_from/paid_to-swap regression guards), ING `test_models.py` / `test_transaction_service.py`.
- **SEPA sequence-type** FRST→RCUR transitions (A10b) — real live-DB PmtInf assertions, though concentrated in the two dedicated files (see gap below).

### 5. Notable specific gaps
- **SEPA FRST/RCUR sequence-type on real collections** is broadly asserted only in the two dedicated files; the mandate domain (A9) has just ONE end-to-end transition test (`test_sepa_mandate_runner::test_mandate_with_usage_history`).
- **Concurrency/lock contention**: member-import advisory locks tested only on the success path, never under contention/timeout.
- **Field-sync failure/rejection paths** (`test_field_sync_integration.py`) untested — configs only inspected, sync never executed to fail.

### 6. Base-class / isolation inconsistency
Main-app service tests mostly sit on `EnhancedTestCase` (real DB) or the
mock-based `FrappeTestCase` pure-unit split — largely intentional. Outliers:
`test_member_lookup_service.py` (lone plain FrappeTestCase hand-rolling Member),
and the **entire Ponto + ING suites use plain `FrappeTestCase`**, not the
project Enhanced/factory base. Several files carry parallel Mock + realdb
siblings (lifecycle service, fee-change history) — intentional but duplicative.

## Audited vs. remaining
**DONE (this pass): all services-layer tests** — main app + payments app (18 domains).
**NOT YET AUDITED** (out of scope "services"; candidates for a Phase 3):
`tests/payment` (170), `tests/e_boekhouden` (87), `tests/backend/components` (75),
`tests/member` (54), `tests/backend/portal` (41), `tests/security` (38),
`tests/chapter` (38), `tests/report` (29), and other non-services trees.

See `00-TRACKER.md` for per-domain status and the `NN-*.md` files for per-file tables.
