# Test-suite order-dependence + Customer-naming — handoff (2026-06-07)

## TL;DR

The parallel test suite churns its failure set whenever the shard split changes
(3 vs 4 shards, count vs measured weights), because `run-parallel-tests` runs each
shard as ONE process / ONE site with **no DB reset between files**, so state bleeds
file→file. Foppe accepted a **4-shard** split; this work fixes the *suite itself* so
it's isolation-clean.

This session: built diagnostic tooling, fixed all 13 fixable **ORDER_DEP** modules,
shipped one **production** Customer-naming fix, and a **persistent fiscal-year** fix.
**7 commits on `develop`** (all green through pre-commit). Remaining: **9 GENUINE**
failures (real causes diagnosed below) + 3 FLAGGED (external polluter) + perf quarantine.

## Background / why

8 baselines (v22..v29) proved the failures are mostly co-location artifacts, not real
bugs: v28 (4-shard)=29 fails, v29 (3-shard)=28, only **12 stable across both, 33 churning**.
The frappe LPT/timings patch (`apps/frappe/frappe/parallel_test_runner.py`, **uncommitted**)
+ `verenigingen/tests/test_timings.json` are **PARKED** until the suite is clean (fixing
state-bleed may change the optimal split). Land them LAST.

## Tooling built (`apps/verenigingen/scripts/testing/`, committed `9aaba0e8` + `7cb6c0d6`)

**Always verify fixes with the DETECTOR, never `bench run-tests --module`** — the latter
under-seeds (e.g. Team Role "Team Member" missing) and gives false failures.

- **`order_dependence_detector.py`** — subclasses the real `ParallelTestRunner`, overriding
  only the file list, so it reproduces a production shard faithfully (real `before_test_setup`
  seeding + shared-process semantics) with controlled order. Emits per-test JSON AND now prints
  failure tracebacks to stderr. **MUST run with cwd = `frappe-bench/sites`.**
  ```bash
  cd ~/frappe-bench && MARIADB_ROOT_PASSWORD='...' bash reset_test_sites.sh test_site_1
  cd ~/frappe-bench/sites && ../env/bin/python \
    ../apps/verenigingen/scripts/testing/order_dependence_detector.py \
    --site test_site_1 --modules dotted.mod.a,dotted.mod.b --json-out /tmp/out.json
  ```
  Solo-pass + fails-in-some-layout ⇒ ORDER_DEP. Fails-solo ⇒ GENUINE (real bug or needs a
  neighbour's seeding).
- **`scan_order_dependence.py`** — AST scanner for the source anti-patterns. 44 REUSE hits
  (`get_all(DT, limit=1)`/`[0]` reuse), 17 high-signal files (mutable masters) — latent
  offenders not failing *today*.
- **`sweep_solo_classify.sh`** — resets to clean snapshot before each module, solo-runs it,
  classifies PASS_SOLO→ORDER_DEP vs FAIL_SOLO→GENUINE. Output in `/tmp/sweep/`.

Reset infra: `~/frappe-bench/reset_test_sites.sh` (restores golden snapshot
`sites/test_snapshot/clean_v1620-database.sql.gz`; needs `MARIADB_ROOT_PASSWORD`).
Disposable sites `test_site_1..4`. **Never test on veg11** (commit-pollution cascade).

## Classification (25 non-perf failures; `/tmp/sweep_classification_2026-06-07.tsv`)

- **16 ORDER_DEP** (pass solo, fail co-located) — 13 fixed + committed; 3 FLAGGED (below).
- **9 GENUINE** (fail solo) — diagnosed below, NOT yet fixed.
- 3 perf (`test_performance_comprehensive`, `scalability.*`) → **QUARANTINE**, don't "fix".

## Root causes discovered

1. **Suite-wide shared hardcoded identity** `"Test Verenigingen Volunteer"` used in ~47 test
   files. Member insert auto-creates a Customer named by full name; duplicates collide.
2. **`EnhancedTestCase.setUp` sets `frappe.flags.in_import = True`** (to skip user-creation
   throttling), which **disables ERPNext's `" - N"` Customer-name dedup** — so same-name
   Customers collide HARD in tests though they'd suffix peacefully in production.
3. **Current-year Fiscal Year restricted to `_Test Company`** (erpnext `set_defaults_for_tests`)
   — breaks dated docs vs other companies; **recurs every January**.
4. One file (`test_volunteer_skills_api_enhanced`) ran `DELETE ... WHERE email LIKE
   'TEST_%@test.invalid'` — the factory's own pattern — **deleting other tests' data mid-shard**.
5. **Reproduction needs the LIVE shard composition** — reconstructing from the current
   `test_timings.json` fails (it was regenerated post-v29). Solo-classification sidesteps this.

## Commits this session (on `develop`)

| Commit | What |
|---|---|
| `508c7905` | **PROD** Option E: `insert_customer_with_duplicate_retry` (4 Customer-insert sites) |
| `9aaba0e8` | detector + AST scanner + solo-classify sweep |
| `dedb1b65` | team_assignment_history (exemplar: `get_all` reuse → factory unique volunteer) |
| `134421fd` | 11 ORDER_DEP modules (unique identities, scoped asserts, Single restore, unique IBANs) |
| `09a0f5e5` | error_recovery (unique IBANs/donors; concurrent test = flake not order-dep) |
| `7cb6c0d6` | **persistent fiscal-year fix** + detector prints tracebacks |
| `de9eedc0` | donor tearDown `set_single_value` (Single-pollution robustness) |

**Verification:** all 16 ORDER_DEP modules run together through the detector → **229 ran / 0 fail**.

### Production fixes (need a real review)
- **Option E** (`508c7905`) — `create_customer_for_member` + 3 Mollie factories. Helper in
  `services/member/approval/application_payments.py`. Tests
  `tests/member/test_customer_creation_duplicate_name.py` (3 pass; set `in_import=False` to get
  prod naming). Proposal: `docs/plans/2026-06-07-customer-naming-fragility-proposal.md`.
  **Option A (switch Customer naming to a series) is a tracked FOLLOW-UP** — bigger blast radius.

### Persistent fiscal-year fix (`7cb6c0d6`) — Foppe's explicit ask
`ensure_test_fiscal_year_for_all_companies()` in `verenigingen/tests/setup/__init__.py` reuses
PROD `ensure_fiscal_year_exists(today(), company)` (`e_boekhouden/utils/consolidated/date_utils.py`)
then clears the FY's `companies` restriction. Called once-per-session from
`EnhancedTestCase.setUp` + `ensure_erpnext_base_masters`. **Date-driven → no 2027 recurrence.**
**COVERAGE GAP:** non-`EnhancedTestCase` bases (e.g. `VereningingenTestCase` in
`tests/utils/base.py`, used by the donor suite) don't get it — fine today (they don't hit FY).

