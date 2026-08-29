# 2026-08-29b — the runs that measured nothing

**Merged:** #651 (`f7b69e4b5`) closing **#640**, and #650 (`410a88d40`) closing **#645**.
In that order, deliberately. **Filed:** #648, #649.

Four results in this session read as evidence and were not. Three were mine.

| the result | what it looked like | what it was |
|---|---|---|
| 39 tests green across three modules | the #645 fix works | a mutation making the fix **completely inert** in production passed all of them |
| `2107 tests, 0 failing` (in #640's body) | in-process co-tenancy refuted | the runner **never ran a test** |
| `origin/develop` green on shard 7 | my branch broke it | the module was already broken; shard packing differed |
| combined commit status `pending` | PR #647 failing | that API returns `pending` for *every* PR here — nothing writes legacy statuses |

The one control that did work, both times, was the boring one CLAUDE.md prescribes: **run
the thing against an untouched base tree and against the branch, back to back, on the same
site.** It settled both merges. Everything clever failed.

---

## 1. A test that asserts *who* was called does not assert *what* was passed

#645: a Journal Entry that moves a member invoice's `outstanding_amount` leaves
`Member.payment_history` stale. Payment Entry and Sales Invoice each have a refresh route;
Journal Entry had neither, and the Sales Invoice route cannot cover it — ERPNext writes the
restored figure with `frappe.db.set_value` + `set_status(update=True)` (`gl_entry.py`),
neither of which dispatches `on_update_after_submit`.

The fix registers a handler on the **doctype**, so it covers all fourteen Journal Entry
producers rather than the one from #635. A Journal Entry carries its party per **account
row**, so the Payment Entry handler (`doc.party_type` / `doc.party`) could not be reused.

I split the proof in two and was pleased with myself about it:

* **dispatch** — driven through a real `doc.submit()` / `doc.cancel()`, so a registration
  that exists but never dispatches still fails.
* **payload** — the refresh must OVERWRITE a stale row, not backfill a missing one. Not
  implied by the dispatch: both existing safety nets fail on exactly this shape (the
  payment-history validator backfills only *missing* rows, inside a 7-day window).

Both halves had controls. Both controls passed. And the review then mutated the shared
enqueue helper to pass `customer=None`:

```python
    member=member_doc.name,
    customer=None,          # was: customer=customer
```

`drain_member_payment_history` then queries `Sales Invoice` on `{"customer": None}`, gets
zero invoices, and **the fix does nothing at all**. Result: `test_journal_entry_payment_history`
8/8 OK, `test_payment_entry_hook_defers` 2/2 OK, `test_background_jobs` 29/29 OK. **Thirty-nine
tests, zero killed.**

The gap sat exactly between my two halves. The dispatch tests read `c.kwargs.get("member")`
and never `customer`. The payload test called `drain_member_payment_history` directly,
bypassing the enqueue entirely. Neither half was wrong; the **argument joining them** was a
third property with no assertion on it.

> **When a proof is split into "it dispatches" and "the payload is right", the argument
> passed between them is a third property. Assert the tuple, not the endpoints.**

Every enqueue assertion now pins the `(member, customer)` pair. Same mutation now reddens 5
of 9.

### The fix made the row wrong instead of stale

Wiring the refresh exposed a second defect. `determine_payment_status` had no branch for
ERPNext's own `Partly Paid`, and `paid_amount` is the sum of Payment Entry **allocations** —
which a reversing Journal Entry does not touch. So after a partial reversal
`paid_amount == grand_total`, the `paid_amount < grand_total` test reads False, and the row
falls through to `Unpaid`. Measured:

```
row: status='Unpaid'  paid=42.0  outstanding=20.0      invoice: 'Partly Paid'
```

Three fields on one row disagreeing, reading on the Member form as "this member never paid".

My assertion had been `assertNotEqual(row.payment_status, "Paid")` — which passes for
`Unpaid`, `Overdue`, `Cancelled`, `""`, and any typo. **A negative assertion is how a wrong
value hides in a green test.** Pinned to `"Partially Paid"` now, with the branch added and
its own control.

---

## 2. An instrument that runs nothing refutes nothing

#640 — six tests in `test_bank_transaction_reconciliation_coverage` red in CI shard 7 — had
been open for weeks behind a body listing six non-reproducing configurations and five
refuted hypotheses. The most load-bearing row:

> all 111 shard-7 modules, in CI's order, in ONE process — **pass** — 2107 tests, 0 failing

That refuted hypothesis 2, in-process co-tenancy. The `OrderedSubsetRunner` recipe published
alongside it subclasses frappe's `ParallelTestRunner` and overrides `get_test_file_list`. But
`ParallelTestRunner.__init__` only calls `setup_test_file_list()`. **Nothing calls
`setup_and_run()`.** Run verbatim, the snippet exits 0 with zero test output.

So the number that closed the most promising line of investigation was produced by an
instrument that ran no tests. With a working runner, two modules in one process reproduce all
six failures on base and none on the fix.

> **A pass is only as good as the instrument. `0 failing` from a run whose test count you did
> not sanity-check is not a refutation — and a round number that arrives without a control
> that it *can* fail deserves suspicion.**

This is the same family as `bench console < f.py` not halting on an exception
(2026-08-27). Different tool, identical shape: the probe cannot report its own failure.

### The actual cause was one ambient field

Single-variable control — one site, base commit, module alone, nothing changed but the value:

| ambient `Mollie Settings.mollie_clearing_account` | result |
|---|---|
| `Mollie - _TC` (an account on the **INR** `_Test Company`) | `FAILED (failures=5, errors=1)` |
| `Mollie - TPIC` (the EUR test company) | `Ran 68 tests ... OK` |

Several settlement tests never open a `_mollie_settings(...)` context, so they booked against
whatever the Single held. That is the `INR` in the error the issue quoted, surfaced to the
test only as `assertTrue(ok)` with the cause in the Error Log.

**The poisoning co-tenant, named:** `ensure_mollie_reversal_accounts`
(`mollie/tests/mollie_test_helper.py`) creates an Account called `Mollie` on
`Verenigingen Settings.company`, calls `_ensure_mollie_clearing_configuration`, and
**commits**. Three refund/chargeback modules reach it. Its write is gated on
`configured_company != company` — so on a site whose `Verenigingen Settings.company` is
already the EUR company it is a no-op. **That gate is why this read as environmental rather
than order-dependent for weeks.**

---

## 3. My first fix for it was narrow, and I explained the narrowness confidently

I pinned only `mollie_clearing_account`, having watched pinning all three break three
fee-counting tests, and wrote this into the commit message:

> That is a real behaviour difference and belongs in its own change, not smuggled into a
> fixture fix.

Both halves of that were wrong.

**It was not a behaviour difference.** Pinning all three lets the settlement **payout leg**
book — correctly. The tests broke because `_fee_journal_entries` matched **any** submitted
Journal Entry whose free-text `user_remark` contained the settlement id, so it counted the
payout leg as a fee entry. The discriminator was already in the same file:
`_fee_entries` / `_payout_entries` key on `custom_mollie_settlement_id` **and**
`voucher_type` (`Journal Entry` vs `Bank Entry`), and
`test_the_payout_leg_is_not_mistaken_for_the_fee_entry` exists because production had this
exact confusion. Retiring the misnamed helper also removed an **unescaped LIKE wildcard** —
settlement ids carry `_` — the class already fixed three times here
(`reversal_idempotency`, `sepa_mandate_manager`, `periodic_donation_operations`).

**And narrowing left the defect live.** With only the clearing account pinned, setting ambient
`mollie_bank_account = Mollie - _TC` takes base from 5 failures to **8, plus an uncaught
`Please check Multi Currency option`** out of `process_mollie_settlement`. Shipping that would
have re-armed the same weeks-long investigation on the next field.

> **A deferral is a claim. "This belongs in its own change" needs the same evidence as any
> other assertion — and the three-line explanation I wrote for it was the strongest signal in
> the file that I had not checked.**

That is the *second consecutive handoff* to record this shape (the last one: a guard, a
comment asserting the property, and the guard not enforcing it). It is now the recurring one.

### I also reimplemented a fixture that already existed, and the ratchet could not see it

`tests/fixtures/mollie_account_fixtures.py` already provides `ensure_mollie_gl_accounts`
(`@shared_fixture`) and `provisioned_mollie_settings`; `tests/support/mollie_settings.py`
provides `pin_mollie_clearing_account`. I wrote a second copy of both under new names.

**`duplicate_helper_validator.py` keys on NAMES.** A rename is how a clone family hides — the
census reported 569/1388 before and after, unchanged. CLAUDE.md's Pre-Implementation Checklist says
to search `services/`/`utils/` first; for test code that means **`tests/fixtures/` and
`tests/support/`**, and I did not.

Using the real fixture also fixed something my copy had silently dropped: `singleton_backup`'s
restore **commits**. `addCleanup` is LIFO and an uncommitted restore is discarded by the
framework's own rollback — that is #312, and the sibling helper's docstring says so in as many
words.

---

## 4. A green develop is not a control for a red branch shard

PR #650 reddened `Tests / Tests (7/12)` with #640's six failures. `origin/develop`'s own tip
was **green on shard 7**. So the obvious control said *my branch broke it*.

Same shard number, 110 modules both, module last (110/110) in both — but a materially
different **composition**. Editing any test file re-packs every bin. What settled it was
running the module alone against an untouched `origin/develop` worktree and against the
branch, back to back on the same site: identical six failures, identical error string. Plus
zero occurrences in the shard log of any string my change introduces.

> **Diff the module *sets*, not the shard numbers — and when develop's CI and your branch's
> CI disagree, the discriminating run is base-vs-branch locally, not develop's last green.**

The merge order came out of this: **#651 first**, then #650 rebased onto it. Shard 7 then went
green on #650 too, which is what confirmed the two reds were one defect rather than a
coincidence.

---

## 5. Corrections I had to make in public

Recorded because they were avoidable, and both were the same error.

* **I commented on #640 having read the first ~50 lines of its body.** I announced "it
  reproduces locally now" as a new finding — the body already said a dirty `test_site_1`
  reproduces it — and proposed a mechanism (the shard-7 predecessor changing to
  `test_mollie_configuration_service`) that the body had **already refuted by direct
  experiment**. Corrected on #640 and on #650.
* **`Net -42 lines`** in a commit message was the delta against my own previous attempt, not
  against develop. It is +86.
* **I diagnosed a monitor alert as "conflating the legacy pending status."** The measurements
  were right (30/30 green, `mergeable_state: clean`); the mechanism was a guess stated as a
  finding. I have no visibility into that monitor.

Rule 5 in CLAUDE.md says read the comments, not just the body. The complement is now also
earned: **read the whole body before commenting on it.** Both of my errors above were
already answered in text I had open.

---

## Left open

* **#648** — `deduplicate=True` is **inert** under `enqueue_after_commit=True`. frappe checks
  for a duplicate **eagerly at `enqueue()` call time**; the actual push is deferred into an
  `after_commit` closure with no second check. Measured with a control: after-commit +
  deduplicate pushed **2** jobs for one `job_id`; immediate + deduplicate pushed 1. Also:
  neither payment-history handler respects `frappe.flags.in_migration` /
  `bulk_invoice_generation`, where the Sales Invoice route does.
  **Do not fix this by adding the flag guard until you have confirmed what rebuilds payment
  history after an eBoekhouden migration** — otherwise it trades a scaling problem for a
  correctness gap. Measured on veg11: 13 submitted JEs with a Customer party row, **0** naming
  a member's customer. Not urgent.
* **#649** — two more instances of #645's class: Sales Invoice credit notes (the GL posts
  against `return_against`, so the **original** invoice's outstanding moves, but the app
  queues a refresh only for the credit note) and Payment Reconciliation
  (`ignore_validate_update_after_submit` + `save()`, dispatching only
  `on_update_after_submit` on the Payment Entry, for which nothing is registered).
  Source-verified; 0 occurrences on veg11 today.
* **#647** — the previous handoff PR, green and mergeable, untouched.
* **The `OrderedSubsetRunner`** is worth having under `scripts/testing/` — it is the missing
  instrument for every order-dependent shard failure — but **fix it first**: it needs
  `setup_and_run()`, and deriving dotted names from `verenigingen.__file__`'s parent rather
  than splitting on `/apps/` makes it work from a worktree.

## One process note

The skeptical review was run before opening each PR, per standing instruction. It found a
shipped-inert fix on one and a half-fix plus a duplicated fixture on the other. On both, my
own commit message had confidently explained the thing that was wrong. It changed the outcome on both
PRs here, and on both the tell was prose I wrote defending a choice. I have not counted how
often that has held across sessions -- but it is the second consecutive handoff to name it,
which is the part worth watching.
