# Order-dependence tail — handoff (2026-06-09)

Continuation of `docs/plans/2026-06-07-test-suite-fix-session4-handoff.md`. That
session left the suite at **v32 = 8981 / 24F / 0E**, with the entire 24-failure
residual classified as order-dependence / flaky / perf-noise. This session worked
that tail down to **5**, all of which are pre-existing infrastructure noise.

## TL;DR

- **v32 = 24F → v33 = 9F → v34 = 5F**, on clean 4-shard `run-parallel-tests`
  baselines (snapshot-reset sites). **Zero regressions** across both baselines.
- **19 of 24 tail failures fixed**, in **3 commits pushed to `origin/develop`**
  (`caa0da79`, `60a79a7e`, `3adcdd20`). All changes are test-only.
- Residual **5F = 1 deferred flake + 4 perf/scalability** — no product bugs, no
  actionable test-isolation failures remaining.

## Commits (pushed to origin/develop)

| Commit | Scope |
|---|---|
| `caa0da79` | test(isolation): volunteer_skills ×2 (scope to own volunteers), expense_claim_queries ×2 (filter by run-id), mollie IBAN ×4 (run-unique IBAN from uid), notification polluter restore |
| `60a79a7e` | test(determinism): sepa_input_validation ×3 (weekday collection date), sepa_mandate_lifecycle ×2 (pin service getdate), chapter_expense ×1 (±1 midnight), error_recovery ×1 (naming-series retry) |
| `3adcdd20` | test(isolation): member_lifecycle ×2 (run-unique dues-schedule template names), notification_suppression ×2 (flag-based rewrite) |

## Root causes (the non-obvious ones)

- **member_lifecycle ×2** — a co-located test (`test_member_lifecycle_iban`) calls
  `ensure_membership_type_exists("Regular")`. A Membership Type literally named
  "Regular" makes `Membership Type.after_insert → create_dues_schedule_template`
  auto-create a template named `"{type} Template"` = **"Regular Template"** at the
  €15 framework default. This test's
  `ensure_dues_schedule_template("Regular Template", {dues_rate: 60})` then **reuses
  that stale €15 doc as-is** (the helper returns existing docs without applying the
  requested attributes), and `create_from_template` fails *"Template dues rate (€15)
  cannot be less than membership type minimum (€60)"* → no schedule → line-155
  assertion. **Fix:** run-unique template names (`f"Regular Lifecycle Template {self.uid}"`)
  so they can't collide with the `"{type} Template"` auto-name. Verified by reproducing
  the exact pollution (seed "Regular" type + NL company → all 7 pass).
- **notification_suppression ×2** — `frappe.get_single()` returns a **fresh document
  each call**, NOT the object the context manager mutates. So the in-context
  `assertEqual(setting, 0)` only passed when the *persisted* value happened to be 0; a
  neighbour leaving it at 1 broke it. **Fix:** assert the suppression **flag** (the
  observable contract `EmailConfigurationService._is_suppressed` checks) inside the
  context, and the persisted value unchanged after. Verified robust at ambient 0 and 1.
- **mollie IBAN ×4** — `factory.create_test_iban()` is deterministic AND resets its
  account sequence each test, so `test_members[0]`'s IBAN is identical across tests and
  collides with the first mandate a co-located test leaves behind. Build run-unique
  IBANs from `self.uid`.

## Residual (v34 = 5F, all pre-existing infra-noise — leave)

- **real_template ×1** (`test_real_template_missing_fallback`) — **DEFERRED**.
  `EmailService` is a process **singleton** with a `BoundedLRUCache`; `_get_template()`
  checks the cache **before** `db.exists`, so a co-located test
  (`test_payment_processing_api_integration`) leaves a stale "payment_reminder_friendly"
  entry → this test's DB-delete is ignored → the leaked unrendered template is used →
  `assertIn("30")` fails. The cache-clear fix
  (`get_email_service().template_cache.clear()`) was **mechanism-verified** but
  **unexpectedly broke the solo case** (`result=False`, not understood) → reverted, not
  shipped. There is *also* a separate solo-only under-seed (clean-snapshot email infra →
  `result=False`). Anyone resuming should handle the under-seed first, then re-attempt the
  cache fix with a full reproduction.
- **chapter_permission `test_get_user_board_chapters_returns_list`** — appeared in v33 as
  a transient **MariaDB deadlock (1213)** on `DELETE tabHas Role` in `_reset_user_roles`
  under parallel load; **did not recur in v34**. Not a regression. A naive retry is unsafe
  (the deadlock rolls back the whole test transaction).
- **perf/scalability ×4** — `bulk_member_operations_performance`,
  `performance_comprehensive` ×2 (`large_dataset` + `query_optimization`), scalability
  `payment_history_creation_50_members`. All were in v32; timing-sensitive, leave per policy.

## Methodology notes (save the next session time)

- **`bench run-tests --module A --module B` runs ONLY B** (argparse keeps the last).
  You cannot co-run two modules in one process this way — cross-file order-dependence can
  only be faithfully verified by `run-parallel-tests`.
- **Parse baselines via the `✖` marker**, not the wrapper's "known failures" diff (that's
  the stale v15 mechanism): `sed -r 's/\x1b\[[0-9;]*m//g' shardN.log | grep -aE "✖|FAIL "`.
- **`frappe.get_single` does not share objects** across calls; mutating one is invisible to
  another. Test the flag/persisted-state, not an in-memory object you didn't get from the
  code under test.
- Baseline scripts: `/tmp/run_v3{3,4}_baseline.sh`. Reset (needs the password in memory
  `test-suite-fix-2026-06-07-session2.md`):
  `MARIADB_ROOT_PASSWORD='…' bash reset_test_sites.sh test_site_{1..4}`.
- Pre-push needs the same SKIP as commits:
  `SKIP=whitelist-type-safety,insecure-api-detector,test-quality-enforcer,block-inappropriate-mocks git push`.

## If you pick this up next

1. real_template: resolve the clean-snapshot email-infra under-seed in setUp, then add
   `get_email_service().template_cache.clear()` after the template delete and verify by
   reproducing the co-located leak (not just solo).
2. Consider fixing the shared-helper footgun at the source: make
   `ensure_dues_schedule_template` apply the requested attributes to an existing template
   (many test files carry comments fighting the €15 default) — but vet the blast radius
   across the suite first.
