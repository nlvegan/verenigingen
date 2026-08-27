# 2026-08-26 — the gate that accused the correct fix

One PR merged: **#590** (`316704cc7`, closes **#586** and **#588**). Three commits, and the
second and third exist only because two pre-merge audits found real problems — the second
of them a defect **I introduced while fixing the first**.

The pattern from `2026-08-25b` and `-25d` held again, and tightened: **every measurement I
made survived; almost every sentence I wrote next to one did not.** What is new is the
sharpest failure of the session, which was not a wrong number but a wrong *design*: a gate
that punished the correct action.

---

## The lead: a gate that reddens on the right answer is worse than no gate

#586's durable half is `--check-shrink`: a baseline entry that LEAVES the ratchet must say
why, because nothing distinguished "this swallow was fixed" from "this swallow became
unrecognisable" — the printed remedy is `--update-baseline` and the diff shows a REMOVED
line, so both read as progress.

I gave it three reasons. One of them, `silent` ("the logging call was DELETED"), ran its
structural check over **every** handler in the shrinking function rather than only ones
that had been counted. Consequence, demonstrated on real code: apply the **correct** fix to
`invoice_helpers.py::auto_create_ledger_mapping` — turn one `return None` into `raise` —
and the gate went red naming an **untouched sibling 200 lines away**, asserting a deletion
that never happened.

Measured as a class, not an instance: **2 of 435** baselined functions carry a never-logging
falsy sibling. And `explain_shrink`'s own docstring asserted this was impossible — a
sentence that was true only of a survivor that still *logs*, which the same commit had just
stopped requiring.

I tried four predicates to separate the cases. Each was provably ambiguous, because
**deleting a log call and "this function always had a silent sibling" produce identical
head trees.**

> **When two causes are indistinguishable from the data you have, the fix is an INPUT, not
> a predicate.** And until you have that input, **refuse to report the reason** rather than
> guess it. A gate that punishes the correct action is how a ratchet dies — people learn to
> add pragmas reflexively.

So the gate now takes `--base-tree`, a checkout of the base commit, which CI materialises
with `git worktree add --detach "$RUNNER_TEMP/base_tree" "$BASE_SHA"`. Without it the
`silent` reason is not reported at all and the run says so.

Two further things that arm taught:

- **Match base↔head by a line-independent fingerprint, never by position.** A positional
  slice gets the COUNT right and the HANDLER wrong. The fingerprint is the exception type
  plus the unparsed return expressions.
- **The gate is deliberately NOT exempted when the validator changes**, unlike the sibling
  "did not grow" gate. A validator PR is exactly where a detection rule gets narrowed by
  accident, and this is the only step that would say so. Measured: widening the falsy test
  is silent, refactors are silent, only a *narrowing* reddens it.

---

## What the measurement refuted before any of that

#586 asked for a measurement first, and it moved the fix twice.

The issue framed the choice as "a one-line widening or a design change". Neither, as posed:

| every return in the handler is… | handlers |
|---|---|
| a call with ≥1 arg, all falsy literals — the shape the issue named | **1** |
| a zero-argument call | 10 |
| a `Name` bound to a module constant | 2 |
| a non-empty dict (`{"success": False, "error": str(e)}`) | 528 |

The widening is a population of **one**. The two `Name`-constant sites turned out to be
*deliberate* explicit-failure sentinels — `RECURRING_STATE_UNKNOWN`, `_READ_FAILED` — each
carrying a comment saying why it is not `None`. **They are the remedy, not the bug.**

And the issue's own suggested rule — *"the call's arguments are all falsy"* — is refuted by
one fact:

> **`all([])` is True**, so that rule is satisfied **vacuously by any argument-less call**.

Measured against the shipped rule it ADDS **7** false findings (`to_dict()`,
`get_fallback_cost_center()`, `_get_empty_statistics()`, `self._load_payment_history_original()`)
— and, the half nobody checks, **REMOVES 6** findings that were in the baseline, because
`_is_falsy_return` also feeds condition (5). Widen it and a function whose only real return
is `settings.as_dict()` reads as *never returning a real value*, so its whole swallow
vanishes. The suggested fix would have **committed the disease #586 exists to stop, on 6
sites.**

