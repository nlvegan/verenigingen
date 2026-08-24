# Handoff — 2026-08-23e: the key that had to be written last

Merged **#500** (the fabricated/backwards settlement fee) and **#520** (the missing payout leg,
closing #508), and opened **#538** for #523. The useful thing this session produced is not any of
the three fixes — it is that **my fix for #508 recreated #508's exact symptom on its failure path,
and reported success while doing it.**

> **Whichever write is the idempotency key, everything else goes before it.** The fee Journal Entry
> is the settlement-level idempotency key (`_existing_settlement_fee_entry` →
> `_already_processed_result`). I booked it *first* and the payout leg second. Measured: run 1 fails
> on the payout leg, leaving the fee on the ledger; run 2 short-circuits on that fee, **returns
> True**, marks the deposit `Reconciled` with `allocated_amount = 0.00` and 27.50 stranded in
> clearing. That is verbatim #508, reached through the failure path and unrecoverable by any code
> path. With the payout first, a failure in *either* leg recovers fully on the next run.

## State

| | |
|---|---|
| **#500** | **MERGED** `889b9af3` — closed #194, #501 |
| **#520** | **MERGED** `e3e8b7ff` — closed #508. 4 commits, +804/−6, 30/30 checks green |
| **#538** | **OPEN** — #523, the gate that never passed. 54/54 module, 74/74 sibling |
| Filed | **#521**, **#523** (now #538), **#534** |
| veg11 (live) | **not deployed this session.** `clearing == bank`, so #508's leg is a no-op there |

## The design question #508 asked to be settled first, and how prose settled it

#508 could not say whether this was a single-clearing-account shape or a two-account shape whose
missing piece is a transfer. It is the latter, and the app says so itself — the decisive quote being
in the docstring of the function that omits the leg:

| evidence | says |
|---|---|
| `get_clearing_account()` | clearing is "where Mollie payments are deposited **before settlement to the physical bank account**" |
| `get_bank_account_gl()` | the bank is "where **settlement payouts from Mollie are deposited** (typically Triodos)" |
| `process_mollie_settlement()` | names **three** legs and implements two |
| `match_mollie_settlement():399` | gates on the transaction being on the bank account — so the deposit reconciled **is** the physical one |

