# Design — False-Confidence Test Remediation Roadmap

**Date:** 2026-07-08
**Status:** Approved design (pending spec review) → next step: implementation plan
**Source of truth for the worklist:** `verenigingen/docs/testing/test-inventory/` (37 reports,
1,132 files, 20,180 methods classified HAPPY/UNHAPPY/EDGE/OTHER).

## 1. Problem & goal

The test-type inventory established that the suite is large and green, but a material slice of
that green is **false confidence**: ~1,367 methods classified `OTHER` (smoke / import-safety /
0-assert debug scripts / `@unittest.skip`-dominated / tautological / mock-into-tautology /
reimplements-prod-logic-in-test), plus tautological methods hiding inside the HAPPY/EDGE buckets
(e.g. `if result["success"]:`-guarded assertions that also pass on the failure branch). These
tests **execute code but cannot fail on a regression**, so they inflate coverage without
protecting anything.

**Goal:** make "green" mean "green." For every confirmed false-confidence test, either make it
assert real behavior or remove it — while keeping the coverage gate honest and never regressing it.

This is the **first** of the three gap classes the inventory surfaced. Out of scope for this
roadmap (tracked separately, see §8): net-new negative-path coverage on money paths, and
zero-coverage modules beyond the empty scaffolds we encounter in-batch.

## 2. Guiding decisions (locked with stakeholder)

1. **Optimize for killing false confidence first** (not raw new coverage).
2. **Triage by target:** delete tests whose target is dead/nonexistent code; **rewrite** tests
   whose target is live, important code but which assert nothing. Rewrites are scoped small — just
   enough to make the assertion real.
3. **Full risk-ordered roadmap**, executed in module batches over several sessions.
4. **Offset within each batch:** deletions and rewrites/adds are sequenced so each batch nets
   **coverage-neutral-or-positive** on its module. The CI gate never regresses; gate config is not
   touched. This is feasible precisely because the inventory found abundant real gaps to add
   meaningful tests against on the same modules.
5. **Bounded unhappy gap-fill (added 2026-07-08).** While an agent is already in a module's prod
   code to rewrite its tautologies, it also fills that module's **named** money-path unhappy gaps
   (from the offset-candidate list) plus any genuine-rejection path it directly touches. This is
   *bounded* — it does NOT audit the whole module for every missing case (that stays deferred, §3).
   New unhappy tests assert a genuine raise/throw/permission-denial (not a graceful-fallback, which
   is EDGE), are mutation-verified like rewrites, and are tracked separately from offset adds.

## 3. Scope & non-goals

**In scope:** changes to **test files only** — deleting confirmed-dead tests, rewriting
tautological tests to assert real behavior, and adding just enough real tests on the same module to
keep coverage neutral-or-positive per batch.

Adding real tests is also in scope where it is **bounded** — the offset rewrites/adds (§2.4) and
the named per-module unhappy gap-fill (§2.5).

**Non-goals (spun off to backlogs / later roadmaps, not done here):**
- **Deleting dead production code.** When a test's target turns out to be dead, we delete the test
  and record the dead prod code to a `dead-code` backlog for a separate pass. (Memory lesson:
  dead-code claims are unreliable — deletion of prod code needs its own careful track.)
- **Building missing features.** When a test references a nonexistent endpoint/feature, we delete
  the aspirational test and record the intended behavior to a `missing-coverage` backlog, so the
  lost intent is recoverable.
- **Unbounded module-wide negative-path audits.** Filling *every* missing unhappy case across a
  module (vs. the §2.5 named gaps) stays deferred to a dedicated gap-class-#2 roadmap — it does not
  converge per module and would stall the waves.

## 4. Artifacts

Living in `verenigingen/docs/testing/test-remediation/`:

- **`REMEDIATION-ROADMAP.md`** — the module sequence (§6), the triage algorithm (§5), and the
  batch definition-of-done (§7). The stable "how."
