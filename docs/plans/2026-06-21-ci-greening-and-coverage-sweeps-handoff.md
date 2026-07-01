# Handoff — CI greening + eBoekhouden-migration + SEPA coverage (2026-06-21)

## TL;DR
One long session on `develop`, three sequential efforts. **All my work is PUSHED to
origin/develop (HEAD of my work = `d9350b68`).** A **concurrent session** was running
the whole time (mijnrood-sync + utils/security coverage) — its commits are interleaved
on the same branch; treat its files as out-of-scope.

1. **Greened the red Server Tests gate** (shards 1/3/4/11 order-dependence + a shard-6 flake).
2. **Covered the E-Boekhouden Migration controller** (24.43% → 43.89%) + fixed a latent crash.
3. **SEPA coverage sweep, 3 parallel agents** (~127 tests) + **6 real production bug fixes**.

## ⚠️ START HERE (open items)
1. **Gate run `27916510137` (on `d9350b68`) was in progress at handoff.** It bundles my SEPA
   work with the concurrent session's commits. **Early signal: the only real failures are the
   concurrent session's `verenigingen.mijnrood_sync.*` tests** — `TestSyncLock.test_acquire_then_second_acquire_blocked`,
   `test_run_sync_skips_when_lock_already_held`, `test_lock_stores_run_id`,
   `test_mijnrood_sync_settings_remote.*` (a shared-Redis-lock order-dependence in *their* code,
   not mine). **Verify**: `gh run view 27916510137` → confirm any failures are mijnrood/security
   only; my SEPA + eBoekhouden tests should be green. **Do NOT fix the mijnrood tests — that's the
   concurrent session's domain.**
2. **Concurrent session is active.** At handoff local HEAD was `811ad2cd` (their newer commit, UNPUSHED)
   stacked on my pushed `d9350b68`. When committing, ALWAYS `git commit -F msg -- <explicit paths>`
   (NOT `git add -A`, NOT `git add` then `git commit` — the index gets polluted by the other session
   mid-commit; I hit this and recovered with `git reset` + pathspec commit). Pushing the shared branch
   publishes their commits too (linear ancestry) — coordinate / expect it.
3. **Flagged dead code (NOT fixed — deletion candidates for a future pass):**
   - `BatchProcessingService.validate_sepa_sequence_types` + `_get_mandate_sequence_types_bulk`
     (read phantom SEPA Mandate fields → swallow real `1054`/AttributeError; only reachable via
     `BusinessLogicOrchestrationService`, which has NO live importers → dead-calling-dead).
   - module-level `update_membership_payment_status` (direct_debit_batch.py) — phantom Membership
     fields, no caller.
   - `e_boekhouden_migration.migrate_chart_of_accounts` ~L458-459: `created_count` set from the
     cleared/deleted count → success message likely UNDER-reports accounts created (API-gated, flagged only).

---

## PART 1 — Server Tests gate greening (PUSHED, GATE WENT GREEN)
The gate was red (deferred from the prior handoff) on shards **1/3/4/11**, all order-dependence
(pass in isolation, fail in the full 12-shard run on shared MariaDB+redis). Diagnosed from CI job
logs (`gh api repos/nlvegan/verenigingen/actions/jobs/<id>/logs`), fixed via 4 parallel agents.
- `acc17f3c` — **prod bug**: `frappe.log_error(title, msg)` put the long detail into the Error Log
  `method` field (Data, max 140) → `CharacterLengthExceededError` crashed log-and-swallow paths. Use kwargs.
- `c5f05cc8` — greened 1/3/4/11: cache round-trips via `isolate_cache_keys` (sibling-shard redis FLUSH);
  `set_single_value` not Single `.save()` (MandatoryError); `account_type` filter; v16 role-profile drift.
- `c26657d1` — shard-11 follow-up: CI company has no `account_type=="Expense Account"` leaf → get-or-create it.
- `b699e900` — shard-6 flake: duplicate-detection tests' `uuid4().hex` emails got mangled by the factory
  uniquifier ~0.76% of the time → use `set_shared_email` (db.set_value) for deterministic shared emails.
Gate confirmed GREEN at `b699e900` (run 27910944669, all 12 shards) — see memory
`server-tests-shard-greening-2026-06-21`.