This is the third session running in which the answer was in the prose and not the schema (see
[the fee booked backwards](2026-08-23-the-tests-that-were-never-running.md) and #501). **Grep the
prose.**

## Two things the reviews caught that I would have defended

**An ordering comment can describe the pre-fix world.** Mine argued fee-first was safe *because*
"booking the payout first would let a fee failure short-circuit every later run." True before I
narrowed the fee guard by `voucher_type` — false after, because narrowing it is precisely what
stopped the payout leg being a key. I wrote the guard change and the comment in the same commit and
did not re-read one against the other. **When you change what a guard matches, every comment that
reasons about that guard is suspect.**

**`clearing == bank` is not a misconfiguration.** I shipped an Error Log telling the operator to
"configure them as separate accounts." With one account there is no intermediate to drain: the
payments land directly in the bank account and the fee reduces it, leaving exactly the deposit
(measured — the single account ends at 27.50 for a 27.50 deposit). So the skip is correct
accounting, the advice was to change a working setup, and since **veg11 is in that configuration**
the row would have fired on every settlement to report a correct ledger. My test for it asserted
only that no voucher was booked — which passes whether the skip is right or wrong. It now asserts
the ledger.

## A clean mutation matrix is evidence about the rows in it, nothing more

The six-guard matrix in #520's first commit was honest: the reviewer re-ran every row independently
and no test passed with its guard gone. It still missed the critical defect, because **C1 lives in
territory no row covered** — recovery after a partial failure. Three further guards had no control
at all:

| guard | mutation result before a test existed |
|---|---|
| `deposit` vs the settlement's stated `amount` — the claim the docstring argues hardest for | **47/48 passed** (every test set the two figures equal) |
| the `<= 0.01` amount guard | **48/48 passed** |
| the allocation-repair path | **51/51 passed** (my own C1 test cannot reach it) |

The last one is the sharpest: I added the repair to fix C1, wrote a test for C1, and the repair
itself stayed unpinned — because with payout-first the C1 test never reaches the repair branch. Only
re-running the mutation *after* the fix found it. **Re-run the matrix after you change the code it
was measured against.**

Also unpinned when I first wrote it: the `clearance_date` stamp (C2). I added a line and asserted
nothing about it, in the same session whose lesson was that review-driven fixes land unpinned.

## What C2 was, and why an accounting-only lens could not see it

The payout leg never received a `clearance_date`, so ERPNext's own Bank Reconciliation Statement
listed it as an outstanding item forever while the Bank Transaction read `Reconciled` — two ERPNext
views disagreeing, which is the class of disagreement #508 was filed about, moved one document
downstream. The GL rows were correct throughout; the *reconciliation metadata* was half-set.

ERPNext will not set it, and the reason is worth keeping: `clear_linked_payment_entry` is reached
only from `allocate_payment_entries`, which **skips any row carrying a non-zero
`allocated_amount`** (`bank_transaction.py:194`) — and even with a zero row,
`get_clearance_details`' `should_clear` refuses a voucher whose other bank leg is not fully
allocated. Our other leg is the clearing account, itself `account_type = "Bank"`. **A Bank-to-Bank
transfer is a shape ERPNext never auto-clears.** The reviewer falsified its own first explanation
with a control before landing on that.

## #523: the gate that had never once passed

`match_mollie_settlement` compared `transaction["bank_account"]` — a **Bank Account** docname, from
`reconcile_bank_transactions`' own select — against `config.get_bank_account_gl()`, a **GL Account**
name. Different namespaces (`Bank Account` autonames `account_name + " - " + bank`, `Account` uses
`abbr`), so equality was possible only by coincidence.

```
veg11, read-only:  Bank Accounts 409, with name == account: 0
                   Bank Transactions 7,664
                   Journal Entries / Payment Entries carrying custom_mollie_settlement_id: 0
```

So **the entire Mollie settlement pipeline has never run**, and #194's probe finding no fee entries
and #345's idle scheduler both now have a mechanical cause rather than a suspicion.

It survived because the tests forced the two sides equal — **six sites**, one of them carrying
`# force account equality with the configured Mollie account`. That comment is the tell CLAUDE.md
rule 6 names: an explanation sitting next to the bug. Four were simply deleted (`_txn_dict` already
carries the right value once the code is right), and `test_bank_transaction_reconciliation.py:953`
had to be *changed rather than deleted* — its subject is the keyword branch, so left alone it would
have started returning None at the account gate and **passed without reaching what it tests.**

Deleting the four converted them into real coverage: reverting the fix now reddens the new namespace
test **plus two pre-existing tests**.

## Process notes

- **The skeptical review is worth insisting on.** It found C1 (critical), C2, and three unpinned
  guards. Foppe asked for it twice; the first attempt died instantly on an org monthly spend limit,
  which is not a verdict on anything.
- **Verify an agent's housekeeping claim too.** The first reviewer reported "worktree is clean
  again" and had left `test_zzz_review_probe.py` behind; `git add -A` swept it into a commit and the
  pre-commit hooks caught it. Brief reviewers to check `git status --untracked-files=all`, and note
  that a scratch test file also distorts the duplicate-helper gate (it manufactured four bogus clone
  families).
- **The duplicate-helper ratchet fires on baseline drift, not only clone families.** `_run::3` →
  `_run::4` from a fourth same-named test helper. The line carried no `# clone family` annotation.
  Fixed by naming the helper `_run_settlement` rather than regenerating the baseline upward — #500
  had just ratcheted that census *down* by one.
- **`gh issue view` / `gh pr edit` are still broken here** (Projects-classic GraphQL). `gh api` and
  `gh api -X PATCH` work; `gh pr create` / `merge` / `checks` are fine.
- **Handoff slots collided again.** `2026-08-23` is claimed by **two** open PRs (#502 and #536) with
  different filenames; `b`, `c`, `d` are #503, #507, #522. This is slot `e`.

## What is left

- **#538** — open, awaiting CI and review.
- **Nothing is deployed.** veg11 needs `mollie_clearing_account` and `mollie_bank_account` split
  before #508's leg does anything, and that is a **deployment decision, deliberately not taken
  here**: fixing #523 makes the pipeline *able* to run, and splitting the accounts is what makes it
  run. Do those in that order and watch the first settlement.
- **#521** — no reconciliation path populates `Bank Transaction.allocated_amount` for the
  invoice/batch branches; `bank_transaction_name` sets a custom Link field, not ERPNext's child
  table. Those branches book a real bank GL leg, so they strand no money.
- **#534** — extract a `MollieSettlementReconciler`: **1032 of 1915** method lines (53%) in
  `PaymentReconciliationManager` are settlement-only. Deliberately deferred so a ~1000-line move
  would not bury a three-line fix. **Do not add a fourth `_create_*`/`_book_*` Journal Entry builder
  to that class before doing it** — #520 added the third, and the file being too big to hold in
  context is how C1's ordering survived to review.
- `_require_submit_permission("Journal Entry")` in the payout leg is redundant on the only pipeline
  path (`:1331` already refuses for both doctypes) and therefore unpinnable there. Kept for symmetry
  with its sibling, flagged rather than removed.
- **No real 1213/1205 has still ever been produced** across #470/#475/#484/#504 — unchanged this
  session, noted so it does not get forgotten.

## For whoever picks this up

- **Write the idempotency key last.** Everything a run needs to redo on retry must be written before
  the thing that says "this run is done."
- **A mutation matrix proves its own rows.** Ask what *isn't* in it — here, every failure path.
  And re-run it after the fix, because a fix moves the code the matrix was measured against.
- **The prose is the spec in this app.** Three sessions running, the answer was in a docstring.
  Also: when your own docstring makes a promise (operator visibility, "nets to zero"), check the
  code keeps it — two of mine did not, and both were caught by review rather than by me.
- **`expectErrorLog()` is a tolerance, not an assertion.** It permits a row; it does not require
  one. To assert a log, query `Error Log`.