> **When widening a predicate, measure BOTH directions.** The two arms that shipped were
> verified to remove nothing.

---

## #588, found by refusing to accept an unexplained instrument reading

Two of my own runs disagreed on the *function* count at an **identical** site count. That
is the whole finding: I could have shrugged, and the numbers I needed were unaffected.

`templates/pages/me.py` is a **symlink** to `member_portal.py` — the only symlinked `.py`
under either scan root. `os.walk` yields both, and `_rel()` keys findings by
`path.resolve()`, so the same file was parsed twice and merged onto one key. All four of
that file's swallows were recorded as `::2` where the tree has one each, and the gate fires
on `count > baseline`: **four free slots** in exactly the four functions being watched.

Neither of the guard's own gates could see it. The doubling is **deterministic**, so
"baseline is in sync" regenerates the same inflated file; "baseline did not grow" compared
totals inflated on **both** sides. Same `::2` *symptom* as #581, different cause.

`failed_write_validator` walks the same collision (3227 files, one symlink, one same-target
pair) and is latent only for want of a finding in that file. Both fixed **at the build site
(`_iter_py`)** rather than the symptom (`_rel`), so the file is parsed once instead of
parsed twice and merged.

---

## Process traps — three that made a FAILED check look like a passed one

These are the ones to carry; each cost real time and each was silent.

- **`grep -c` exits 1 when the count is 0.** My mutation loop was `n=$(run) && printf …`
  with `run()` ending in `grep -c`. Every **surviving** mutant made grep exit 1,
  short-circuited the `&&`, and printed **nothing** — so four genuine gaps read as "anchor
  problem". Use `grep -E … | wc -l`, and print SURVIVED explicitly rather than inferring it
  from absence.
- **`_own_nodes()` pops its stack from the end**, so handlers come back in roughly
  **reverse** source order. A test asserting the right handler was reported **passed under
  a positional-slice mutation**, because the slice happened to pick the last-in-source one.
  Fix: put the decoys **first AND last** in source order, then it kills both directions.
- **A control whose mutation never applied.** I probed for a logging call with
  `390 < lineno < 400` and missed an 8-line `frappe.log_error(` spanning 405–412, so the
  mutation was a no-op and the gate's silence proved nothing. **Assert the mutant differs
  from the original** before reading the result.

One more, from the audit: deleting an `except` line to simulate a change is a
**SyntaxError**, and `explain_shrink` treats an unparseable file as self-explaining — so it
exonerates *every* entry in that file. Nothing else in CI would let that land, but the
mutation proved nothing.

---

## What the two audits changed

Both were dispatched under the standing permission, the second specifically because
**#492 shipped four false claims in a review-response commit** — the round that answers a
review is itself unreviewed.

**Audit 1** (on the first commit) found the `silent`-arm precondition (H1 above), a file
leaving the SCAN being invisible (`unscanned`; measured, excluding `templates/` dropped 10
baselined entries and reported **0**, dropping the `scripts` root dropped 33 and reported
0), and — stingingly — that I had applied *"a finding is a class"* to `_iter_py` and **not
to my own explanation**. The sentence I wrote, *"a falsy-MEANING sentinel is not a
falsy-SHAPED literal"*, is a search query and I had not run it. A non-empty **sequence** of
only falsy literals is the same shape one step out: **3** live sites, flagship
`MT940Import.get_transaction_date_range`, whose handler's `return None, None` sits **four
lines below** an identical `return None, None` meaning "no transactions in range" — and it
logs through `frappe.logger()`, which reaches nobody in CI.

**Audit 2** (on the commit that answered audit 1) confirmed every quantitative claim and
found the new defect, plus **four stale prose claims inside the functions that commit had
just rewritten** — including the module docstring sentence the same commit made false, in
the first prose a reader meets — and **six untested branches**, two of which were the
"passes for the wrong reason" class the commit itself claimed to have found twice.

> **Rewriting a function makes the prose around it a claim you just changed.** Re-read the
> docstring of anything you touch, and the module docstring if the behaviour it advertises
> moved.

