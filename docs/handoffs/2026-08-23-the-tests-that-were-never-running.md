# Handoff — 2026-08-23: the tests that were never running

Instruction: pick up an old open issue, hand a second one to an agent, start fixing.

I took **#194** (the oldest, 2026-07-31). An agent took **#206**. Both are now PRs. But the
thing worth carrying forward is neither fix.

> **A regression test that errors in `setUp` reports the same shape as a passing suite once
> it is one module among twelve in a shard log.** The four tests holding #194's guard in
> place had been dead for 12 days. Nobody noticed, because the failure said *"Test master
> data could not be created"* — an environment problem — and not *"your test file has a
> method name collision"*.

And a second one, which cost me a whole commit:

> **My replacement arithmetic was refuted by the skeptical review, and every one of my 41
> tests stayed green under the wrong version.** Each settlement in that file happened to
> have `payments − payout == the stated fee`, so nothing pinned the fee's *source*. The
> mutation was the only thing that found it.

## Landed

| | | |
|---|---|---|
| **PR #500** | #194 residual: a partly allocated settlement books its unmatched payments as fees | open, 3 commits, 42/42 green |
| **PR #493** | #206: approval-invoice coverage stops before the anniversary (agent) | open, 3/12 shards green at handoff |
| #496 | the shadowed-harness-method defect: 15–20 occurrences, 1 fatal | filed + corrected |
| #497 | four settlement tests whose result depends on what `Mollie Settings` holds | filed |
| #501 | the Mollie fee Journal Entry is booked backwards | filed |

## #194 was fixed the day it was filed, and left open

