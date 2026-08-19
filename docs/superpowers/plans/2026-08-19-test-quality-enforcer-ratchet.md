# Ratchet the Test Quality Enforcer

**Status:** design v2, not yet implemented
**Branch:** `test/quality-enforcer-ratchet` off `6cd33d8d`

> **v2 supersedes v1 after review.** v1 was sound about the problem and wrong about the
> remedy. It proposed "ignore matches inside strings" as a prerequisite — which would have
> silenced roughly half the gate and then generated the baseline from the crippled
> detector, producing a permanently green CI job enforcing nothing. Every number below was
> re-measured on `6cd33d8d`, and every claim about existing code was read rather than
> assumed. The three v1 claims that were simply false are listed in *Corrections to v1*.

## The problem

`scripts/validation/test_quality_enforcer.py` runs at `pre-commit` and `pre-push` with
`pass_filenames: true`, so it only ever judges the files in the change being pushed.
`develop` carries **40 test files that fail it**, and nothing surfaces them.

The gate is dead in both directions. It never reports the standing debt, and it blocks
whoever's push happens to touch one of those 40 files — including anyone merging `develop`
into a branch, since the merge brings those files into the pushed range. That is how it was
found: the merge of `develop` into `fix/mollie-reversal-booking` (#379) could not be pushed,
over `ignore_permissions=True` calls in `test_donation_portal_behavior.py` that arrived with
#372 and that the branch never touched.

Measured, not assumed: run standalone on that file the enforcer exits **1**; on a clean
control file it exits **0**. The finding is real and the rule works. What is broken is that
a rule nobody can satisfy is a rule nobody runs.

### Counts, and why the spec pins a command rather than a number

Two independent measurements of "the debt" disagreed — 174/121/40 against 175/122/41. The
cause is not arithmetic, it is that **there is no single agreed file set** (see D2). So this
spec does not treat any count as ground truth. It specifies the enumeration:

```
_is_test_file() over os.walk('.') with dirs pruned of
{node_modules, .git, __pycache__, worktrees, .claude, archived}
```

which yields **1,398 files**, against **12,574** unpruned. Under that enumeration:
121 unique findings on 120 lines, 174 raw ERROR lines, across 40 files. The step that
locks this down is a pinned-count test (see Testing), landing *before* any baseline.

## What the violations are

Four kinds, from four checks:

| kind | count |
|---|---|
| `PERMISSION BYPASS` | 91 |
| `DATABASE MOCK` | 20 |
| `BUSINESS LOGIC MOCK PROHIBITED` | 8 |
| `MOCK` (in security test) | 2 |

Not one category, which is why this records them rather than fixing them. Many
`ignore_permissions=True` hits are *arrangement* — #372's tests build a donation owned by
**another** donor precisely so the portal can be proven to refuse it. The enforcer
classifies by enclosing function name, so it cannot tell arrangement-inside-a-test from a
bypass that defeats the assertion. Sorting those is per-site judgement.

Concentration: `test_region.py` (22), `test_event_contact_campaign.py` (20),
`test_sepa_mandate_validation_service.py` (18), `test_volunteer_journey.py` (14).

## Five defects that must be fixed BEFORE any baseline is generated

A baseline generated from a broken detector is worse than no baseline: it is a green CI job
that enforces nothing, and the "baseline only shrinks" check is structurally incapable of
noticing, because shrinking is the celebrated direction.

### D1 — Path keys are unnormalized

`file_path` is interpolated verbatim into every finding (`:281`, `:406`, `:428`, `:539`).
`main()` builds paths with `os.path.join(root, file)` over `os.walk('.')` (`:712-716`), so
`--update-baseline` writes `./`-prefixed keys while pre-commit passes bare repo-relative
paths. Every key the hook computes would be absent from the baseline → "new key" → fail.
That is the problem this design exists to solve, reproduced.

**Fix:** a `_rel()` equivalent of `error_swallow_validator.py:353-357`, applied at key
construction, not at print time.

### D2 — `os.walk('.')` has no directory pruning

Measured on the live checkout: `_is_test_file` matches **12,574** files unpruned versus
**1,398** pruned — **11,176** of the difference inside `.claude/worktrees/`, from agent
worktrees. A developer regenerating locally produces a wholly different file from CI's clean
checkout, which makes the drift check unusable.

**Fix:** the sibling's prune set (`error_swallow_validator.py:365-369`). It prunes exactly
six directories, which is strong evidence this trap was already paid for once.

> **Careful:** pruning a directory *named* `archived` does not prune `archived_unused/`,
> `archived_deleted/`, `archived_removal/`. The hook's own `exclude` regex uses
> `archived_.*`. Both the sibling validator (`:126`) and its hook entry (`:263-264`) carry
> written warnings about this coupling.

### D3 — `_find_function_context()` is not a sound key

`:639-647` scans backwards for the nearest line whose `.strip()` starts with `def `. Four
defect classes, all measured against AST truth:

| defect | consequence |
|---|---|
| decorator lines attributed to the **previous** function | systematic — mock findings land on decorator lines by construction |
| module-level code attributed to the last `def` | adding any function above it silently changes the key → spurious failure. This is the exact key-rot that dropping line numbers was meant to avoid |
| nested-`def` bleed | **manufactures a violation**: `test_chapter_membership_validation_edge_cases.py:63` sits in the allowlisted `_ensure_user` but keys to the nested `_apply_role_profile`, which is not allowlisted |
| no class qualification | returns a bare name; v1 called this "qualified" and claimed it was free |

The nested-`def` case also produces a **real key collision today**, covering one genuine and
one manufactured finding — fix either, add one elsewhere, count unchanged, ratchet blind.
`async def` is unhandled (`line.startswith('def ')`); zero occurrences today, moot once
fixed with AST.

**This is the design's central soundness problem, not the key's granularity.**

**Fix:** replace with an AST scope map in the shape of `error_swallow_validator.py:254-267`
(`_qualnames`, yielding `Class.method` and `outer.inner`), keyed by line span **including
`decorator_list`**.

### D4 — Duplicates come from overlapping patterns, not double-scanning

All 53 duplicate lines are `PERMISSION BYPASS`, multiplicity 2. `self.permission_bypasses`
(`:98-105`) lists

```python
r"ignore_permissions\s*=\s*True",                    # [0]
r"\.insert\s*\(\s*ignore_permissions\s*=\s*True",    # [1]  strict subset of [0]
r"\.save\s*\(\s*ignore_permissions\s*=\s*True",      # [2]  strict subset of [0]
r"\.delete\s*\(\s*ignore_permissions\s*=\s*True",    # [3]  strict subset of [0]
```

and the loop at `:496-497` has **no `break`**. Patterns [1]-[3] can never fire without [0]
also firing — they are dead weight.

**Fix at the pattern list** (`break` on first match, or delete [1]-[3]) — *not* at the
output. De-duplicating output leaves the redundant patterns in place, so duplicates return
the moment any message embeds which pattern matched.

> Where de-dup *is* still needed, key it on `file:line:message`. Exactly one location is
> legitimately flagged by two **different** checks — `test_security_setup.py:651`, hit by
> both `BUSINESS LOGIC MOCK` and `MOCK in security test`. A `file:line` de-dup would
> silently drop one. This is also why 121 findings occupy 120 lines.

### D5 — False positives, and the trap in fixing them

Two real false positives:

| FP | cause |
|---|---|
| `test_suspension_api_import_fallback.py:104` — `# This replaces multiple @patch("frappe.db.get_value")` | a plain `#` comment. `_check_permission_bypasses` (`:474`) and `_check_all_mocks_blocked` (`:365`) skip comments; `_check_database_mocks` (`:267-271`) and `_check_never_mock_patterns` (`:423-425`) skip only docstrings |
| `test_permission_bypass_elimination_validation.py:171` — `"NO ignore_permissions=True",` | a single-line string literal in a list. `_docstring_line_numbers` tracks only triple-quoted blocks |

**The trap.** A fix implemented as "blank out string contents before matching" destroys the
gate, because **14 of 18 patterns require a quote**:

```python
r"frappe\.set_user\s*\(\s*['\"]Administrator['\"]"      # 2/6 permission patterns
r"patch\s*\(\s*['\"]frappe\.db\.get_value['\"]"         # 9/9 database_mocks
r"patch\s*\(\s*['\"].*validate_.*['\"]"                 # 3/3 never_mock_patterns
```

Measured: **58 of 120 finding lines match only quote-requiring patterns** and would be
silenced outright.

**Fix:** a uniform comment skip on all four error paths, plus `tokenize`-based string
handling applied **per-token with position matching** — a match is a false positive only
when its span falls inside a `STRING` token that is *not itself the call site*. Blanket
string suppression is forbidden by the numbers above.

## Design

### Baseline

`scripts/validation/test_quality_baseline.txt`, keyed:

```
<repo-relative path>::<qualified name>::<kind>::<count>
```

**No line numbers** — they rot on any edit above them.

`kind` is the fourth segment, added over v1. Measured justification: only **2 of 109** keys
mix kinds today, so this is a cheap improvement rather than a fix — it makes the four rules
independently ratchetable and prevents a "one mock removed, one bypass added" swap. It does
nothing for the 12 keys where a **same-kind** swap is invisible; only line numbers would,
and they rot. Stated plainly so nobody mistakes it for the soundness fix, which is D3.

### Failure rule

Copied verbatim from `error_swallow_validator.py:454`:

```python
new = {k: v for k, v in counts.items() if v > baseline.get(k, 0)}
```

Fires **upward only**. A file absent from a partial scan contributes no key, so a
pre-commit run over a handful of files can never produce a false "count decreased" or false
"new key" verdict. There is no decrease check anywhere; staleness is caught by CI drift
instead. That division of labour is deliberate.

The count half matters: a sixth `ignore_permissions=True` in a function baselined at five
still fails. Presence-only would let one existing violation license unlimited new ones in
the same function.

### `--update-baseline` must ignore passed filenames

The sibling hardcodes its scan roots in that branch (`:441-445`), precisely so a pre-commit
invocation cannot truncate the baseline to the changed files. v1 said "matching the sibling
validator's interface" without naming this; it is the single most destructive way to get
the interface wrong.

### Pragmas

**No new pragma.** The baseline is already an escape hatch, and unlike a pragma it is
visible in a diff and countable.

But v1's rationale for that was wrong in both directions, so the real situation is recorded
here instead:

- The sibling's `# swallow-ok:` **is policed today** — `VALID_REASONS = {"best-effort",
  "caller-checks", "false-positive"}` (`error_swallow_validator.py:170`), enforced through
  `bad_pragmas` to a non-zero exit. #384 *fixed* that hole; v1 cited the fixed state as a
  reason to avoid pragmas.
- The enforcer **already has an unpoliced escape hatch**, in a blocking path:
  `_check_all_mocks_blocked` (`:385-404`) skips any infrastructure-classified mock with
  `# Mock justified:` / `# External service` / `# Infrastructure` within ±3 lines. No reason
  vocabulary, no validation — `# Infrastructure` alone silences it. **Measured: 361
  occurrences across 77 files.**