- **`REMEDIATION-TRACKER.md`** — living status board, one row per module batch:
  `module | status | flagged | deleted | rewritten | added | coverage Δ | commit | backlog refs`.
  Mirrors the inventory's `00-TRACKER.md`.
- **`backlog-dead-code.md`** — prod code found unreachable while dispositioning a test.
- **`backlog-missing-coverage.md`** — intended behaviors from deleted aspirational tests.

The 37 inventory reports remain the read-only worklist; each already names offenders per file
(e.g. report 31's "Weak / tautological files to flag", HANDOFF's "Highest-value gap-filling
targets"). We execute against those and also grep the machine-detectable patterns (§5.5) inside
each module to catch offenders the inventory did not name.

## 5. Triage algorithm (per flagged test method)

1. **Confirm the flag.** Read the method. Verify it is actually false-confidence: 0 meaningful
   assertions / asserts only shape or `isinstance` / `assertIsNotNone(result.success)` (always a
   bool) / `if result["success"]:`-guarded / `try/except: pass` swallowing / mock-into-tautology
   (patches the very function under test and asserts the mock's own return) / reimplements the
   production formula in-test / `@unittest.skip`-dominated. If it actually does assert real
   behavior, leave it (the inventory is judgement-based; do not over-delete).
2. **Locate the target** production code the test *should* exercise.
3. **Classify the target** (always re-grep callers — do not trust a prior "dead" claim):
   - **Live & important** → **REWRITE** to assert real behavior (see §5.4).
   - **Dead (no callers, unreachable)** → **DELETE** the test; append the prod symbol to
     `backlog-dead-code.md`.
   - **Missing (endpoint/feature does not exist)** → **DELETE** the test; append the intended
     behavior to `backlog-missing-coverage.md`.
4. **Pre-delete safety checks:** confirm (a) no other test imports symbols from the file being
   deleted, (b) the executed lines are covered by a real test elsewhere OR are genuinely dead —
   otherwise the deletion needs an offsetting real test in the same batch (§7).

### 5.4 What a valid rewrite looks like
- Exercises the real production path (mock only true collaborator boundaries — HTTP/SDK/GL/SFTP —
  never the function under test).
- Asserts a **value or observable effect**, not a type or dict-key.
- Uses the app's factory base classes (`EnhancedTestCase` / `VereningingenTestCase`) — no
  hand-rolled fixtures (per CLAUDE.md pre-implementation checklist).
- **Mutation-verified** (§7): proven to go red when the target is deliberately broken.

### 5.5 Machine-detectable patterns to grep per module
`assertIsNotNone(result.success)` · `assertTrue(True)` · `if result\["success"\]:` guarded blocks ·
`try:` … `except .*: pass` · files with 0 `def test_` under a `TestCase` · `@unittest.skip` clusters ·
`isinstance(...)` as the sole assertion · module-level `print(` with no `assert`.

## 6. Module sequence (risk-ordered; money-path first)

Executed top-down; re-orderable if a hotter area is known.

1. SEPA / mandate (batch/validation/reconciliation/sequence)
2. Payments apps — Mollie, ING Checkout, Ponto
3. Billing / dues / fee-change
4. Member financial & history (payment-history, fee-change-history, billing-date)
5. e_boekhouden (accounting sync)
6. Membership / termination
7. Chapter / volunteer / donation / donor
8. Report / API / portal
9. Utils / infra / security framework
10. Co-located doctype controllers + mijnrood_sync (Phase-8 offenders, incl. the four empty
    scaffolds: `bulk_operation_tracker`, `verenigingen_payments_settings`, `mijnrood_sync_log`,
    `mijnrood_sync_state`)

Each roadmap entry links to the inventory report(s) that name that module's offenders.

## 7. Batch definition-of-done

A module batch is complete only when **all** hold:

- Every flagged test in the module is dispositioned (deleted / rewritten / kept-with-note).
- **Every rewrite AND every new unhappy gap-fill test is mutation-verified:** green on current
  code; then the target is deliberately broken and the test is confirmed **red**; break reverted. A
  test that cannot be shown to fail on a break is not done.
- **Bounded unhappy gap-fill done (§2.5):** the module's named money-path unhappy gaps are covered
  by real UNHAPPY tests, counted separately from offset adds in the tracker.
- **Coverage delta ≥ 0** (the CI gate is a **Codecov delta gate** — it fails on a coverage
  *regression* vs. base, not on an absolute threshold; so "do not regress" is the exact target).
  Measured per module with file-scoped `coverage run --include=<module glob>` (the reusable per-file
  technique from prior sweeps). If a deletion would drop coverage, an offsetting real test on the
  same module lands in the same wave.
- Full module suite runs **green on a `test_site_N`** (1–5) — never veg11 (its before_tests
  bootstrap crashes on EUR-vs-INR).
- `REMEDIATION-TRACKER.md` updated; backlogs appended.
- **One conventional commit per module** (`test(<module>): remediate false-confidence tests`).

## 8. Orchestration — waves of 3, then a skeptical review, rinse repeat

- **Single accumulating branch** off `develop` (e.g. `refactor/test-false-confidence-remediation`).
  Every module commit lands on this one branch; it is NOT PR'd per module. The branch is reviewed
  and merged as a whole (or in a few grouped PRs) at the end. Do not commit directly to `develop`.
- **Wave = 3 modules in parallel.** Per module, a **general-purpose agent** performs triage +
  rewrites under a hardened contract (no sub-spawn; work incrementally; **test-files only**; use
  factory base classes; run on a `test_site_N`; mutation-verify every rewrite). Three such agents
  run concurrently, dispatched in one message.
- **After each wave, one `skeptical-code-reviewer` pass** adjudicates all three modules' rewrites
  together — it judges test meaningfulness (tautological / over-broad / stub-defeated /
  wrong-target) and gates against trading one weak test for another. Findings are fixed before the
  wave's commits are considered final.
- The orchestrator then verifies each module's DoD (§7), updates the tracker + backlogs, commits
  per module onto the accumulating branch, and launches the next wave. The 10 modules of §6 form
  ~4 waves (3/3/3/1).

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Deleting a test that was the *only* thing covering live code | §5.4 offset rule + coverage-Δ gate; deletion of live-covered lines forces an in-batch rewrite. |
| "Dead code" is actually reachable (unreliable claim) | Always re-grep callers before classifying dead; when unsure, rewrite rather than delete. |
| A rewrite is itself tautological | Mandatory mutation check + skeptical-code-reviewer adjudication. |
| Over-deletion from trusting the inventory's judgement | Step 1 re-confirms the flag against the actual code; leave genuine assertions alone. |
| Coverage gate regresses mid-roadmap | Per-batch coverage-Δ ≥ 0 is a hard DoD gate; gate config never touched. |
| Losing the intent of deleted aspirational tests | `backlog-missing-coverage.md` records intended behavior. |

## 10. Definition of done (whole roadmap)

Every module in §6 has a completed batch row in the tracker; the app-wide `OTHER` count and the
tautology-in-HAPPY/EDGE population are materially reduced; coverage % is neutral-or-higher than at
roadmap start; and two backlogs (`dead-code`, `missing-coverage`) capture the deferred follow-on
work. "Green means green" across the suite.

## 11. Resolved decisions

- **Coverage gate = Codecov delta** (regression-based). The §7 coverage-Δ ≥ 0 rule maps directly:
  no wave may regress module coverage vs. its start. The first wave still empirically measures the
  real exposure per module to confirm the offset math.
- **Branch strategy = single accumulating branch** off `develop`
  (`refactor/test-false-confidence-remediation`); per-module commits accumulate; reviewed/merged as
  a whole (or a few grouped PRs) at the end — not one PR per module.
- **Orchestration = waves of 3 module-agents → one skeptical-code-reviewer pass per wave → repeat**
  (see §8).