## PART 2 — E-Boekhouden Migration controller coverage (PUSHED)
Biggest prod gap: `e_boekhouden/doctype/e_boekhouden_migration/e_boekhouden_migration.py`
(24.43%, 668 miss). Probe agent mapped reachability → 3 parallel writers → skeptical review.
Most of the gap is API-REQUIRED (can't cover without mocking the REST client; enforcer forbids) —
covered the ~150-200 reclaimable PURE/DB-only + guard branches.
- `8aaec1d0` — **prod bug**: migration failure handlers wrote a phantom `error_message` field
  (doctype has `error_log`) → `OperationalError 1054` crashed the error handler itself. → `error_log`.
- `40f011dc` — 38 real-DB tests (accounts/CoA helpers, cost-center + service-init + log_error, endpoint
  guards + delete-cascade).
- `526a2bda` — fixed an FY order-dependence the first gate run exposed in the cascade test: a *submitted*
  JE against an arbitrary `get_value("Company",{})` company that lacked a current FY → use a DRAFT JE
  (the cascade lookup has no docstatus filter; a draft skips make_gl_entries/FY).
File 24.43% → **43.89%**; overall develop **65.32% → 65.48%**. Gate green at `526a2bda` (run 27910944669).
See memory `eboekhouden-migration-controller-coverage-2026-06-21`.

## PART 3 — SEPA coverage sweep (PUSHED) — "put 3 agents on the SEPA code"
`verenigingen_payments` was 73.9%. Excluded the KEEP-as-is Week-4 monitoring cluster
(sepa_memory_optimizer/alerting/zabbix — Foppe: keep, not in prod). 3 parallel writer agents +
skeptical review + central commit.
- `04c4a927` — cluster 1 (DD batch pipeline, 36 tests) + cluster 2 (bank reconciliation, 20 tests).
- `2b003d82` — cluster 3 (mandate lifecycle/retry/rollback + the 0%-covered `sepa_mandate_issues`
  report, 51 tests) **+ 5 real prod-bug fixes**:
  1. `SEPAMandateMetricsCollector.reset_metrics()` **self-deadlock** — held the non-reentrant
     `_metrics_lock` then called `get_metrics_summary()` (re-acquires same lock) → permanent hang for
     ANY caller. Extracted lock-free `_build_metrics_summary()`. (Caused a deterministic test HANG;
     LESSON: a same-point hang across multiple sites is a real deadlock, not contention.)
  2. Phantom `processing_started`/`processing_completed` fields (sepa_retry_batch.json) → on_submit
     "Unknown column" crashed EVERY batch submit. Added.
  3. Missing `allow_on_submit` on on_submit-mutated fields (both retry doctypes) → "Cannot Update After
     Submit". Added; + the `Partially Completed` status option the controller already sets.
  4. `calculate_totals` ran SQL during validate() (before children persisted) → counted stale Pending.
     Now aggregates in-memory `self.operations`.
  5. `on_cancel` plain assignment dropped by Frappe's cancel flow → use `db_set`.
- `a404215f` — **error-log-guard hardening (per Foppe's question "did you check error log entries?")**:
  ran all 3 modules under `VERENIGINGEN_FAIL_ON_ERROR_LOG=1`; the dead methods swallow real
  `1054`/AttributeError and `process_batch` logs an intentional guard — the tests now `expectErrorLog(...)`
  those, and the known benign "Fiscal Year Auto-Creation Error" artifact is acknowledged at base setUp.
  All 3 modules now pass clean under the flag.
See memory `sepa-coverage-sweep-2026-06-21`.

---

## KEY PROCESS LEARNINGS (reuse)
- **Always run a coverage sweep's new tests under `VERENIGINGEN_FAIL_ON_ERROR_LOG=1` before declaring
  done.** Green tests hide swallowed prod errors. It surfaced the dead-code 1054 swallow here.
- **A deterministic same-point hang across multiple test sites = a real deadlock** (here a re-entrant
  non-reentrant `threading.Lock`), NOT contention. Bisect with a `signal.alarm` probe in console.
- **Don't submit financial docs against `get_value("Company",{})`** — arbitrary company often lacks a
  current FY on the shared CI DB → FiscalYearError (passes alone, fails in full shard). Use a DRAFT doc
  or the dedicated `tests/support/sepa_test_company` / `get_eur_test_company` FY fixture. Never append
  rows to a shared `_Test Fiscal Year`.
- **Most of a controller's gap can be API-REQUIRED** (out of scope — enforcer forbids mocking business
  logic). Be honest about the reclaimable number; cover PURE/DB-only + reachable guard branches only.
- **Shared working tree + concurrent session**: `git commit -F msg -- <explicit paths>` is race-safe;
  the index gets polluted between `git add` and `git commit`. `bench run-tests` site startup hangs under
  contention (no-output timeout = retry on another site, test_site_4/5); always wrap module runs in
  `timeout`; use `--case <Class>` / `--test <method>` for fast isolation (no `--verbose`).
- **Codecov read (no token):** `api.codecov.io/api/v2/github/nlvegan/repos/verenigingen/...` (totals +
  per-file `report/`).

## STATE AT HANDOFF
- origin/develop = `d9350b68` (all my work pushed). Local HEAD `811ad2cd` = concurrent session's unpushed commit.
- Gate run `27916510137` in progress (verify it; expected red ONLY on concurrent-session mijnrood tests).
- Coverage: verenigingen_payments SEPA modules materially up; overall develop ~65.5%.
- Task list (this session) all complete except verifying the final gate run.
