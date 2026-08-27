# Handoff — 2026-08-25b: the rule that went dead when I finished the job

Two PRs, both merged: **#378** (issue #254) and **#574** (issue #561). Both went through the
skeptical review. In both, **the review confirmed every measurement I made and refuted my
explanations** — three on the first, four on the second — and in both, a check I had written
myself turned out to have no failing branch.

The measurements were fine. The sentences next to them were not. That is now three sessions
running, and it is worth reading as a pattern rather than as two incidents.

## The sharpest one: a ratchet that fixing everything switched off

#561's ratchet had two rules: (1) the savepoint rollback must go through the shared helper,
(2) a *swallowing* catch-all needs an `except NON_RESUMABLE_DB_ERRORS: raise` above it.

Rule 2 was gated on rule 1 — a handler was only checked for the missing guard if it *also*
still wrote the rollback by hand. So converting all 22 sites to the helper made **rule 2
unreachable across the entire app**. The reviewer planted the exact shape the ratchet's own
failure message tells you to write — helper + swallow + no guard — into a real production
file and ran it: **11/11 green**, on a ratchet whose docstring read *"15 handlers were fixed;
this is what stops the sixteenth."*

This is a different failure from 2026-08-22's (which read the `except` clause and never the
body). The new rule:

> **A ratchet whose predicate mentions the OLD spelling dies the moment you finish the
> migration.** Gate on the union of old and new spellings; only *report* the old one.

Three more holes in the same walker, all found by *probing* it rather than reading it:

| planted | why it has to be caught |
|---|---|
| `raise Wrapper(str(e))` counted as "re-raises" | **that IS #561's own defect written by hand** — replacing the exception defeats every type-keyed guard exactly as the 1305 does |
| `rollback(); if not critical: return None; raise` | a conditional swallow under a trailing raise |
| `except te.NON_RESUMABLE_DB_ERRORS:` and the two classes spelled out | **false NEGATIVE** — the one site that had got this right first was about to be reported as unguarded |

And rule 3's first draft — "a `try` containing a rollback" — matched every operation-wide try
that rolls back on an early return. **4 false positives, which is how a ratchet teaches people
to add exemptions reflexively.** Tightened to "every statement in the try body is a savepoint
call".

## The explanations that were never measured

Every one of these was checkable in under a minute, and each was written from reading rather
than from asking the system.

| my claim | how it died |
|---|---|
| "skipping customer creation would drop Mollie linkage" (#378) | **the file I cited refutes it** — `mollie_sync_service.py:56-59` creates the Customer itself when one is missing |
| "all three importers roll the row back" (#378) | one of three has **no savepoint at all**; it commits the row it reports `"skipped"` → **#570** |
| "msgprint reaches nobody in a background job" (#378) | `_bulk_context` sets that flag for **every** caller, including a foreground desk button |
| "the two mt940 copies this replaces" (#574) | one was replaced; the other was **twelve lines above it** |
| "20 hand-written rollbacks" (#574) | **22**, diff-counted |
| "let the job be retried" (#574) | there is no job — it runs synchronously; the retry comes from the gateway seeing HTTP 500, and whether it retries is the vendor's policy, which I had asserted and not verified |

The tell is the same every time: I measured the symptom on the path in front of me, then wrote
the general sentence from reading. **A justification that names a file is a claim about that
file — open it.**

## What landed

| | | |
|---|---|---|
| **#378** | issue #254 | **merged** — a failed Customer no longer destroys the Member on interactive/guest paths; bulk imports still hard-fail so their per-row reporting stays honest. Also fixes a *develop* bug: a deadlock was arriving as `ServiceError(1305)` |
| **#574** | issue #561 | **merged** — `rollback_to_savepoint()` + `release_savepoint_if_present()`, 22 rollbacks converged, 16 guards, a 3-rule ratchet sharing its AST predicates with #470's |

`develop`: `a394f613` → `1ef89531` (#378) → `9404e5392` (#574). Both green at merge; #574 was
**43/43 with 12/12 shards**, which is the number that mattered — see the risk note below.

Filed: **#570** (Member Import commits the row it reports "skipped"), **#572** (eBoekhouden
swallows a 1213 into `debug_info`; marked with its reason, not converted).

## The mechanism, for whoever meets it next

A 1213 destroys **every savepoint in the transaction**. Measured on test_site_1 with two
contending connections, and — this is the part that makes it discriminating — with a
non-victim control that **kept** its savepoint:

```
a_err:                   QueryDeadlockError [(1213, 'Deadlock found when trying to get lock ...')]
a_savepoint_after:       GONE — OperationalError (1305, 'SAVEPOINT sp_a does not exist')
b (non-victim control):  no error; savepoint STILL ALIVE
```

So a handler whose first act is `rollback(save_point=...)` raises 1305 *from inside the
except*, and that 1305 **replaces** the error being handled. Every guard keyed on the original
type then evaluates False — which is how #481's guard could be correctly placed on 50
endpoints and never fire.

Three things worth carrying:

1. **There is a second cause a type guard can never cover.** Any nested commit clears the
   savepoint stack, so a helper that commits internally takes its caller's savepoint with it.
   That arrives as an ordinary exception. `mt940_import` had hit it and hand-written the
   workaround twice — and its comment said so, unread, for however long.
2. **Both halves are needed.** Making the rollback safe *without* also re-raising converts a
   loud 1305 into a silent swallow at any handler that logs-and-returns — the exact defect
   #378 shipped and had to fix. Doing one half would have been a regression.
3. **Match the error code, never the message.** `frappe.DoesNotExistError` says "does not
   exist" too. The original string test was dead code (the driver always carries `args[0] ==
   1305`) *and* the only place the change could hide a real failure.

## Two things about my own process

**`git checkout --` after a commit restores from the index, and the tests still passed.** I
used it to revert a mutation and it silently took my real edits to `transaction_errors.py` with
it. The suite stayed green because the test module did not import the symbols I had just
removed — two *other* files did, and they were not in the modules I re-ran. I caught it by
grepping the file, not by running anything. Green was not evidence.

**A real 1213 hit `test_dues_schedule_health_manager` during the sweep** and now fails the test
instead of being swallowed — correct behaviour, and the honest cost of this change. It did not
reproduce in four further runs. This bench runs RQ workers during tests and CI does not, and CI
gives each shard its own database, so the contention is a dev-box property. It also left
orphaned rows that reddened two mt940 modules **identically on develop** — pre-existing site
dirt, cleaned. Always diff the red run against develop before believing it is yours.

## For whoever picks this up

- **#505** is the live one: guard and swallow one frame apart. #574 fixed 5 instances because
  they were pre-empting its own new guards, but the class is open.
- **#572** and **#570** are both "a report that says something untrue" — an import claiming it
  rolled back when it did not, and a row reported skipped that is committed.
- If a shard reddens later with a `QueryDeadlockError` where it used to pass, **that is #574
  working, not regressing.** The error was always there; it was being converted to a 1305 and
  then dropped.
- The duplicate-helper guard's documented remedy (`--update-baseline`) is the wrong move when
  it fires on code you just wrote. Converging the two ratchets' predicates into
  `tests/support/non_resumable_ast.py` left the baseline **byte-identical** at 571/1388, versus
  the 573/1390 CI had already written when it went red. Take the stricter of the two rules and check the other caller
  still passes — the termination package stayed 10/10, so both ratchets got the better rule.
