# Handoff — 2026-08-27: the comment I wrote was the search query

One PR, **#604** (issue #597), merged. It took **three rounds** to close what I twice
announced as closed, and the pattern in the misses is more useful than the fix.

CLAUDE.md already carries the rule I broke:

> **If the fix deserved an explanation, that explanation is a search query.** Grep the
> explanation.

I quoted that rule *in a code comment I wrote*, and did not run it on my own sentence. The
sibling was **in the same file I was editing, ~140 lines below the function I fixed.**

## The shape of the miss

#597 listed 8 sites; #598 had fixed 4. I fixed the other 4 plus two "near-relatives" and
said the class was done.

| round | found by | what it added |
|---|---|---|
| 1 | me, from the issue | 4 sites + 2 near-relatives. Claimed closed. |
| 2 | skeptical review | 3 more, **all on the unattended path**, one proved end-to-end. Claimed closed. |
| 3 | a whole-codebase sweep I should have run first | a **daily scheduled job** the reviewer had not named either |

Round 2's finding is the one to read. The sites I fixed populate the batch UI's invoice
**selector** — a human reads that list before submitting. The reviewer's point was that the
severity ordering was inverted: the unattended paths matter more, and one of them
*multiplies rows* rather than picking the wrong one. Measured, with a control, on a member
built entirely with ordinary `save()`:

```
PROBE[one-membership-mandate]      rows=1 -> [('ACC-SINV-2026-00052', 'TST0019E4076')]
PROBE: donation mandate inserted Active=Active
PROBE[plus-donation-only-mandate]  rows=2 -> [('ACC-SINV-2026-00052', 'PROBE-DON-801e92'),
                                              ('ACC-SINV-2026-00052', 'TST0019E4076')]
```

A €25 invoice became two Direct Debit Batch rows, both legs on the **donation-only** IBAN.

Round 3 only happened because I stopped patching the sites a reviewer named and asked a
different question: *enumerate every Active-mandate resolution in the app and classify it.*
That found **52 purpose-blind sites, 23 scoped, 75 total** — and among the 52, a job
registered at `hooks/scheduler.py:58` running **daily** with the same row-multiplying join.

> **New rule: when a reviewer finds a sibling you missed, do not fix that sibling. Build the
> census.** Two rounds of "the reviewer named three, I fixed three" is what produced a third
> round.

Most of the 52 are correct as they are — counts and monitoring, termination (which *should*
reach every purpose), and lookups keyed on `iban`/`mandate_id` rather than on member. The
final claim in the PR is deliberately narrower than "done": **every double-debit shape I can
measure is fixed.** The rest is enumerated in **#605** rather than asserted away.

## The premise, and why #597's own severity section was backwards

#598 did **not** establish "one Active mandate per member". It established one per member
**per purpose** — `validate_single_active_mandate_per_purpose`. Probed directly, no bypass:

```
membership mandate accepted: g332r5ugvg        (used_for_memberships=1)
donation   mandate accepted: g394jsa6er        (used_for_donations=1)
second membership mandate REJECTED: ValidationError
  "already has an active SEPA mandate for memberships: PRB-8e299c3b"
```

So every remaining site — `status = 'Active'` with no purpose filter — was ambiguous **by
construction** for anyone who both pays dues and donates, not defending an unreachable
state. That inverts the issue's severity note, and it is why the fixtures need no
`frappe.db.set_value`: both mandates are legitimately Active. `test_the_ambiguous_state_is_reachable`
is the control, and it is the one test that correctly **survives** mutation, because it pins
the fixture shape rather than the fix.

This too was already diagnosed in-repo and never grepped:
`payment_history_service._get_default_mandate` carries a docstring explaining that the
generic helpers "pick the single most-recently-created ACTIVE mandate with **NO purpose
filter at all**" — and fixed only its own call site. Meanwhile
`financial_mixin.get_financial_summary` gates on `has_active_sepa_mandate()`, which *is*
memberships-scoped, then reported the **donation** mandate's id/status/expiry as the
membership one.

## Two tests of mine that did not discriminate

Both passed while the defect they describe was present. Neither was caught by running them.

**1. A mutation that silently did not apply.** I re-introduced the log-before-blank defect
with a string replace, asserted the pieces were present, ran the test, and got `OK` — and
concluded my test was inadequate. The file had never changed: I asserted the *operands*
existed, not that the *replacement* happened.

```python
assert LOG + BLANKS in s          # passes
s2 = s.replace(LOG + BLANKS, BLANKS + LOG, 1)
assert s2 != s, "REPLACEMENT DID NOT APPLY"   # <- the one that matters
```

With the mutation actually applied the test failed as intended. **A mutation you did not
verify changed the file is not a control; it is a second copy of the original run.**

**2. `tabError Log` is MyISAM, and test member names repeat.** The test read "the newest
Error Log naming this member" and asserted both colliding mandate ids appeared. Error Log
rows are non-transactional, so they survive the teardown rollback, and member names recur
across runs — so it was reading a log written by an **earlier green run of the same test**.
Scoped to rows that did not exist before the call, it now fails on the defect:

```
AssertionError: 'PURP-DUP-1f48ef26' not found in
  '... Candidates: None (None), TST001801C01 (NL58 ABNA 0000 0000 01).'
```