**Consequence for this change:** the baseline is generated with that hatch active, so the
recorded number **understates** the debt by whatever those 361 comments suppress. The
baseline header must say so. Policing that hatch is a follow-up, not this change — it would
change the finding count and must not be entangled with generating the baseline.

### Where it runs

| stage | scans | rationale |
|---|---|---|
| `pre-commit` / `pre-push` | changed files only (`pass_filenames: true`, unchanged) | fast; today's behaviour minus the false blocks |
| CI (new job) | all 1,398 test files | a ratchet nobody runs whole is not a ratchet |

Hook scope must stay a **subset** of baseline scope, or files the hook sees produce keys the
baseline never recorded. Today the hook's `exclude` (`.pre-commit-config.yaml:77-87`) makes
it a strict subset; D2's pruning must preserve that, minding the `archived` vs `archived_*`
mismatch above.

### CI wiring — three steps, not two

Mirroring `.github/workflows/code-validation.yml:130-184`:

1. **ratchet check** — run the validator, fail on new/raised keys
2. **drift check** — re-run `--update-baseline`, fail if the file changed
3. **baseline did not grow** — the *only* enforcement of this design's own promise that the
   file must only ever shrink. v1 omitted it, leaving that promise living in a header
   comment and nothing else.

Blocking from day one, like the sibling. The baseline neutralises existing code, so arming
it affects nothing that exists.