`292a8d5c` (PR #214) landed the settlement-level idempotency guard **hours** after the
issue was written. `git merge-base --is-ancestor 292a8d5c develop` passes. This is the
third time this pattern has appeared (see `issue-filed-from-a-review-comment-can-already-be-fixed`);
the check costs 30 seconds and I nearly re-implemented a guard that was already there.

What was left was the arithmetic underneath the guard. `mollie_fees = total_reconciled −
settlement_amount`, and `total_reconciled` counts only the payments *this run* matched.
`292a8d5c` stopped the `processed_count == 0` case; the partial case is the same defect:

```
AssertionError: Lists differ: [{'name': 'ACC-JV-2026-00042', 'total_debit': 18.5}] != []
```

1 of 2 payments matched, 30.00 reconciled against a 48.50 payout, and the unmatched
payment's value is **submitted** as a processing-fee expense. The real fee is 1.50.

It compounds: that entry *is* `_existing_settlement_fee_entry`, the idempotency key. Once
the fabricated entry is on the ledger the settlement short-circuits forever, so the
payments that never matched can never be booked — and `create_reconciliation` had already
marked the deposit `Reconciled`, out of the `{"status": "Pending"}` pool for good. The SEPA
batch branch of that same method has gated exactly this (`allocated_total ==
deposit_total`) the whole time. The settlement branch did not.

## The module had been dead for 12 days

Before any of that could be tested:

```
TypeError: MollieBase._ensure_company_cost_center() takes 1 positional argument
           but 2 were given
```

`EnhancedTestCase` defines `_ensure_company_cost_center(self, company_name)` and calls it
from `_ensure_master_data`, which every `setUp` runs. `MollieBase` defined a no-argument
method of the same name. Measured:

| tree | result |
|---|---|
| untouched develop | `Ran 38 tests ... FAILED (errors=38)` |
| after the rename | `Ran 42 tests ... OK` |

Dead since `e16523d6` (2026-08-11). Among the 38: the four regression tests `292a8d5c`
added for #194, and the five `TestSettlementSubmitPermission` tests from `78f0e32b`.

The reason it hid: the harness wraps the `TypeError` in `RuntimeError: Test master data
could not be created`. That reads as site state, so nobody opens the test file. **The
`__cause__` is where the answer was, two frames up.**

Only `_ensure_company_cost_center` is reachable from the harness's own `setUp`
(`setUp → _ensure_production_ready_setup → _ensure_master_data → _ensure_company_defaults`).
Every other shadowed name needs an *optional* convenience helper a test has to call
itself — which is why 10 sibling modules probe clean and this one killed everything. That
sentence is the whole of #496.

**My census was wrong in one place, and the review caught it.** `tests/utils/test_base_framework.py:12`
declares `VerenigingenTestCase(unittest.TestCase)` — not a harness subclass at all. My AST
pass resolved inheritance by *simple class name* and conflated it with
`tests/test_framework_enhanced.py:9`, which declares `VerenigingenTestCase(EnhancedTestCase)`.
Two base test classes, one name, one app.

## The arithmetic I shipped first was wrong in the same direction as the bug

I replaced the derived fee with `sum(payments) − payout` and called it "a fact about the
settlement". It is not the fee. It is **`fee + refunds + chargebacks`** — refunds and
chargebacks live on separate endpoints and never appear in
`get_payments_for_settlement`. Measured:

```
AssertionError: 207.5 != 7.5
```

500.00 of matched payments, a 200.00 refund, 7.50 of Mollie costs, a 292.50 payout — and a
**submitted 207.50 expense**, which then becomes the permanent idempotency key. The same
fabrication I was fixing, with different arithmetic underneath.

This repo already knew the identity, in two places — `SettlementsClient.list_settlement_reconciliation`
and `settlement_bank_transaction_processor` both compute `payments − refunds −
chargebacks`, and both read `settlementAmount`, not `amount`, because a payment's `amount`
is in the payment's own currency while the payout is in the settlement's. I did not look
before writing.

The fee is now **read**, not derived: `periods[<year>][<month>].costs[*].amountNet`, which
is Mollie's own statement. Deriving it the siblings' way was rejected on purpose — their
client calls return `[]` on failure *and* on "none" (`suppress_errors=True`), so a failed
refunds fetch silently overstates the fee, which is the exact failure mode this guard
exists to prevent.

**The lesson is about the tests, not the arithmetic.** Swapping `_settlement_stated_fee`
for `sum(payments) − payout` left **all 41 tests green**. Every settlement in that file has
payments-minus-payout equal to the stated fee, so not one of them pinned the fee's source.
`test_a_refund_in_the_settlement_is_not_expensed_as_a_fee` is the only case where the two
disagree, and it exists only because a mutation was run.

Mutations, each reverting exactly one thing:

| mutation | failures |
|---|---|
| remove the completeness gate | 2 |
| derive the fee instead of reading it | 1 — the refund test, 207.5 != 7.5 |

## #501: the fee entry is booked backwards, and the evidence was in a passing test

Settled during review without needing the bank leg. `test_full_path_creates_balanced_journal_entry`
builds the fees account with `root_type="Expense"` and asserts
`credit_in_account_currency > 0` for a **positive** fee — and passes. A cost debits an
expense account. `_create_mollie_payment_entry` sets `paid_to = clearing`, so each matched
payment *debits* clearing; with the bank receipt crediting clearing by the payout, the
residual to clear is a *credit*, and the code debits it again. Clearing drifts by 2× the
fee per settlement.

Two characterization tests cement it, with docstrings asserting the direction as intended.
Left for #501: it is independent of amount and timing, it changes GL semantics, and veg11
has **zero** such Journal Entries so far — cheap now, expensive after the first real
settlement.

## #206 (agent): the issue named one line; there were seven

The agent's PR #493 is worth reading for the census. `add_years(start, 1)` with no `-1` day
was the Annual branch the issue named — **all six branches plus the `else` default** had
it, and `Daily` was two days instead of one. It shifts the whole *sequence* off the
anniversary, because `CoverageCalculator` rolls each later period off `previous_end + 1`.

And it is in the live data. Measured read-only on veg11: **22 Annual + 11 Monthly** submitted
invoices whose coverage ends on the same day-of-month it starts. Repairing those rows is
data work and is filed separately.

Its own review found three more things, including that the seam test's first assertion was
**circular** — `period.start_date == first_end + 1` restates `CoverageCalculator`'s own
`add_days(latest_end, 1)`, so it moves *with* the bug and passes under mutation.

## Where things stand

- **PR #500** — open, needs review. 42/42 on `test_site_3`, also green with
  `VERENIGINGEN_FAIL_ON_TEST_LEAK=1` and under `run_without_credentials.sh`. Siblings 74 OK
  and 20 OK. **Not yet through CI.**
- **PR #493** — open, 3/12 shards green at handoff, 9 pending. Was being watched.
- #496, #497, #501 — filed, unstarted.

## What to distrust

- **The settlement payload shape is unverified, and it is now load-bearing.**
  `GET /v2/settlements` returns **400** for this bench's Mollie test key at every page size
  (10, 50, 100, 250), so no real settlement could be fetched. `_settlement_stated_fee`
  walks for a `costs` list at *any* depth because the API documents year-then-month nesting
  while this app's `Settlement` model assumes one level. If the list response does not carry
  `periods` at all, PR #500 books no fee and says so on the transaction — conservative, but
  the happy path would stop booking fees. **This is the biggest open question in #500.**
  It also means the whole Mollie settlement pipeline has never run against a real
  settlement.
- **PR #500's shard-scale behaviour.** The module is absent from `known_test_leaks.txt`
  (it contributed nothing when that file was seeded, being already dead), and
  `check_test_leaks.py` treats an unlisted module as baseline **0**. Zero leaks measured
  locally under enforcement, and these tests create fresh documents rather than reusing
  shared fixtures — but a warm local site is not CI.
- **A behavioural shift in #500 worth watching.** A settlement containing even one
  permanently unmatchable payment — a donation, a webshop payment, a cancelled invoice,
  anything outside the ±1% tolerance — now spends 4 daily runs in the retry pool and then
  goes **Unreconciled permanently**, leaving clearing holding `unmatched payments + fees`.
  Better than fabricating a fee; but settlements that used to auto-close (wrongly) now
  queue for a human. If that turns out to be common, the answer is probably to book the
  known fee and route the unmatched value to a suspense account.
- **#497 means `test_site_1` lies about this module.** It holds
  `Mollie Settings.mollie_clearing_account = "Mollie - _TC"` (INR), so four tests fail
  there with `InvalidAccountCurrency` and pass on `test_site_2/3` (EUR). I used
  `test_site_3` throughout for that reason.

## Unrelated, needs a decision

The main checkout on `develop` carries an **uncommitted whole-file rewrite** of

```
verenigingen/verenigingen/doctype/membership_termination_request/membership_termination_request.json
```

377/376 lines: `modified` bumped, `naming_rule`/`allow_bulk_edit` added, `app` dropped,
`permissions` reordered. mtime `00:24 CEST`, which precedes every bench command run this
session. This is the known `developer_mode=1` trap — a test run rewriting fixtures into the
live tree — and bench serves veg11 from that tree, so it is a live deploy of that file.
Left untouched. Default per the standing note is **revert**; tie-break on the live DB's
`modified`.

## Notes for next time

- `gh issue view --comments` is broken here in exactly the way that matters: it prints
  **nothing** and exits, so CLAUDE.md's rule 5 silently returns "no comments". Use
  `gh api repos/:owner/:repo/issues/<n>/comments`.
- Before trusting any regression suite, **run the module and read the count.** `Ran N` is
  the only instrument that answers "is this suite doing anything".
- `verenigingen/tests/utils/leak_guard.py` prints leaks regardless of the env flag;
  `VERENIGINGEN_FAIL_ON_TEST_LEAK=1` makes them fail instead of warn. Cheap to add to any
  local run.
