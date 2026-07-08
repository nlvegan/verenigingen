# False-Confidence Test Remediation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove or rewrite every confirmed false-confidence test (0-assert / tautological / skip-dominated / mock-into-tautology) in the Verenigingen suite so that "green" means a real regression would fail, without ever regressing coverage.

**Architecture:** A risk-ordered roadmap executed in **waves of 3 module-agents**; each module runs the identical **Module Remediation Cycle** (triage → disposition → mutation-verify → coverage-Δ gate → commit). After each wave, one `skeptical-code-reviewer` pass adjudicates all three modules' rewrites. All commits accumulate on **one branch** off `develop`. Test-files only — no production code changes (dead prod code and missing features are logged to backlogs).

**Tech Stack:** Frappe/ERPNext (Python), `bench run-tests`, `coverage.py`, pytest-style asserts inside Frappe `FrappeTestCase`/`EnhancedTestCase`/`VereningingenTestCase`, git.

## Global Constraints

- **Test-files only.** Never modify production code in this roadmap. Dead prod code → `backlog-dead-code.md`; missing features → `backlog-missing-coverage.md`.
- **Run tests on `test_site_1`..`test_site_5` — NEVER `veg11.veganisme.org`** (its `before_tests` bootstrap crashes on EUR-vs-INR).
- **Every rewrite AND every new unhappy gap-fill test is mutation-verified:** green on current code, then break the target and confirm the test goes red, then revert the break.
- **Bounded unhappy gap-fill (added 2026-07-08):** while in a module's prod code, also add real UNHAPPY tests for that module's NAMED unhappy gaps (the per-task "OFFSET/GAP CANDIDATES" list) + any genuine-rejection path you directly touch. Bounded — do NOT audit the whole module for every missing case. Assert a genuine raise/throw/permission-denial, NOT a graceful-fallback (that is EDGE). Count these separately from offset adds.
- **Coverage gate = Codecov delta (regression-based).** No wave may regress module coverage vs. its start (`coverage-Δ ≥ 0`).
- **Fixtures via factory base classes** (`EnhancedTestCase` / `VereningingenTestCase`) — never hand-rolled Member/Membership docs (per CLAUDE.md pre-implementation checklist).
- **Pre-commit compliance (added after Wave 1):** before finishing, run `pre-commit run --files <your changed files>` and fix all violations. The test-quality-enforcer rejects `ignore_permissions=True` / `set_user("Administrator")` in test *bodies* — put any such seeding in a factory-named helper (`_create_*`, `setup_*`, `make_*`, `ensure_test*`) or `setUp`/`tearDown`. Also keep files `ruff`+`black` clean (no unused imports left after deleting code).
- **Single accumulating branch:** `refactor/test-false-confidence-remediation`. One conventional commit per module: `test(<module>): remediate false-confidence tests`. Never commit to `develop` directly.
- **Design source of truth:** `verenigingen/docs/testing/test-remediation/2026-07-08-false-confidence-remediation-design.md`. **Worklist source:** the 37 reports in `verenigingen/docs/testing/test-inventory/`.

---

## Task 1: Set up branch and remediation artifacts

**Files:**
- Create: `verenigingen/docs/testing/test-remediation/REMEDIATION-ROADMAP.md`
- Create: `verenigingen/docs/testing/test-remediation/REMEDIATION-TRACKER.md`
- Create: `verenigingen/docs/testing/test-remediation/backlog-dead-code.md`
- Create: `verenigingen/docs/testing/test-remediation/backlog-missing-coverage.md`

**Interfaces:**
- Produces: the tracker table schema and the two backlog files that every Module Remediation Cycle appends to.

- [ ] **Step 1: Create the remediation branch off develop**

Run:
```bash
cd /home/frappeuser/frappe-bench/apps/verenigingen
git checkout develop && git pull --ff-only
git checkout -b refactor/test-false-confidence-remediation
```
Expected: `Switched to a new branch 'refactor/test-false-confidence-remediation'`.

