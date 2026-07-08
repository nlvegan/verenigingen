# Test Inventory — Methodology

How this test-type inventory was produced, so it can be continued, re-run, or trusted.

## Goal
Classify **every test method** in the app into one of four intent types, per file and per
domain, to reveal coverage shape (esp. where negative-path testing is thin) and surface
weak/dead tests. This is an **inventory + triage**, not a refactor — nothing under test was
modified, run, or fixed.

## The four categories
Each class-level `def test_*` gets exactly ONE primary type (dominant intent when mixed):

- **HAPPY** — nominal success / expected-valid path succeeds.
- **UNHAPPY** — expects an error/throw/validation-failure/permission-denial/rejection/
  signature-reject. The assertion that *fails on regression* is a negative outcome.
- **EDGE** — boundary, empty/null/zero, duplicate/replay, concurrency, idempotency, malformed
  data, ordering, retry/backoff, rounding/sign, graceful-degradation returns.
- **OTHER** — smoke / import-safety / setup-only / tautological / debug-script-with-no-assert /
  mock-into-tautology / `@unittest.skip`-dominated. Always annotated with WHY.

### Classification rules of thumb (applied consistently across all agents)
- **Services that return `False`/error-dicts instead of raising** → the "absence of data / graceful
  fallback" case is **EDGE**; only an *invalid identity / genuine rejection* is **UNHAPPY**. (This is
  why true asserted-failure coverage is even thinner than the ~17% UNHAPPY headline.)
- **`if result["success"]:`-guarded** assertions that also pass on the failure branch → **OTHER**
  (can't fail meaningfully). Same for `assertIsNotNone(result.success)` (always a bool).
- **Shape-only** (asserts only dict keys / column defs / return type, no values/behavior) → **OTHER**
  if no business value is pinned; **EDGE** if it asserts correct behavior on empty/boundary data.
- **Reimplements production logic in the test body** (inline formula/validator) and asserts against
  that → **OTHER** (regression-inert).
- **Mock-into-tautology**: patches the very function/endpoint under test and asserts the mock's own
  return → **OTHER**. Mocking a *collaborator* (HTTP/SDK/GL boundary) while real logic runs is fine.
- **Known-bug tripwires** (tests that pin current-wrong behavior) → classified by what they assert,
  but flagged in observations.
- Count **class-level methods only**; nested helper `def test_*` inside a method are excluded
  (naive `grep -c 'def test_'` over-counts — several reports note the discrepancy).

## Orchestration
- **Scope unit = one folder / subtree = one domain.** Big trees split by sorted file position into
  ~20–30-file chunks (e.g. e_boekhouden → 1–29 / 30–58 / 59–87).
- **Fan-out in waves of 3–4 concurrent general-purpose agents**, one domain each, dispatched in a
  single message so they run in parallel. Orchestrator waits for the wave, updates the tracker,
  launches the next.
- **Agent contract (hardened after a failure — see below):**
  1. READ-ONLY; classify per the categories above.
  2. **Do all work yourself — NEVER spawn sub-agents / Task / Agent tools.**
  3. **Write the report incrementally**: header + table header first, then append each file's row
     immediately after classifying it (so a crash preserves partial progress).
  4. Per file: `grep -nE "def test_"` for the method list, then Read bodies in ranges to judge intent.
  5. Output a per-file table `| File | Total | Happy | Unhappy | Edge | Other |`, a DOMAIN TOTALS row,
     4–6 observation bullets (coverage skew, weak/dead files, mock-tautology flags, strongest files,
     base class), and a note of any zero-method/missing files.
  6. Return domain totals + top-3 observations + files-completed count to the orchestrator.

### Why the "no sub-agents" rule exists
The first Phase-3 attempt gave agents 85 files each; they *independently decided to fan out into
their own sub-agents*, which multiplied token use and hit the weekly **session limit** — producing
**zero output**. The re-run with "no sub-spawn + incremental writes" completed cleanly. A single
agent comfortably handles ~85 files of pure classification.

## Outputs & durability
- All reports live in **`verenigingen/docs/testing/test-inventory/`** (git working tree; currently
  **untracked** — `git add` to version them). This folder is durable; the session scratchpad
  (`/tmp/.../scratchpad`) is NOT and was only used before the reports were copied in-repo.
- `00-TRACKER.md` = status board (domains, per-domain H/U/E/O, grand total, progress log, remaining).
- `NN-<domain>.md` = per-domain reports.
- `99-SUMMARY.md` = cross-cutting synthesis (Phases 1–2 baseline + banner to current totals).
- `HANDOFF.md` = entry point: what's done, what's left, concrete gap-fill targets, how to resume.
- `METHODOLOGY.md` = this file.

## After each wave (orchestrator checklist)
1. Read each agent's returned totals.
2. Update `00-TRACKER.md`: mark domains ✅ with `Nt: H/U/E/O`, add the phase subtotal, refresh the
   GRAND TOTAL line, append a progress-log entry, update the remaining list.
3. Update `HANDOFF.md`: DONE table + type-mix % + remaining list + any new weak-test findings.
4. Spot-verify the new `NN-*.md` files exist and are non-empty (`wc -l`).

## Known limitations
- Classification is judgement-based at the HAPPY/UNHAPPY/EDGE boundary; the rules above make it
  consistent but not perfectly reproducible. Counts are ±a few per large file.
- Agents read enough of each body to judge intent, not every line — a determined mislabel (test that
  looks positive but asserts a negative deep in a helper) can slip. Observations flag the suspicious ones.
- "Strongest/weakest file" calls are the auditing agent's opinion, useful as triage leads, not verdicts.
- This is coverage **shape**, not coverage **percentage** — it says nothing about which production
  lines are exercised, only how existing tests distribute across intent types.

## Resuming (remaining ~229 files, 3 buckets)
See `HANDOFF.md` for the current remaining breakdown. In short:
- **A. Co-located DocType controller tests** `verenigingen/verenigingen/doctype/*/test_*.py` — the
  standard Frappe pattern; the tests/-tree sweeps never touch these. Split by doctype groups.
- **B. mijnrood_sync sub-app** + a few stray co-located service tests.
- **C. Remaining `tests/` subtrees** (comprehensive, volunteer, workflows, email, events, www,
  membership, financial, fixtures, and small dirs) + the ~19 loose files directly in `tests/`.
Continue the same wave-of-3–4 pattern; number new reports `33+`.
