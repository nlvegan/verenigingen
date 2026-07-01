# Mollie Core Cluster — Coverage Sweep + Dead-Code Purge + 13 Bug Fixes — Handoff

**Date:** 2026-06-17
**Branch:** `develop`
**Status:** 3 commits **LOCAL / UNPUSHED** (not pushed — user did not ask)

## TL;DR

Codecov "where next" assessment pointed at `verenigingen/verenigingen_payments/mollie/`
— the biggest, lowest-covered directory (33.5%, ~5,721 missed lines, least
recently touched). Did the proven playbook: **triage dead-vs-live → delete dead
→ multi-agent coverage sweep → skeptical review → fix bugs → commit.**

| Commit | What | Net |
|---|---|---|
| `8f0c176d` | refactor(mollie): remove 4 dead modules + 1 false-confidence test | −1,908 LOC |
| `25c58387` | refactor(mollie): remove 3 more dead modules | −694 LOC |
| `15af342a` | test(mollie): cover live payment cluster + fix 13 production bugs | +5,184 / −36 (29 files) |

Net: **−2,602 LOC dead code removed, ~256 new tests across 20 files, 13 production bugs fixed.**

Coverage trend across recent sweeps: 50.85 → 55.18%.

## Context at session start

- Overall codecov 55.18% (full 9-session report on develop HEAD `3eb8e59e`).
- **Partial-upload gotcha:** HEAD showed 43–47% until all 9 sessions uploaded —
  always check `totals.sessions == 9` before trusting a % (via
  `api.codecov.io/api/v2/github/nlvegan/repos/verenigingen/commits/`).
- **Server Tests CI fully RED** (all 8 shards) since `4f4022a55b` (06-15). Confirmed
  this is the **known order-dependent flaky tail, NOT a regression** — every recent
  run incl. `ab5854e9` had all shards red. Durable fix = test isolation program,
  not more baselining. Did not touch this.
- Concurrent eBoekhouden session active (committed `a7935719`, `3c122739`
  interleaved). Kept its files out of all my commits via explicit pathspec.

## Phase 1 — Dead-code triage (commits `8f0c176d`, `25c58387`)

All evidence-confirmed (grep exact class/endpoint names + check JS/JSON/workspace
wiring; whitelisted endpoints checked for real callers, not just the
auto-generated `critical_operation_rule.json` registry which is circular):

| Deleted | Why dead |
|---|---|
| `services/generic_webhook_service.py` | Dead duplicate of the live `unified_payment_api` webhook path (which does its own signature validation at L341/442). Only consumer was `tests/test_webhook_security.py` (8 "security" tests) → asserted against dead code = **false security assurance**. |
| `tests/test_webhook_security.py` | Tested the above dead service. Its scenarios were **ported onto the live path** (see `tests/test_webhook_security_live.py`). |
| `api/subscription_sync.py` | 3 orphan `@frappe.whitelist()` endpoints, zero callers. Superseded by live `services/mollie_subscription_sync_service.py` (PATCH sync via `events/amendment_events.py`). |
| `api/dashboard.py` | 3 whitelist endpoints; import commented out in `api/__init__.py`; live dashboards live in `verenigingen_payments/dashboards/`. |
| `utils/validation.py` | `MollieValidator` is a dead dup; the live `MollieValidator` is an alias of `MollieDataValidator` in `verenigingen_payments/utils/mollie_data_validator.py`. |
| `utils/transaction_manager.py` | `MollieTransactionManager`/`MollieOperationManager`, zero refs. |
| `tests/interactive_subscription_test.py` | Print-based manual persona script, no TestCase/asserts. |
| `tests/page_test_mollie.py` | Diagnostic page module, not wired to any route. |

Package imports verified clean after each deletion batch (bench console import smoke test).

## Phase 2 — Coverage sweep (commit `15af342a`)

5 parallel agents on distinct test sites (test_site_1..5), each a coherent slice,
no commit / no `--coverage`. ~256 tests / 20 files. Credential-free seam:
`EnhancedTestCase` + bypass `MollieClient.__init__` via `object.__new__()` + stub
the Mollie SDK boundary with `types.SimpleNamespace` (canonical example:
`tests/test_dues_payment_processor_integration.py`).

### 13 production bugs fixed (all verified by me, all adjudicated MEANINGFUL by a skeptical-code-reviewer)

**Renamed-class root cause (4 of the fixes):** the class was renamed
`WebhookWrapperServiceUnified` → `UnifiedWebhookWrapperService` and its method
`process_webhook` → `process_payment_webhook(payment_id, webhook_data)`, leaving
dangling references that **crashed at runtime**:
1. `api/unified_payment_api.handle_chargeback_webhook` — wrong class + arity →
   every chargeback webhook ImportError'd, swallowed, silently 500'd → **no
   chargeback was ever recorded**.
2. `utils/error_recovery._attempt_automatic_recovery` — same defect → the
   automatic webhook-recovery path crashed. (Added a regression test for it.)
3. `mollie/__init__.py` + `services/__init__.py` — imported the old name in a
   **combined try/except**, so on ImportError the `except` rebound ALL names
   (incl. the successfully-imported `PaymentService` / `CompletePaymentService`)
   to `None` → the package exported `None` for three services. Repointed +
   backward-compat alias.

**Other fixes:**
4. `services/shared/payment_entry_factory` — queried/wrote the Customer↔Member
   link as `custom_member` (non-existent; real field is `member`) at 4 sites →
   OperationalError swallowed → customer creation returned None → **membership
   Payment Entries were never created for any member lacking a pre-existing
   Customer**. Also set the mandatory `posting_date` explicitly.