- [ ] **Step 2: Write `REMEDIATION-ROADMAP.md`**

Content (the stable "how" — copy verbatim):
```markdown
# False-Confidence Remediation — Roadmap

Design: ./2026-07-08-false-confidence-remediation-design.md
Worklist: ../test-inventory/ (37 reports; each names offenders per file)

## Module sequence (risk-ordered; executed in waves of 3)
Wave 1: 1 SEPA · 2 Payments (mollie/ing/ponto) · 3 Billing/dues/fee
Wave 2: 4 Member-financial & history · 5 e_boekhouden · 6 Membership/termination
Wave 3: 7 Chapter/volunteer/donation/donor · 8 Report/api/portal · 9 Utils/infra/security
Wave 4: 10 Co-located doctype controllers + mijnrood_sync

## Module Remediation Cycle (run per module — see plan Task template)
1. Snapshot baseline module coverage.
2. Grep the machine-detectable patterns + read the inventory-named offenders; confirm each flag.
3. Disposition each: live→rewrite, dead→delete+log dead-code, missing→delete+log missing-coverage.
4. Mutation-verify every rewrite (green→break→red→revert).
5. Re-run the module suite green on a test_site_N.
6. Confirm coverage-Δ ≥ 0 vs. baseline; if a deletion dropped coverage, add an offsetting real test.
7. Update TRACKER + backlogs; commit `test(<module>): remediate false-confidence tests`.

## Grep patterns (step 2)
assertIsNotNone(result.success) · assertTrue(True) · if result["success"]: · try:/except: pass ·
0 `def test_` under a TestCase · @unittest.skip clusters · isinstance(...) as sole assertion ·
module-level print( with no assert.
```

- [ ] **Step 3: Write `REMEDIATION-TRACKER.md` (empty board)**

Content:
```markdown
# False-Confidence Remediation — Tracker

Branch: refactor/test-false-confidence-remediation · Gate: Codecov delta (no regression)
Legend: ⬜ pending · 🟨 in wave · ✅ done

| # | Module | Status | Flagged | Deleted | Rewritten | Added | Coverage Δ | Commit | Backlog refs |
|---|--------|--------|--------:|--------:|----------:|------:|:----------:|--------|--------------|
| 1 | SEPA | ⬜ | | | | | | | |
| 2 | Payments (mollie/ing/ponto) | ⬜ | | | | | | | |
| 3 | Billing/dues/fee | ⬜ | | | | | | | |
| 4 | Member-financial & history | ⬜ | | | | | | | |
| 5 | e_boekhouden | ⬜ | | | | | | | |
| 6 | Membership/termination | ⬜ | | | | | | | |
| 7 | Chapter/volunteer/donation/donor | ⬜ | | | | | | | |
| 8 | Report/api/portal | ⬜ | | | | | | | |
| 9 | Utils/infra/security | ⬜ | | | | | | | |
| 10 | Co-located doctype + mijnrood_sync | ⬜ | | | | | | | |

## Wave log
- (none yet)
```

- [ ] **Step 4: Write the two backlog files (empty)**

`backlog-dead-code.md`:
```markdown
# Backlog — Dead production code found while remediating tests

Prod symbols with no callers, surfaced when a test's target turned out unreachable.
Format: `- <file>:<symbol> — from <deleted test> — re-grep callers before deleting prod code.`

(none yet)
```

`backlog-missing-coverage.md`:
```markdown
# Backlog — Missing coverage / features from deleted aspirational tests

Intended behaviors from tests deleted because they referenced nonexistent endpoints/features.
Format: `- <intended behavior> — from <deleted test> — build feature OR write real test.`

(none yet)
```

- [ ] **Step 5: Commit**

Run:
```bash
git add verenigingen/docs/testing/test-remediation/
git commit -m "docs(test-remediation): scaffold roadmap, tracker, and backlogs

Claude-Session: https://claude.ai/code/session_01QzKjZkhw1pqZACTdSf9Ey7"
```
Expected: one commit on `refactor/test-false-confidence-remediation`.

