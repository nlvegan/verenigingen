# Handoff — 2026-08-16b: the issues that were wrong

Session goal was "push and open PR", then "file the follow-ups", and it grew from there.
Five PRs merged, three open, sixteen issues filed. The through-line is not the code: it is
that **four of my own issue write-ups were wrong, and every one was caught by something
other than me re-reading them.**

## State

| | |
|---|---|
| `develop` | `86f10b51` |
| Merged this session | #360, #361, #364, #366, #368 |
| Open, green, awaiting merge | #358 (re-running CI after a conflict resolution) |
| Open, red | #365, #367 |
| Open, stacked | #347 (pylint-only until #346 lands) |
| Issues filed | #348–#357, #359, #362, #363, #369, #370 |

## What merged

- **#360** — `get_recurring_donations` mutated the list it iterated; and a Mollie outage
  read to donors as "cancelled".
- **#361** — the member fee-adjustment kill switch did not exist; `enable_member_fee_adjustment`
  is now a real field.
- **#364** — test cleanup never cancelled submitted documents, because `delete_doc(force=True)`
  does not bypass the submitted guard. Plus a ledger guard, added after CI caught what three
  local modules could not.
- **#366** — `before_tests` now names a site's stale Single links instead of letting them
  surface as an unattributable wall of errors.
- **#368** — deleted the Payment Entry button from the Donation form; unblocked the PDA
  donation picker, which had been permanently empty.

## The four issues I got wrong

**#348 — I described the symptom backwards.** I wrote that an *active* recurring donation
following an inactive one goes missing. `list.remove()` during iteration shifts the tail left
while the index moves right, so the next element is **never visited** — and therefore never
removed. It *survives*. A cancelled donation right after another cancelled one stays in the
donor's active list. Reproduced in five lines of Python; the implementing agent caught it.

**#356 — "produced and read by nothing" was false.** `require_approval_for_increases` /
`_decreases` are read by `membership_adjustment.html:169,172`. My grep covered `*.py`,
`*.js`, `*.json` and **not `*.html`**. Correcting it exposed something worse than the dead
setting I had filed: since the flag is always `0`, the portal never shows "Rate increases
require approval", while `before_insert` forces **every** member request to Pending Approval.
**The portal tells members increases take effect immediately, and they silently do not.**

**#357 — both halves of the premise were false.** I claimed a module had "zero gating
coverage" because all 10 of its tests are in `known_test_failures_v16.txt`. CI reads
`known_test_failures.txt` — a *different* file, 62 lines, **all comments, zero entries**. The
v16 file says so in its own header, which I never read because I had already cited its entry
count. And the module **passes 10/10** on a clean site. An agent deleted it on my false
premise before the correction landed.

**#350 — understated by a factor of five.** The issue named 2 consumer files. There are 10,
plus two `.js` files.

Each correction is posted on the issue itself.

## The three findings worth more than the branches they came from

**`delete_doc(force=True)` does not bypass the submitted-document guard.**
`check_permission_and_not_submitted` runs at `delete_doc.py:120` and `:162`; the `if not
force:` guard is at `:170`. So every submitted document a test tracked survived teardown.
Fixing it took three modules from 24/33/16 leaks to zero.

**But cancel-before-delete is unsafe for ledger-bearing vouchers**, which is what CI caught
and three local modules could not:

```
after submit   2 GL Entry, 1 Payment Ledger Entry
after cancel   4 GL Entry, 2 Payment Ledger Entry   <- cancel WRITES reversals
after delete   4 GL Entry, 2 Payment Ledger Entry   <- parent gone, rows remain
```

The delete *succeeds* and strands the rows; then `revert_series_if_last()` rewinds the naming
series, so the next Payment Entry is handed the same name and is **born already linked to
them**. The drain never saw it — it walks tracked documents only, so cleanup reported
`success` with no leak line while leaving 6 orphaned rows. Silent by construction.