Two of my own numbers were also wrong, and re-measuring them made the argument stronger:
"1 true positive against 10 false positives" was wrong *on its own code*, and "936 sites
tree-wide" is not reproducible from any reading of the predicate it sat beside (the real
figures: +7/−6, and 483 handlers in 462 functions). Both audits' own figures also needed
re-deriving — they were measured against the pre-fix state — so the shipped docstrings
carry **my** measurements with the predicate and scope named.

---

## State

| | |
|---|---|
| **#590** | **merged** `316704cc7` — closes #586 and #588 |
| **#586** | closed — `_is_falsy_return` widened on two measured arms; `--check-shrink` with three reasons and `--base-tree` |
| **#588** | closed — symlink double-count, 4 phantom ratchet slots; fixed in both validators |
| **#589** | **open** — a dict whose every value is a falsy literal: 8 sites, one of them a permission dict. Deliberately not ridden along |

Baseline **449 → 449**: same total, **4 phantom slots out and 4 real sites in.** 61
swallow-validator tests (was 43), 194 across `scripts/validation/tests` (was 176). Ten
mutants planted and killed after audit 1; nine more after audit 2, of which **one
survived** — a positional match for the newly-silent handler — and is now killed in both
slice directions.

`develop`: `98003ca45` → `316704cc7`.

**28/28 checks green — and 28 is the complete set for this diff, not a partial one.**
`server-tests.yml` is `paths`-filtered to `verenigingen/**` and `pyproject.toml`, and this
PR touches only `scripts/validation/`, `code-validation.yml` and `.pre-commit-config.yaml`,
so the sharded app suite legitimately did not run. **#574's "43/43 with 12 shards" is not
the bar for a tooling-only PR** — check the paths filter before reading a smaller number as
a partial pass.

The new CI step was verified to have actually executed, not skipped: its log shows
`Preparing worktree (detached HEAD 98003ca4)` and then the real verdict line, with the
"no --base-tree" note **absent** — so the flag was passed and the step did not pass
vacuously through its `git cat-file -e` guard.

---

## For whoever picks this up

1. **#589** is the direct follow-up, and it needs a decision rather than a fix: 8 handlers
   return a dict whose every value is a falsy literal. A non-empty dict is the shape this
   validator has **always** let through on purpose, because `{"success": False, "error":
   str(e)}` is the remedy it prints. Read
   `chapter_query_service.py::get_user_permissions_optimized` first — it returns an
   all-`False` **permission** dict, which fails *closed* (so not the PR #191 incident
   repeating) but still cannot tell "no rights" from "the roles query failed".
2. **Two known false alarms in `--check-shrink`, both currently empty, both documented in
   `_returns_the_cause`.** A genuine fix returning `frappe.get_traceback()` with no `as`
   binding is reported, and so is a container holding the BARE bound name (`{"error": e}`).
   Checked as a class: `"error": e` occurs **0** times against **719** of
   `"error": str(e)`, so the exposure is real and unrealised. If either starts firing,
   widen `_returns_the_cause` rather than pragma the site.
3. **The explainer shares the detector's structural predicates**, which is deliberate — two
   copies of that ladder means adding a condition to the detector silently stops the
   explainer explaining. The cost is that narrowing `_is_broad` or `LOG_NAMES` is invisible
   to the gate. It sees a narrowing of the falsy test, which is the heuristic that has now
   been widened three times.
4. **58 stale git worktrees** from earlier sessions are still registered on this repo, all
   under `/tmp/claude-1000/…/scratchpad/`. Harmless to the validators (they are outside the
   repo tree, and `_iter_py` excludes a `worktrees` dir anyway), but `git worktree list` is
   unreadable and `git worktree prune` would tidy it.
5. Still open from previous sessions and untouched here: **#505** (guard and swallow one
   frame apart), **#576**, **#570**, **#572**, and **#545**, which still blocks all
   vendor-side Mollie verification. **#581**–**#584** are also open but belong to the
   bank-account / SEPA-mandate line from #575 and #585, not to this one — `2026-08-25d`
   is their handoff.