---

## Module Remediation Cycle (the reusable sub-routine every module task runs)

Each module task below supplies three arguments: **SEEDED OFFENDERS** (inventory-named files to
confirm first), **TEST GLOB** (where the module's tests live), and **COVERAGE INCLUDE** (derived at
run time from the imports of the test files you touch — the production modules under test). Then run
these steps. `<M>` = module number, `<name>` = module name.

- [ ] **C1: Snapshot baseline coverage.** For the production files the module's tests import, run:
  ```bash
  cd /home/frappeuser/frappe-bench
  bench --site test_site_1 run-tests --app verenigingen --module <module.dotted.path> 2>&1 | tail -5
  # then, scoped coverage on the prod files under test:
  coverage run --include='<COVERAGE INCLUDE glob>' -m pytest <TEST GLOB> ; coverage report
  ```
  Record the baseline % in the tracker row. (If `coverage`/pytest is unavailable for a Frappe-bound
  module, use `bench run-tests` + note that coverage-Δ is judged by lines-covered before/after.)

- [ ] **C2: Discover + confirm offenders.** Grep the patterns from the roadmap across `<TEST GLOB>`,
  union with the SEEDED OFFENDERS, then **read each candidate** and confirm it is truly
  false-confidence (design §5.1). Leave genuine assertions alone.
  ```bash
  grep -rnE "assertIsNotNone\(.*\.success\)|assertTrue\(True\)|except[^:]*:\s*pass|isinstance\(" <TEST GLOB>
  grep -rLnE "assert|self\.fail|with self\.assertRaises" <TEST GLOB>   # files with NO assertion
  grep -rn "@unittest.skip" <TEST GLOB>
  ```