The defect it catches was mine: `candidates[0]` **is** the dict being blanked, so logging
after blanking destroyed half the evidence the refusal exists to carry.

## The red shard that was not the code

Shard 8/12 failed on `test_validate_invoice_mandate_single_query` — a query-count bound on
code this branch does not touch. Grepping the shard log for my module and for every error
string my change can produce: **zero hits**, which ruled out my code before any other
analysis. The three queries were:

```
1. SELECT name FROM tabMember WHERE name=… LIMIT 1
2. SELECT column_name FROM information_schema.columns WHERE table_name='tabSEPA Mandate'
3. SELECT … FROM tabSEPA Mandate WHERE member=… AND status='Active' AND used_for_memberships=1
```

Query 2 is `Database.get_db_table_columns` (`database.py:1346`) missing its cache and issuing
an introspection **inside the open `assertQueryCount` window**. That cache is
`frappe.client_cache` — **Redis-backed, shared across processes, surviving between runs** —
so whether it fires depends on whether anything earlier in the shard touched that table, and
**shard bins re-pack whenever any test file is edited**. I edited test files. Same assertion,
`✔` on #598's head in the archived shard-8 log.

`setUp` already warmed caches "so the count measures only the business SQL" — but it warmed
`get_meta` for four doctypes and the *table-info* cache for Sales Invoice only, never the
*column list*. They are separate caches.

Reproduced with **one Redis key**, no branch and no CI:

```
frappe.client_cache.delete_value("table_columns::tabSEPA Mandate")
→ FAILED  AssertionError: 3 not less than or equal to 2
# after the fix: OK, twice, each from a freshly cleared cache
```

**I had filed this as #608 a few hours earlier calling it "a local-vs-CI parity artifact".
That was wrong** — it is one mechanism in both environments, and this bench's Redis simply
happened to be warm for one measurement and cold for the others. #608 now carries the real
diagnosis.

## Two claims of mine the review killed

| my claim | how it died |
|---|---|
| "`get_active_mandates_for_members` is whitelisted, so reachable from outside the app" — used to justify both the guard *and* fixing a caller-less helper | `frappe.get_attr` splits on the **last dot only**, so `@frappe.whitelist()` on a staticmethod inside a class cannot be dispatched: `ModuleNotFoundError: … 'optimized_queries' is not a package`. The decorator is inert. Guard kept — correct and free — but the stated reason was false. |
| "the `payment_mixin` gate now stops a misleading warning for donation-only members" | the whole body sits inside `if not hasattr(self, "payment_method")`, and Member **has** that field. Measured `True` for `new_doc` and for a loaded doc. The block has never run; the edit was reverted. |

## What landed

| | | |
|---|---|---|
| **#604** | issue #597 | **merged** — purpose-scoped mandate resolution across 10 production files; 25 new tests |

`develop`: `1d90b3bb1` → `bcf07e754`. Merged green.

Also merged at session start: **#598** (issue #584) as `5f7ee8b1d`, **#599** (handoff) as
`1d90b3bb1`.

Filed: **#605** (the enumerated 52-site remainder, classified), **#606** (Direct Debit Batch
accepts the same invoice twice; `validate_sequence_types` has a comment claiming another
function catches it, which it does not — plus an all-purposes-zero mandate that escapes the
per-purpose guard), **#607** (a validation that has never run; two swallows left behind that
`get_default_mandate` still routes through; a refusal rendered to members as "SEPA not
configured"), **#608** (root-caused above, closed by this PR).

## Verification, and what it is worth

- 25 new tests; **16 affected existing suites** re-run green.
- **Mutation-verified** against `develop`'s production code: **23 of 24 failed** at the
  24-test point (survivor: the fixture control). The 25th test — the secure twin's ambiguity
  path — was verified individually against the defect re-introduced *in the secure copy*, not
  as part of that whole-file run.
- Codecov earned its place once: it put `sepa_batch_ui_secure.py` at **58.8%** patch coverage
  and the uncovered lines were **exactly** the ambiguity path — the one this PR had already
  had to fix in both copies while testing only one. An untested duplicate is how the defect
  reached the second copy.

## For whoever picks this up

- **#606 is the live one.** #604 removed the routinely-reachable duplicate; it did **not** add
  a duplicate-invoice guard, so a duplicate arriving any other way still becomes two debits.
  `validate_sequence_types` silently skips rows with no `mandate_reference` under a comment
  saying `validate_invoices` catches them. It does not.
- **#605 is a census, not a task list.** Read the "correct as they are" section before
  changing anything in it — scoping the termination sites would leave a terminated member's
  donation mandate Active.
- `mandate_candidates.resolve_purpose_flag` now accepts both vocabularies
  (`"memberships"` and `"used_for_memberships"`) and raises otherwise. Before it,
  `has_active_mandate` **silently applied no filter** for an unrecognised purpose — so
  handing it the spelling every resolver uses answered "does this member have *any* Active
  mandate".
- Only `None` means "any purpose". `""` and `0` raise. That is deliberate: the first draft
  guarded with `if purpose and …`, so `purpose=cfg.get("x") or ""` silently restored
  purpose-blind resolution.
- If a query-count test reddens on a branch that cannot have changed the count, clear
  `table_columns::tab<DocType>` and see whether it reproduces before looking at the diff.