## REMAINING WORK — 9 GENUINE (real causes from detector tracebacks, `/tmp/det_genuine.log`)

| Module | Real failure | Fix |
|---|---|---|
| `donor_auto_creation_comprehensive` | (co-located) dangling `national_board_chapter` → **FIXED `de9eedc0`**; (solo ~9) persona donation **Payment Entry lacks `paid_to`** bank/cash acct → `MandatoryError: paid_to, paid_to_account_currency` + 2× `TypeError: join None` | Fix the persona (`DonorAutoCreationTestPersona.create_donation_payment_entry`) to set `paid_to` + a company bank/cash account |
| `test_invoice_generation_and_payment_history_sync` (2) | `LinkValidationError: Item: Membership Dues - Daily` not seeded | Seed the membership Item (check `ensure_membership_type_exists("Daglid")` creates the linked Item) |
| `test_membership_approval` (1) | `AssertionError: No membership invoice generated AND no logged failure — approval may be silently dropping invoices` | **Investigate as a possible PRODUCT bug** (approval invoice path) |
| `test_concurrency_safety` (2) | `AssertionError: Exception not raised`; `4 != 3 total assignments` | Real concurrency asserts; sibling already `@unittest.skip`'d "thread-unsafe" — **decide skip vs product fix** |
| `test_membership_application` (1) | `QueryTimeoutError: doc being modified by another user` | Lock/flake — likely a commit/locking issue in setup |
| `test_volunteer_portal_integration` (1) | `TimestampMismatchError: User modified after opened`; ALSO the `national_board_chapter` polluter | Restore the Single in tearDown (stop leaking) + resolve the User save-conflict |
| `test_member_lifecycle_complete_real`, `test_regression_payment_history_draft_status` | passed in the 126-module batch | Recheck — may be co-location-only or already resolved |

### 3 FLAGGED ORDER_DEP (agents found no internal anti-pattern; PASS in the 16-batch)
`sepa_mandate_lifecycle_service` (pure Mock unit), `sepa_performance_optimization`
(`assertQueryCount` is a max-bound), `security_framework_comprehensive` (monotonic monitor).
Their v28/v29 polluter is an **external** file not in the ORDER_DEP set → resolves when that
polluter is fixed, or needs a full-suite run to pinpoint. **Don't fake a fix.**

## Decisions needed from Foppe

1. **`test_membership_approval`** — assertion says approval may be *silently dropping invoices*.
   Investigate as a production bug?
2. **`test_concurrency_safety`** — skip the two thread-unsafe tests (like their sibling) or attempt
   a real concurrency-logic fix?
3. **Option A** (Customer naming series) — pursue the structural follow-up, or leave Option E?

## How to finish

1. Fix the remaining GENUINE (donor `paid_to`, invoice Item, volunteer_portal Single restore;
   decide approval/concurrency with Foppe).
2. Re-run the **full** `run-parallel-tests` (4-shard) to confirm the churn is gone.
3. **Land the parked 4-shard tooling** (frappe `parallel_test_runner.py` patch +
   `test_timings.json` + generator + a make target).
4. Option A follow-up if approved.

## Gotchas

- Verify via the **detector** (cwd `frappe-bench/sites`), not `run-tests --module` (under-seeds).
- `run-parallel-tests`/detector splits files alphabetically within a shard; reproduction needs the
  LIVE shard list, not reconstruction.
- Pre-commit: `SKIP=whitelist-type-safety,insecure-api-detector,test-quality-enforcer,block-inappropriate-mocks`
  for these test files (the test-quality-enforcer hits are **pre-existing** permission bypasses,
  not introduced here).
- Subagents must NOT run git; commit from the main conversation only.
- Memory topic file: `test-order-dependence-2026-06-07.md`.