- [ ] **C3: Disposition each confirmed offender** (design §5.3):
  - Target **live & important** → rewrite to assert a value/effect (mock only true boundaries).
  - Target **dead** (re-grep callers first!) → delete test; append to `backlog-dead-code.md`.
  - Target **missing** endpoint/feature → delete test; append to `backlog-missing-coverage.md`.
  - Before any delete: `grep -rn "from .*<deleted module> import\|import <deleted module>" verenigingen/`
    to confirm nothing imports the file.
  - **Bounded gap-fill (§2.5):** after dispositioning, add real UNHAPPY tests for this module's
    NAMED gaps (the task's GAP CANDIDATES list) + any genuine-rejection path you directly touched.
    Assert a real raise/throw/permission-denial (NOT a graceful-fallback → that's EDGE, skip it).
    Mutation-verify these in C4 like rewrites. Bounded: do NOT audit the whole module for every
    missing case. Record the added-unhappy count separately in the tracker row.

- [ ] **C4: Mutation-verify every rewrite.** For each rewritten test:
  ```bash
  bench --site test_site_1 run-tests --app verenigingen --module <test.module> --test <test_name>   # PASS
  # temporarily break the target (e.g. flip a comparison / return None) in the PROD file, then:
  bench --site test_site_1 run-tests --app verenigingen --module <test.module> --test <test_name>   # must FAIL
  git checkout -- <prod file>   # revert the break — prod code stays untouched
  ```
  A rewrite that stays green when the target is broken is NOT done — strengthen the assertion.

- [ ] **C5: Run the full module suite green on a test site.**
  ```bash
  bench --site test_site_1 run-tests --app verenigingen --module <module.dotted.path> 2>&1 | tail -15
  ```
  Expected: all pass. (NEVER veg11.)

- [ ] **C6: Confirm coverage-Δ ≥ 0.** Re-run the C1 scoped coverage command; compare to baseline.
  If a deletion dropped coverage on live code, add an offsetting real test on the same module (the
  inventory's "under-tested negative paths" list names good candidates) and re-check.

- [ ] **C7: Update tracker + commit.** Fill the module's tracker row (flagged/deleted/rewritten/added
  /Δ), then:
  ```bash
  git add verenigingen/ && git commit -m "test(<name>): remediate false-confidence tests

Deleted <n> dead, rewrote <n> tautological, added <n> offsetting; coverage Δ +<x>%.
Claude-Session: https://claude.ai/code/session_01QzKjZkhw1pqZACTdSf9Ey7"
  ```

---

## Task 2 (Wave 1): SEPA · Payments · Billing — 3 agents in parallel

Dispatch three general-purpose agents in ONE message, one module each, each running the Module
Remediation Cycle with the arguments below.

**Module 1 — SEPA**
- TEST GLOB: `verenigingen/tests/sepa/` + `verenigingen/verenigingen_payments/doctype/sepa_*/`
- SEEDED OFFENDERS (confirm first):
  - `verenigingen/tests/sepa/test_enhanced_sepa_integration.py` — non-unittest print script, swallows failures.
  - `verenigingen/verenigingen_payments/doctype/sepa_audit_log/test_sepa_audit_log.py` — lone `assertTrue(True)` placeholder.
  - `verenigingen/verenigingen_payments/doctype/sepa_mandate/test_sepa_mandate_comprehensive.py` — 5 save-then-assert-nothing placeholders.
  - `verenigingen/tests/unit/test_sepa_business_logic_unit.py` — 12/13 reimplement validators in-test.
  - `verenigingen/tests/api/test_sepa_health.py` — 10/10 key-presence + type only.
- OFFSET CANDIDATE (design's named negative-path gap): SEPA **FRST→RCUR** sequence-type on a real collection (only ~1 end-to-end transition test exists) — add one real transition assertion if a deletion needs offsetting.

**Module 2 — Payments (mollie/ing/ponto)**
- TEST GLOB: `verenigingen/verenigingen_payments/mollie/tests/` + `verenigingen/verenigingen_payments/ing_checkout/tests/` + `verenigingen/tests/sepa/test_ponto_*`
- SEEDED OFFENDERS:
  - mollie `test_payment_entry.py`, `test_subscription_creation.py`, `test_subscription_fixes.py`, `test_webhook_directly.py` — debug scripts, hit real API / hardcoded prod records, 0 asserts.
  - mollie `test_payment_context_resolver.py` — 7/14 assertion-free "doesn't crash".
  - `verenigingen/verenigingen_payments/tests/test_api_regression.py` — 14/15 `isinstance`-or-exception tolerant; `hasattr(...__name__)` always true.
  - `verenigingen/tests/payment/test_payment_integration_workflows.py` — 8/8 `@unittest.skip`.

**Module 3 — Billing/dues/fee**
- TEST GLOB: `verenigingen/tests/payment/` + `verenigingen/verenigingen/doctype/membership_dues_schedule/`
- SEEDED OFFENDERS:
  - `verenigingen/tests/payment/test_dues_schedule_system.py`, `test_payment_plan_system.py` — module-level print debug, 0 asserts.
  - `verenigingen/tests/backend/optimization/*` (all 5) — non-collected copy-paste smoke, print timings only.
  - `verenigingen/tests/backend/performance/test_api_performance.py` — 9/9 tautological (asserts stdlib arithmetic).

- [ ] **Step 1:** Dispatch 3 general-purpose agents (one per module) with the hardened contract (Global Constraints + the Module Remediation Cycle steps C1–C7). Each returns: counts (flagged/deleted/rewritten/added), coverage Δ, backlog appends, and the list of rewritten test names for review.
- [ ] **Step 2:** When all three finish, dispatch ONE `skeptical-code-reviewer` agent over the three modules' **rewritten tests only**, asking it to adjudicate meaningfulness (tautological / over-broad / stub-defeated / wrong-target) by reading the production code under test. Fix every confirmed finding.
- [ ] **Step 3:** Verify each module hit its C5 (green) and C6 (Δ ≥ 0) gates; confirm the 3 module commits are on the branch; update the tracker Wave log.

---

## Task 3 (Wave 2): Member-financial · e_boekhouden · Membership/termination

Same structure as Task 2 (3 agents → skeptical review → verify). Arguments:

**Module 4 — Member-financial & history**
- TEST GLOB: `verenigingen/tests/unit/` (payment/lifecycle) + `verenigingen/verenigingen/doctype/member/`
- SEEDED OFFENDERS:
  - `verenigingen/tests/unit/test_payment_direction.py` — 12/12 reimplement the `is_incoming` expression.
  - `verenigingen/tests/unit/test_member_lifecycle_unit.py` — 12/15 inline helpers.
  - `verenigingen/tests/unit/test_member_lifecycle_production_issues_discovered.py` — 7/7 pure `print()`, 0 asserts.
  - the `*_mock_elimination.py` pair — swallow failure branches in try/except.
- OFFSET CANDIDATES: member fee-change-history + payment-history realdb + billing-date have ~0 UNHAPPY.

**Module 5 — e_boekhouden**
- TEST GLOB: `verenigingen/tests/e_boekhouden/`
- SEEDED OFFENDERS:
  - `test_cost_center_ui_integration.py` — 8/12 OTHER (3 patch the whitelisted fn then assert the mock; 4 UI sims).
  - `test_party_resolver.py` — patches `frappe` wholesale, 9/35 config-shape/delegation tautologies (its `_coverage` twin is the real one).
  - `test_transaction_type_classification.py::test_unknown_numeric_type_raises_error` + `test_payment_processor_sweep::TestLinkBankTransactionToPayment` — known-bug / dead-code pins (see report 25c; keep-with-note, do NOT silently delete).

**Module 6 — Membership/termination**
- TEST GLOB: `verenigingen/verenigingen/doctype/membership*/` + `verenigingen/verenigingen/doctype/membership_termination_request/`
- SEEDED OFFENDERS (from Phase-8 reports 34):
  - `membership_termination_request/test_membership_termination_request_critical.py` — 8/8 OTHER; pins nothing.
  - `membership/test_membership.py::test_payment_sync` (db_set roundtrip) + `membership_type/test_membership_type.py::test_default_membership_type` (asserts flags it just set).

- [ ] **Step 1:** Dispatch 3 agents (modules 4/5/6). **Step 2:** skeptical review over rewrites. **Step 3:** verify gates + tracker.

---

## Task 4 (Wave 3): Chapter/volunteer/donation/donor · Report/api/portal · Utils/infra/security

**Module 7 — Chapter/volunteer/donation/donor**
- TEST GLOB: `verenigingen/tests/chapter/` + `verenigingen/tests/donor/` + `verenigingen/verenigingen/doctype/volunteer/`
- SEEDED OFFENDERS:
  - `test_chapter_board_permissions_comprehensive.py` — 8/12 skipped (archived DocType).
  - `verenigingen/tests/donor/` — 7 overlapping `test_donor_permissions*.py` + `test_donor_security_*.py`; `_enhanced.py` and `_enhanced_fixed.py` near-identical → consolidate (delete the duplicate, keep one meaningful).
  - `volunteer/test_volunteer.py` — 13/30 OTHER; five tests assert non-fields (`phone`/`address`/`development_goals`/`emergency_contact_*`/`training_records`/`languages_spoken` are NOT in `volunteer.json`) → delete those; pass-either-way permission tests → rewrite or delete.

**Module 8 — Report/api/portal**
- TEST GLOB: `verenigingen/tests/api/` + `verenigingen/tests/report/` + `verenigingen/tests/backend/portal/`
- SEEDED OFFENDERS:
  - `tests/api/test_security_monitoring_dashboard.py` — 7 envelope-shape / `0<=x<=100` tautologies.
  - report `test_is_membership_related_always_true` — asserts an always-True fn.
  - `test_broken_link_detection_is_currently_dead_code` + the `link.type` vs `link_type` pin — known-bug tripwires (keep-with-note).

**Module 9 — Utils/infra/security**
- TEST GLOB: `verenigingen/tests/utils/` + `verenigingen/tests/backend/unit/services/` + `verenigingen/tests/security/`
- SEEDED OFFENDERS:
  - `backend/unit/services/test_approval_unification.py` — 17/17 AST-string / getattr refactor asserts.
  - `tests/utils/test_notification_helpers.py` — 6/23 re-implement prod logic; one `assertTrue(True)`.
  - `security/test_security_penetration.py` — 8/12 skipped.

- [ ] **Step 1:** Dispatch 3 agents (modules 7/8/9). **Step 2:** skeptical review. **Step 3:** verify gates + tracker.

---

## Task 5 (Wave 4): Co-located doctype controllers + mijnrood_sync

Only 1 module remains, so this wave is a single agent + skeptical review.

**Module 10 — Co-located doctype + mijnrood_sync**
- TEST GLOB: `verenigingen/verenigingen/doctype/*/test_*.py` (the Phase-8 set) + `verenigingen/mijnrood_sync/`
- SEEDED OFFENDERS (Phase-8 reports 33/34/35/36):
  - **Empty scaffolds** (0 test methods — decide: write a real smoke+happy+1-unhappy, or delete the stub file): `doctype/bulk_operation_tracker/test_bulk_operation_tracker.py`, `doctype/verenigingen_payments_settings/test_verenigingen_payments_settings.py`, `mijnrood_sync/doctype/mijnrood_sync_log/test_mijnrood_sync_log.py`, `mijnrood_sync/doctype/mijnrood_sync_state/test_mijnrood_sync_state.py`.
  - `doctype/expense_category/test_expense_category.py` — all `skipTest`-guarded → make runnable or delete.
  - `mijnrood_sync` `TestStaticMappingConstants` — 4 static-constant drift guards; `test_create_volunteers_batch_uses_service` — mock-into-tautology.

- [ ] **Step 1:** Dispatch 1 agent (module 10) running the Module Remediation Cycle. Note: for the four empty scaffolds, C3's "target live & important" branch means **write** a minimal real test (smoke + happy + one unhappy) rather than delete — these are genuine coverage holes.
- [ ] **Step 2:** skeptical review over the new/rewritten tests. **Step 3:** verify gates + tracker; mark all 10 modules ✅.

---

## Task 6: Close out the roadmap

- [ ] **Step 1:** Confirm the tracker shows all 10 modules ✅ with non-negative coverage Δ each, and the two backlogs are populated with any deferred dead-code / missing-feature items.
- [ ] **Step 2:** Run the full app suite once on a test site to confirm nothing cross-module broke:
  ```bash
  cd /home/frappeuser/frappe-bench && bench --site test_site_1 run-tests --app verenigingen 2>&1 | tail -20
  ```
- [ ] **Step 3:** Update `verenigingen/docs/testing/test-inventory/HANDOFF.md` — mark the false-confidence gap class as remediated, with the aggregate deleted/rewritten/added counts and the net coverage Δ.
- [ ] **Step 4:** Present the accumulated branch for review/merge (one PR for the whole branch, or a few grouped PRs by wave — per stakeholder). Do NOT merge to `develop` without approval.

---

## Self-review notes (author)

- **Spec coverage:** design §4 artifacts → Task 1; §5 triage → Cycle C2–C3; §7 DoD → Cycle C4–C7; §8 waves+skeptical review → Tasks 2–5 Step 2; §6 sequence → Tasks 2–5; §3 non-goals/backlogs → Task 1 + C3; §11 resolved decisions (delta gate, single branch, waves-of-3) → Global Constraints + Task structure. All covered.
- **Deliberate design choice:** the Module Remediation Cycle is defined once as a reusable sub-routine (it is identical per module); each module task supplies concrete arguments (paths/globs/seeded offenders) rather than repeating the 7 steps 10×. This is DRY without forcing the engineer to jump — the cycle is on the same page, directly above the tasks that invoke it.
- **Not fully enumerable up front:** the exact per-test edits are discovered at execution time (C2 reads each candidate). That is intentional and matches the design — the plan fixes the *procedure, seeded offenders, and gates* concretely; the specific assertions depend on each test's actual body.
