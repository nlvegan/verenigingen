# Ratchet the Test Quality Enforcer

**Status:** design approved, not yet implemented
**Branch:** `test/quality-enforcer-ratchet` off `6cd33d8d`

## The problem

`scripts/validation/test_quality_enforcer.py` runs at `pre-commit` and `pre-push` with
`pass_filenames: true`, so it only ever judges the files in the change being pushed.
`develop` today carries **40 test files that fail it**, and nothing surfaces them:

| | |
|---|---|
| test files in scope | 1,444 |
| files failing on `develop` (`6cd33d8d`) | 40 |
| raw ERROR lines | 174 |
| unique `file:line:message` | 121 |

The gate is therefore dead in both directions. It never reports the standing debt, and it
blocks whoever's push happens to touch one of those 40 files — including anyone merging
`develop` into a branch, since the merge brings those files into the pushed range. That is
how it was found: the merge of `develop` into `fix/mollie-reversal-booking` (#379) could not
be pushed, over `ignore_permissions=True` calls in `test_donation_portal_behavior.py` that
arrived with #372 and that the branch never touched.

Measured, not assumed: run standalone on that file the enforcer exits **1**; on a clean
control file it exits **0**. The finding is real and the rule is working. What is broken is
that a rule nobody can satisfy is a rule nobody runs.

## What the violations actually are

Not one category, which is why this records them rather than fixing them:

- **~30** `frappe.set_user("Administrator")` inside test bodies.
- **~60** `insert`/`save(ignore_permissions=True)`. Many are *arrangement* — #372's tests
  build a donation owned by **another** donor precisely so the portal can be proven to
  refuse it. The enforcer classifies by enclosing function name, so it cannot tell
  arrangement-inside-a-test from a bypass that defeats the assertion.
- **~25** `with patch(...)` mock-abuse hits, 18 of them in
  `tests/sepa/test_sepa_mandate_validation_service.py`.
- **Several false positives** matching inside strings and comments — the literal
  `"NO ignore_permissions=True"` and the comment `# This replaces multiple @patch(...)`
  are both counted as violations.

Concentration: `test_region.py` (22), `test_event_contact_campaign.py` (20),
`test_sepa_mandate_validation_service.py` (18), `test_volunteer_journey.py` (14).

## Design

Follows `error_swallow_validator.py` + `error_swallow_baseline.txt` exactly — same key
shape, same flag, same CI wiring. No new concept enters the repo.

### 1. Fix two enforcer defects BEFORE generating the baseline

A baseline that encodes bugs can never be cleanly shrunk, so these land first:

1. **De-duplicate findings.** 53 of the 174 raw lines are exact duplicates of another
   line — same file, same line number, same message.
2. **Ignore matches inside strings and comments.** The class already has
   `_docstring_line_numbers()` for exactly this; it is simply not applied on the
   permission-bypass and mock paths.

### 2. Baseline file

`scripts/validation/test_quality_baseline.txt`, keyed as the swallow ratchet is:

```
<path>::<qualified function>::<count>
```

**Line numbers are deliberately absent** — they rot on any edit above them. The enforcer
already computes the enclosing function via `_find_function_context()`, so the key costs
nothing to produce.

Regenerated with `--update-baseline`, matching the sibling validator's interface.

### 3. Failure rule

A run fails if it finds:

- a key **not** present in the baseline, **or**
- a **higher count** for a key that is present.

The count half matters: a sixth `ignore_permissions=True` in a function baselined at five
is still caught. Without it, one existing violation would license unlimited new ones in the
same function.

### 4. No opt-out pragma

The swallow validator has `# swallow-ok: <reason>`, and #384 found that pragma was
**unpoliced** — `# swallow-ok: i just do not feel like it` silenced a finding. The baseline
is already an escape hatch, and unlike a pragma it is visible in a diff and countable. A
second, unpoliced one would rebuild the hole this repo just closed.

### 5. Where it runs

| stage | scans | rationale |
|---|---|---|
| `pre-commit` / `pre-push` | changed files only (`pass_filenames: true`, unchanged) | fast; today's behaviour, minus the false blocks |
| **CI (new job)** | **all 1,444 test files** | a ratchet nobody runs whole is not a ratchet |

The CI job is **blocking** from day one, mirroring the Swallowed-Exception Guard. The
baseline means no existing code is affected by arming it.

It also carries that guard's **drift check**: CI re-runs `--update-baseline` and fails if
the file changes, so a stale baseline cannot sit unnoticed.

### 6. Tests

`scripts/validation/tests/test_test_quality_enforcer.py`, mirroring
`test_error_swallow_validator.py`:

| case | expectation |
|---|---|
| violation absent from baseline | fails |
| violation present in baseline | passes |
| count rises above a baselined key | fails |
| match inside a string literal | **not** a finding |
| match inside a comment | **not** a finding |
| duplicate detections of one site | reported once |

The last three are the controls. Without them "false positives fixed" is
indistinguishable from "detection broken" — which is the failure mode this repo keeps
recording.

## Explicitly not in scope

This does **not** fix or judge the 121 violations. Some are genuine mock abuse worth
removing; others are legitimate arrangement the rule over-reaches on. Sorting them is
per-site judgement and belongs in its own work. The baseline header will say so, and will
say the file must only ever shrink.

## Success criteria

1. `git push` of a `develop` merge no longer fails on code the branch did not touch.
2. A newly introduced `ignore_permissions=True` in a test body still fails the gate —
   verified by a test, not by inspection.
3. CI reports the standing debt as a number that can be watched going down.
4. `python scripts/validation/test_quality_enforcer.py --update-baseline` on a clean
   checkout produces no diff.