5. `services/payment_processors` — `validate_iban()` returns a `bool` but the
   donation path called `.get("valid")` on it → AttributeError swallowed →
   **consumer IBAN Bank Accounts (for later MT940 matching) never linked**.
6. `api/webhooks.webhook_health_check` — read non-existent `webhook_url` field →
   AttributeError → **always reported "unhealthy"**. Now reads per-mode
   `testing_/live_webhook_url`.
7. `utils/error_recovery._classify_error_severity` — tested `MollieWebhookError`
   before its subclass `MolliePaymentError` → MEDIUM branch unreachable. Reordered.
8. `api/monitoring_api._get_recovery_performance_metrics` — indexed cache values
   as dicts but the producer stores `json.dumps` strings → TypeError → the
   recovery performance panel silently returned `{}` whenever any recovery
   activity existed. Added `_read_recovery_counter` decode.
9. `api/monitoring_api.test_error_recovery` — referenced `error_recovery.RetryConfig`
   (not an instance attr) → the retry self-test always reported failure.
10. `api/sync.bulk_sync_recent_payments` — used `frappe.utils.add_hours`, which
    **does not exist** → ImportError crashed the endpoint on every call. Now uses
    `add_to_date(now_datetime(), hours=-hours)`.

### Dead-code candidates flagged by agents (NOT yet actioned — for a future pass)
- `services/payment_context_resolver.PaymentContextResolver` class — test-only,
  no prod caller (the `PaymentContext` *container* is live; the *resolver class*
  is not).
- `api/webhooks.webhook_health_check` — zero callers (kept; whitelisted GET, and
  it was broken — now fixed + covered).
- `api/sync.py` (whole module) — not imported by `api/__init__` (commented out),
  no JS/workspace/scheduler wiring; reachable only by full dotted HTTP path.
  Needs a product keep/remove decision.
- `services/payment_entry_factory.py` shim — its `get_appropriate_cost_center_for_context()`
  and `_LegacyPaymentEntryFactory` (self-labeled ARCHIVED) are dead; file not
  deletable yet because `payment_processors.py` still imports its deprecated
  `PaymentEntryFactory` subclass (one-line change to import from `shared` would
  free it).
- **Latent (not a crash):** `Member Payment History` child table has no
  `mollie_payment_id`/`payment_reference` fields, so the membership processors
  write those keys but they silently drop → `MembershipPaymentProcessor.check_idempotency`'s
  history match on those fields can never hit. Worth a follow-up.

## Verification done

- Each of the 17 new test modules run green individually on test_site_1; combined
  run confirmed (the one initial failure — `test_dues_payment_processor_creation_unit`
  — was a cross-site data dependence, now fixed; see gotcha below).
- All 13 prod fixes factually verified (class names, field existence, return
  types, exception MRO, `add_hours` absence) via grep + bench console.
- Pre-existing mollie tests that touch changed code re-run green
  (`test_failed_payment_processing`, `test_webhook_wrapper_unified_unit`,
  `test_payment_processors`).
- Package import smoke test: `UnifiedWebhookWrapperService` resolves, alias works,
  `PaymentService`/`CompletePaymentService` no longer `None`.
- `ruff check` clean on all touched prod files; `black` clean on staged files.

## Gotchas learned this session

- **`black -q <dir>` reformats committed files too.** A broad `black mollie/` run
  churned 8 pre-existing files (import reorder / line-wrap). Revert with
  `git checkout`, then format ONLY staged files
  (`git diff --cached --name-only | grep '\.py$' | xargs black -q`).
- **Pre-commit `black` hook reformats a staged file mid-commit → abort.** Fix:
  pre-format staged files, `git add` them, retry the commit.
- **`bench run-tests --module A --module B` only runs the LAST `--module`.** Loop
  one module per invocation to run several.
- **Dues-creation tests need both a Mollie Clearing Account GL AND a linked
  `Bank Account` doc** on the EUR test company. `bank_transaction_creator` looks
  up `Bank Account` by `{"account": clearing}`. test_site_3 had them from a prior
  session; clean sites (and CI) don't → `setUpClass` must create both idempotently
  (reuse `mollie/tests/fixtures/payment_entry_fixtures.ensure_mollie_bank_gl_account`).
- **Codecov partial-upload:** check `totals.sessions == 9` before trusting a %.

## Next biggest gaps (by missed lines, from the 9-session report)

1. `e_boekhouden/utils` — 5,672 miss @ 48.8% (heavily worked already; harder tail;
   dead candidates: `eboekhouden_enhanced_migration.py` 0%, `stock_account_handler.py` 0%;
   `consolidated/*` very low).
2. `verenigingen/doctype` — 5,021 miss @ 64.9% (large but already 2/3 covered).
3. `verenigingen_payments/utils` — 3,106 miss @ 68.6%.
4. `templates/pages` — 3,063 miss @ 43.8% (templates, harder to test meaningfully).

## To push

The 3 Mollie commits (`8f0c176d`, `25c58387`, `15af342a`) are local on `develop`,
interleaved with the concurrent eBoekhouden session's commits (`a7935719`,
`3c122739`). Pre-push will run the slower validators; expect them clean (no
`ignore_permissions`/`set_user` violations in test bodies — agents used fixtures
helpers). CI Server Tests will be red regardless (pre-existing flaky tail).