**Inherited caveat, recorded not fixed:** step 3 auto-passes any PR that touches the
validator (`:168-172`). The introducing PR is therefore unguarded by construction, and any
later PR touching `test_quality_enforcer.py` gets a free pass to grow the baseline.

## Testing

`scripts/validation/tests/test_test_quality_enforcer.py`, mirroring
`test_error_swallow_validator.py`:

| case | expectation |
|---|---|
| violation absent from baseline | fails |
| violation present in baseline | passes |
| count rises above a baselined key | fails |
| match inside a string literal that is not a call site | **not** a finding |
| match inside a `#` comment | **not** a finding |
| `set_user("Administrator")` — quote-requiring pattern | **still** a finding |
| real violation on a line that also carries a trailing comment or string | **still** a finding |
| one site matched by two subset patterns | reported once |
| one line matched by two **different** checks | reported twice |
| key for a finding on a decorator line | attributes to the decorated function |
| key for module-level code | does not attribute to the last `def` |
| **pinned totals** | ≈121 findings / ≈109 keys over the pruned enumeration |

The pinned total is the control that matters. Without a hard number, the three
false-positive cases are all satisfied by an enforcer that finds **nothing** — which is
exactly how v1 would have failed. It lands **before** any baseline is generated.

## Landing order

1. Normalise path keys (`_rel`); prune the walk — **D1, D2**
2. Replace `_find_function_context` with an AST scope map including decorators — **D3**
3. Fix duplicates at the pattern list — **D4**
4. Fix false positives narrowly; **pin the finding count in a test** — **D5**
5. Only then generate the baseline and arm all three CI steps

