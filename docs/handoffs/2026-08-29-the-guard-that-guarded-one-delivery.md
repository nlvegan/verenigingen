# 2026-08-29 — the guard that guarded one delivery

**Merged:** #646 (`67dcb93fa`), closing #635 — a refunded or charged-back Mollie **dues**
payment now reaches the ledger. **Filed:** #645. **Also corrected:** the
`verenigingen-test-harness` skill and one live docstring still called veg11 "the live
site".

The document leads with the two defects a skeptical review measured in my own first
commit, because both share a shape worth naming: **I wrote a guard, wrote a comment
asserting the property the guard was for, and the guard did not enforce that property.**
The comment was the strongest evidence in the file that nobody had checked.

---

## 1. "Mollie cannot give back more than it took" — a comment, not a guard

The first commit checked `amount > pe.paid_amount`. That is per **delivery**. A refund and
a chargeback are different `reversal_type`s, get different reversal keys, and **both book**.

Measured through the real webhook, two €30 reversals of a €50 payment:

```
SECOND REVERSAL RESULT: success
OUTSTANDING AFTER TWO 30 REVERSALS OF A 50 PAYMENT: 60.0
INVOICE GRAND TOTAL: 50.0
INVOICE STATUS: Overdue
CLEARING CREDITS FROM REVERSAL JEs: 60.0
```

### Why nothing downstream stops it — the discriminating half

The tempting reassurance is "ERPNext would have caught it anyway." It cannot, and the
reason generalises well beyond this branch:

`journal_entry.validate_reference_doc` picks `dr_or_cr = "credit_in_account_currency"` for
a Sales Invoice reference. **Every row a reversal writes is a debit.** So
`reference_totals[invoice]` is `0.0`, and `validate_invoices` is gated on
`if total and flt(invoice.outstanding_amount) < total`. Zero is falsy. The over-allocation
guard never runs.

> **A Journal Entry can restore a Sales Invoice above its grand total and ERPNext will not
> object.** Any code booking a reversing JE against an invoice owns that ceiling itself.

Contrast Payment Entry, which *is* guarded in both directions — `payment_entry.py:462-466`
throws "has already been fully paid" before it looks at the sign, `:480` is the allocation
ceiling. That asymmetry is exactly why a reversal cannot be a Payment Entry **and** why
being a Journal Entry costs you the validation you were implicitly relying on. Trading one
for the other was the whole design decision in #370, and the bill for it was not written
down until now.

The fix counts what is already booked (`reversal_idempotency.total_reversed`).

### The escaping in that scan is load-bearing, and only a control proved it

Reversal keys are `{payment_id}_{reversal_type}_{reversal_id}`, so the scan is a LIKE
prefix. `_` is a single-character wildcard and **every Mollie id contains one** (`tr_`,
`re_`, `chb_`, `cst_`). Measured with a control:

| pattern | matches |
|---|---|
| `tr\_abc\_%` (escaped) | `tr_abc_refund_re_1` only |
| `tr_abc_%` (unescaped) | that **plus** `trXabc_refund_re_2` **and** `tr_abcZZ_refund_re_3` |

Escaped-only would have looked correct in every test I would have thought to write. The
control is the only thing that distinguishes "the escaping works" from "the escaping is
decorative and the pattern happens to be narrow enough."

---

## 2. My unwind order was backwards for the case the branch was written for

The dues route records the whole payment and allocates only the invoice's outstanding
(`cash_received=`), so an excess sits in `unallocated_amount` as a credit on the customer.
I unwound **invoice allocations first**, and defended it in the docstring: *"eating the
on-account credit first would leave a partial refund invisible on the invoice."*

That argument is sound for refunding part of the *invoice* payment. It is wrong for the
case that actually produces an `unallocated_amount` — which only exists because the
gateway moved more than the invoice could absorb, and is therefore the most likely thing
being refunded. Measured, €10 refund against a €50 invoice paid with €60:

```
OUTSTANDING BEFORE: 0.0  STATUS: Paid
OUTSTANDING AFTER REFUND OF THE 10 EXCESS: 10.0  STATUS: Partly Paid
```

Debtors nets to zero either way. **Invoice outstanding is what drives dunning and dues
status**, so netting-to-zero is not the property that matters. The excess now unwinds
first; a full reversal is identical under both orders.

**The reviewable tell:** the docstring argued the upside of my choice and never stated its
cost. A tradeoff written down in one direction is a tradeoff nobody weighed. Both
directions are in the docstring now.

---

## 3. Green locally, red in CI — because I ran a different gate

The duplicate-helper hook passed in `pre-commit run --hook-stage pre-push`; CI failed.
Not flakiness and not environment: **two different gates with the same name.**

- the **hook** blocks NEW near-identical clone families;
- `code-validation.yml` additionally regenerates the census and fails if the committed
  file differs **in either direction**.