**Donation was submittable in ERPNext, not here.** ERPNext's Non Profit module had
`is_submittable: 1`; it was removed in ERPNext `0c0a9ed96d`, and this app reimplemented
Donation without the flag. That single fact explains ten files filtering `docstatus = 1`
(#350/#367), stray `submit()` calls that still "work" because `_submit()` has no
`is_submittable` guard, and a "Create Payment Entry" button that never rendered (#368).
Foppe supplied the memory; the history confirmed it.

## The largest open defect: #370

Mollie reversals never book, for **both** payment types, by opposite routes:

- forward classifies (`PaymentClassifier` → DUES / DONATION) and books type-appropriately —
  **Payment Entry** for dues, **Journal Entry** for donations;
- reversal does not classify at all. It hardcodes `get_donation_by_payment_id` *and* a
  Payment-Entry precondition.

So donation chargebacks fail the missing-PE check (donations book a JE), and every dues
reversal fails the not-a-donation check. A refund additionally books as JE or PE depending
purely on which entry point saw it first.

**The consolidation to reach for is not the obvious one.** `process_reversal_webhook` is
*already* generic — it takes `reversal_type` of refund-or-chargeback with thin adapter
callers. The design intent was right; what is missing is classification. Reuse
`PaymentClassifier`/`PaymentTypeRouter` in the reversal path and replace `payment_entry_exists`
with a type-aware "was this booked?" predicate — which also fixes #369 item 2, where the same
hardcoded check makes `_handle_partial_processing` unreachable. **One change, not two.**

**SEPA returns stay outside** (Foppe's call, and the code agrees): dues collected by direct
debit reverse via return files — `process_sepa_return_file` → `reverse_failed_sepa_payment`
— a different transport with a different trigger, already working. Converge downstream, not
at the entry point.

## Traps that cost real time here

- **`known_test_failures_v16.txt` is not what CI reads.** Presence in it is evidence of
  nothing about today. Read the workflow, then run the module on a clean site.
- **Assigning a nonexistent field on a Frappe Document is a silent no-op** that `save()`
  discards, while *reading* it raises `AttributeError`. A test setUp "configuring" a phantom
  setting configures nothing and passes forever.
- **`gh pr edit` is broken on this repo** — Projects-classic GraphQL error, exit 1, and **the
  edit does not apply** (probe-verified). Use `gh api -X PATCH .../pulls/<n> -F body=@file`.
  Only `pr edit` is affected.
- **`test_site_5` was bricked by three dangling links in a Single**, and I diagnosed it as
  "not provisioned" before the control run showed develop failing identically. Repaired;
  #366 now makes a site announce this itself.
- **A bare `assertRaises(ValidationError)` against a multi-guard validator asserts almost
  nothing** — three amendment tests passed on the minimum-fee guard while claiming to test
  others (#363).
- **Two agents on one test site produce failures that are not real.** I did this twice.
  Both times only a control run said so.

## Before merging what is left

- **#367** (docstatus sweep) — 35 regressions on shard 3. Early triage points *away* from the
  change: `docstatus` appears 5 times in a 10,933-line log, and the failures are
  `MandatoryError: [Account, ...]: parent_account` — test-company chart-of-accounts collapse,
  the shared-fixture family. It adds a test file, which re-packs every shard. **Hypothesis,
  not a conclusion** — needs attribution against a develop control.
- **#365** — down to 1 regression (`test_gl_entry_validation_comprehensive`) from 14.
- **#347** must not merge before #346, and #346 should not merge without it.

## Not yet filed

`EnhancedTestCase._remove_drained_record` has the **identical** ledger defect as #364 with no
guard, and its docstring asserts that cancelling "removes the derived ledger rows" — which the
probe above disproves; cancel *adds* rows. Left alone to keep #364 reviewable. It is a live
source of orphaned ledger rows and wants its own issue.

## The thing I would tell the next session

Every wrong issue in this session was wrong in the same way: I had **confirming** evidence and
stopped. An entry count instead of a file header. A grep over three extensions instead of four.
A symptom I reasoned out instead of ran. The fix each time was thirty seconds of measurement.

The agents were the control. Three of them refused an instruction and were right to —
most sharply when I told one to assert "nothing creates a Payment Entry for a Donation" and it
demonstrated that refunds and chargebacks do. Had it complied, #368 would have shipped a false
assertion dressed as a regression guard. **Brief them so that disagreeing is cheaper than
complying**, and read the pushback as data rather than friction.