Steps 1-4 are behaviour changes to a validator with no baseline, so each is independently
verifiable against the pinned count. Step 5 is mechanical once they hold.

## Explicitly not in scope

- **Fixing the 121 violations.** Per-site judgement; the baseline header will say the file
  must only ever shrink.
- **Policing the existing `# Infrastructure` hatch.** It would change the finding count.
- **The step-3 validator-touch exemption.** Inherited from the sibling; recorded above.

## Corrections to v1

Three v1 statements were not merely optimistic, they were false about the code. Recorded so
the same reasoning is not repeated:

1. **"`_docstring_line_numbers()` is simply not applied on the permission-bypass and mock
   paths."** It *is* applied on all four error paths — `:265/270`, `:303/367`, `:421/424`,
   `:459/474`. The real causes are a plain `#` comment on two of the four paths, and
   single-line string literals which no path handles. v1 named the wrong mechanism and
   therefore prescribed the wrong fix.

2. **"The `# swallow-ok:` pragma was unpoliced, so avoid pragmas."** It is policed today
   (`VALID_REASONS`, `error_swallow_validator.py:170`). #384 *fixed* it. v1 cited a fixed
   state as evidence against pragmas, and simultaneously missed that this enforcer already
   carries an unpoliced hatch of its own, used 361 times.

3. **"`_find_function_context()` already computes the enclosing function, so the key costs
   nothing."** It computes *a* name, wrongly, in four measurable ways, and without class
   qualification — see D3. The key costs an AST scope map.

The common thread: each was a claim about existing code that would have taken one `grep` to
check, asserted from the shape of the sibling validator instead. The measurements in this
document were run, not inferred.

## Success criteria

1. `git push` of a `develop` merge no longer fails on code the branch did not touch —
   verified by pushing the #379 merge that motivated this.
2. A newly introduced `ignore_permissions=True` in a test body still fails the gate —
   verified by a test.
3. `set_user("Administrator")` is still detected after the false-positive fix — verified by
   a test, because this is the failure mode v1 would have shipped.
4. `--update-baseline` on a clean checkout produces no diff, and the same file on a checkout
   with agent worktrees present.
5. CI reports the standing debt as a number that can be watched going down.