My change moved counts *both* ways — it removed two clone families and added some plain
name collisions — so the hook was satisfied and the sync check was not. Fix:
`python scripts/validation/duplicate_helper_validator.py --update-baseline`, commit.

Before trusting the regenerated file I ran it three times and compared hashes
(byte-identical), because this repo has a recorded case of CI disagreeing with a local run
on a byte-identical tree caused by non-determinism inside *this* validator's similarity
scoring. That check cost 20 seconds and converts "CI should agree" into "CI will agree."

**Also worth keeping:** a first attempt to verify the resync reported `STILL DRIFTING`,
which was my check being wrong — `git diff` compares against HEAD, and the regenerated
file was not committed yet. A verification step that can report failure for a reason
unrelated to the thing being verified is not a verification step.

---

## 4. What the gate bought, and what it cost

The duplicate-helper ratchet caught the branch adding a **third** copy of three helpers
every Mollie Journal-Entry booker needs. Converging them on
`journal_entry_booking_support` was not tidying — the two existing copies **had already
drifted**:

- one asked "is this bank line covered?" against `deposit`, the other against `withdrawal`;
- the deposit form reads `>= 0` on a withdrawal line, i.e. **true before anything is
  allocated**.

So the census now records two clone families *removed*. But note what the review then
established: on the production path that status assignment is inert anyway, because
`Bank Transaction.before_update_after_submit` recomputes status from `unallocated_amount`
and `db_set`s it before the update-after-submit comparison. The unified rule is correct
and reachable only on the draft-BT path. **Reconciling a disagreement between two copies
is worth doing even when it turns out the framework was arbitrating it all along** — but
say which of those you proved.

Cost, honestly: converging three helpers pulled four test modules into the diff, including
two that patched the now-module-level functions via `patch.object(creator, ...)`. That is
the real price of extraction in a codebase whose tests reach for private methods.

---

## 5. The skeptical review, and the one thing I would change about how I ran it

Seven findings, of which **two were defects I would have shipped** and five were real but
smaller (a permanently-refusing branch whose reason reached only the Error Log; six
argument-swapped `frappe.log_error` calls; a 12th copy of the `dateutil` block; a
redundant DB read; rotted ERPNext line numbers). It also **cleared** three things I was
least sure of, with measurements rather than opinion.

It mutation-tested my suite before trusting the green run — dropping the invoice reference
row reddens 5 of 8, swapping debit/credit reddens 6 of 8. I did the same for the two new
defects (disabling the cumulative ceiling reddens 2; restoring invoice-first reddens 1).
**A test written after the fix is worth nothing until you have watched it fail.**

What I would change: I dispatched it *after* pushing the branch, so the two defects were
public for the time it ran. The standing rule is before the PR; pushing a branch is not
opening a PR, but it is close enough that the ordering deserves to be tightened.

---

## 6. Filed, not fixed

**#645** — a Journal Entry that restores an invoice's `outstanding_amount` never refreshes
the Member's payment history. Only **Payment Entry** (`on_submit`/`on_cancel`/`on_trash`)
and `Sales Invoice.on_update_after_submit` queue that refresh; ERPNext writes the restored
figure with `frappe.db.set_value` + `ref_doc.set_status(update=True)`, and `Document.db_set`
dispatches `on_change`, which this app does not register for Sales Invoice. Neither safety
net covers it: the validator backfills only **missing** rows within a 7-day creation window
(a chargeback is outside it twice over, and the row is stale rather than missing), and the
batch processor drains a queue nothing enqueues.

Stated as a source claim. **I did not observe a stale row**, and the issue says so.

---

## 7. veg11: the correction that had not propagated

Both `CLAUDE.md` files were corrected on 2026-08-28 — veg11 is a **test site carrying a
copy of production data**, not production. The `verenigingen-test-harness` skill still said
"it is the live site", and a skill is loaded *instead of* re-reading CLAUDE.md, so the
retired framing kept being served. Corrected, with an iteration-log entry.

Swept for the class rather than the instance. Live instances: the skill (fixed) and
`test_cleanup_utils_coverage.py`'s docstring (fixed). Deliberately **not** touched:
`docs/plans/` and `docs/handoffs/` entries, which are historical records of what was
believed at the time, and `test_webhook_user_setup.py:44`, where "the live veg11 site"
means *running, with workers* in contrast to an isolated CI DB — a different sense of the
word.

The generalisation for the skill's own iteration log: **retire the sentence when the fact
changes somewhere else**, not only when a fix closes the blind spot the sentence describes.
When CLAUDE.md is corrected, grep the skills.

---

## State

- `origin/develop` at `67dcb93fa`; #635 closed; #645 open.
- Known-red and **not** this branch: `test_bank_transaction_reconciliation_coverage`
  (5 failures + 1 error) — #640. Confirmed by diffing the failing test *names*, not the
  counts, against untouched `origin/develop`.
- Open PRs untouched this session: #629, #632, #633, #643, #644.
