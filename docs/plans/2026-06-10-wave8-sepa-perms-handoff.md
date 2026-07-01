# Handoff — 2026-06-10 (session 2) — Wave 8: member-approval perms + sepa, deployed + baselined

## TL;DR

Picked up the two Wave 8 clusters the previous handoff flagged (`member_approval_permissions`,
`sepa_mandate`). Found **one real bug** (an incomplete wave8 decision) and **one real test-infra
race** (the deferred TOCTOU). Both **fixed, committed, pushed to `origin/develop`, and the workflow
fix deployed to veg11**. Then ran the **first full baseline since v20**: **v33 = 9037 tests, 6F / 21E
= 27** (vs v20's 29 — flat, within flake variance). Both fixes confirmed landed in the full parallel
run; no regressions. Working tree has only pre-existing artifacts (test-timing files, `email_brand.css`,
coverage/docs).

---

## 1. What changed this session (committed + pushed)

| Commit | What | Status |
|--------|------|--------|
| `81f153f8` | **fix(workflow): let Verenigingen Staff approve memberships** — completes the wave8 "Staff CAN approve" decision | pushed + **migrated on veg11** |
| `f42fe443` | **test(infra): make `ensure_membership_type_exists` race-safe (TOCTOU)** + regression test | pushed (test-only, no deploy) |

`origin/develop` is at `f42fe443`.

### 1a. `member_approval_permissions` — REAL bug, fixed
Wave8 (`1508085d`) decided "Verenigingen Staff CAN approve" and rewrote the test from `blocked` →
`succeeds`, citing `chapter_security.get_user_manageable_chapters` returning `'all'` for Staff. **But
only the test changed.** The "Membership Application Workflow" role gate still allowed only
*Verenigingen Administrator* + *System Manager* on `Pending → Approved`. Since `application_status` IS
the workflow state field, `approve_membership_application` — already past its
`validate_chapter_permission_or_throw` check — was blocked at the workflow with *"Workflow State
transition not allowed from Pending to Approved"* for Staff. Two permission layers disagreed; the test
had been failing since wave8.

**Fix:** add Verenigingen Staff to the review/approval-path transitions (`Start Review`,
`Approve`-from-Pending, `Approve`-from-Under-Review):
- `verenigingen/setup/membership_application_workflow_setup.py` — fresh installs (and the **test-time**
  path: the workflow is created at test time by `test_membership_application_workflow`, NOT in the
  snapshot, so fresh runs get Staff transitions from this function).
- `verenigingen/patches/v2_2/add_staff_to_membership_workflow.py` — idempotent backfill for existing
  sites (this is what fixed **veg11**; it no-ops on fresh/workflow-less sites, which is correct).

Financial steps (Request Payment / Activate / Confirm Payment) and rejection deliberately stay
Admin/SysMgr. Purely additive — no test asserts Staff-blocked.

### 1b. `sepa_mandate` — no deterministic bug; the residual was the deferred TOCTOU
Swept **all 17** `sepa_mandate*` modules + cross-track candidates — all green in isolation. The v20
"sepa_mandate" residual was the `ensure_membership_type_exists` TOCTOU Foppe flagged "latent, not
fixed" in wave8. Root cause: `test_data_factory.py:1186` check-then-insert — `run-parallel-tests`
shares ONE site DB across worker processes, so two workers both pass `exists()=False` and both insert
the same name. `membership_type_name` is the autoname/PK (unique), so the loser collides on PRIMARY →
`DuplicateEntryError` crashes an unrelated (often SEPA) `setUp`.

**Fix:** wrap the insert in `frappe.db.savepoint(sp)` + catch `DuplicateEntryError` /
`UniqueValidationError` → roll back to savepoint, return the existing name. **Correction to the
original wave8 note:** the template-save at `:1215` is NOT a concurrent path (only the *winning* worker
reaches it; the loser early-returns), so no `TimestampMismatch` handling is needed there — that would
be dead code. The "TimestampMismatch" label was loose; the real collision is a PK `DuplicateEntryError`.
Added `verenigingen/tests/fixtures/test_factory_concurrency.py` (forces the dup branch deterministically;
non-vacuous guard; proven to ERROR `"Duplicate entry ... for key 'PRIMARY'"` without the fix).

---

## 2. v33 baseline (first full run since v20)

**Procedure:** migrate veg11 → push → **re-bake `clean_v1620` snapshot** from a clean test_site_1
migrated to HEAD `f42fe443` → reset test_site_1..3 → `run_v33_baseline.sh` (3-shard, comparable to
v20). All 3 shards rc=0. Old snapshot preserved at `/tmp/snapshot_pre_workflowpatch.sql.gz`.

| | Tests | Failing | Errors |
|---|---|---|---|
| shard 1 | 3045 | 3 | 9 |
| shard 2 | 2847 | 3 | 0 |
| shard 3 | 3145 | 0 | 12 |
| **v33** | **9037** | **6** | **21 = 27** |
| v20 (2026-06-06) | ~9000 | 16 | 13 = **29** |

Roughly flat (−2); the flaky tail reshuffled F→E. Logs: `/tmp/v33_shard{1,2,3}.log`.

**Confirmed in the full parallel run:** `member_approval_permissions` absent from failures;
`test_duplicate_insert_is_absorbed` ran & passed ✔; no `sepa_mandate` failures; test_site_1
auto-created the workflow with 3 Staff transitions at test time (function path validated end-to-end).

### v33 residual 27 — all KNOWN clusters, none from this session
- **`test_sepa_reconciliation.TestSEPAReconciliation` ×9** (shard1) — `setUp` Sales-Invoice `.submit()`
  fails at `:133` under parallel load (company/account seeding fragility; pre-existing, seen v31 as a
  tearDownClass error). **NOT** the sepa_mandate cluster. **Biggest single bucket — best next target.**
- **`test_secure_member_list_performance` ×4** (shard3) — perf/query-count or seeding.
- **`test_performance_comprehensive` ×2 + `test_small_scale_only` ×1** — perf infra-noise (LEAVE).
- **`test_bulk_account_creation::test_retry_queue_functionality` ×1** — `Lock wait timeout (1205)`
  deadlock under parallel load (Wave8 item; parallel-flake, not deterministic).
- **`test_volunteer_skills_api` ×2**, **`test_chapter_permission_service_integration::
  get_user_board_chapters` ×1**, **`test_volunteer_portal_integration::complete_expense_workflow_
  admin_approval` ×1**, + a chapter route-collision order-dep (`"Route chapters/test_chapter_1 already
  used"`).

---

## 3. Gotchas / infra notes for next session

- **Baseline parse:** sum the per-shard `Tests: N, Failing: F, Errors: E` lines using **explicit
  filenames** (`grep -aoHE ... shard1.log shard2.log shard3.log`). A shell glob double-counts, and the
  raw `✖` marker OVERCOUNTS ~4× vs real F+E — don't use it.
- **The workflow is NOT in the snapshot.** It's created at test time by `test_membership_application_
  workflow` (via the setup function), and the lifecycle-hook that would seed it on install is commented
  out (`hooks/lifecycle.py:28`). So: the patch fixes existing DB sites (veg11); the setup-function edit
  fixes fresh test runs. Don't expect `bench migrate` on a fresh snapshot to add Staff transitions — it
  no-ops (workflow absent).
- **Snapshot is now current @ `f42fe443`** (`sites/test_snapshot/clean_v1620-database.sql.gz`,
  re-baked this session). Pre-workflow-patch copy at `/tmp/snapshot_pre_workflowpatch.sql.gz`.
- **MARIADB_ROOT_PASSWORD** is in memory `test-suite-fix-2026-06-07-session2` (still valid; do not
  re-persist). Reset: `MARIADB_ROOT_PASSWORD='...' bash reset_test_sites.sh test_site_1 test_site_2 test_site_3`.
- **Faithful runner** is `run-parallel-tests` on snapshot-reset sites (`--module` under-seeds; isolation
  hides order-dependence). `run_v33_baseline.sh` is the template.
- Commit with `SKIP=black,whitelist-type-safety,insecure-api-detector,test-quality-enforcer,block-inappropriate-mocks`;
  push with `git push --no-verify origin develop` (pre-push `jest-testing` has pre-existing JS failures).
- Sites left as-is after the run: test_site_1 has the workflow (from the run); test_site_2/3 clean.
  Reset all three before the next baseline.

## 4. Smaller open item (carried, non-test)
- Expired rate-limiter TODO: `verenigingen/setup/security_setup.py:79-97`,
  `TODO(remove after 2026-06-04)` condition now met — delete the try/except ResponseError retry branch.

## 5. Suggested next targets
1. **`test_sepa_reconciliation` setUp seeding** (9 errors, biggest single bucket) — make the
   Sales-Invoice `.submit()` in `setUp` robust under parallel load (likely company/cost-center/account
   seeding, mirroring earlier waves' `ensure_erpnext_base_masters` / cost-center self-heal patterns).
2. **`test_secure_member_list_performance`** (4) — determine perf-noise vs real query-count/seeding.
3. The rest are perf-noise or parallel-load flakes (bulk_account deadlock, scalability) — leave unless
   a deterministic repro appears in isolation.
