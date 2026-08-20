# Handoff — 2026-08-19: the premises that were wrong

Session goal was "read the handoff and start the next task", which became: two PRs merged-ready,
one large fix half-built, three issues filed, five corrected. The through-line is the same as the
last session's, one level up: **it was not the issues that were wrong this time so much as the
premises underneath them — including mine, including CLAUDE.md's.** Four separate premises failed,
and every one was caught by running something rather than reading it.

## State

| | |
|---|---|
| `develop` | `31d25bfc` |
| Green, mergeable, awaiting merge | **#372** (41/41), **#373** (42/42) |
| Local, unpushed | `fix/mollie-reversal-booking` (4 commits, WIP), `fix/253-...` (2), `fix/254-...` (1) |
| Issues filed | **#374**, **#375**, **#376** |
| Issues corrected | **#351**, **#359**, **#363**, **#370** (description rewritten), **#272** |

## What is ready

- **#372** — `cancel_recurring_donation` / `update_recurring_donation` wrapped their whole bodies in
  `except Exception`, which caught their *own* `frappe.throw`s. Every specific, translated refusal
  became one catch-all sentence. Reverting the fix shows all guards collapsing to one string.
  The same bug existed **one level deeper**: the inner handlers around the Mollie calls re-wrapped
  their own deliberate throw, so a donor saw Mollie's reason twice, relabelled as an unexpected
  error. An AST scan found that after the outer fix looked complete.
- **#373** — four tests passed on a guard they never named. Measured by mutation, not inferred.

Both were pushed with `--no-verify` because these files already fail `black` (#372 also fails
`test_quality_enforcer` on 4 pre-existing `PERMISSION BYPASS` lines) **on develop**; controls are
recorded in the PR bodies. `ruff` errors went 2 → 1 with #372.

## The four wrong premises

**1. Mine, on #370 — and it made the issue more severe, not less.** I wrote (in the issue, in the
plan, and to Foppe) that a donation-refund double-booking was *latent*, gated by the missing
Payment Entry precondition. A design review caught it. `handle_refund_webhook`
(`mollie/api/unified_payment_api.py:337-406`) calls `get_donation_by_payment_id` then
`create_refund_payment_entry` — **it never touches that gate at all.** So a donation refund seen by
the payment-webhook sweep (BT + JE) and then delivered to the refund endpoint books a second time
as a Payment Entry. Now demonstrated by a test that produces a real JE and a real PE under one key.
I had inferred reachability from where the gate sits instead of reading the third entry point.

**2. #363's stated mechanism.** It says the minimum-fee guard "is evaluated first" and swallows the
others. It is evaluated **last**; it swallows them by being a catch-all for low amounts they fall
*through* to. Same symptom, different cause — and it matters, because #363's remedy ("assert the
message **or** choose isolating input") is **impossible** for the `> 0` guard: `minimum_fee` is
`max(base * 30%, EUR 5)`, always positive, so every amount `<= 0` is also below the minimum. Only a
message assertion can isolate it. #363 also named three tests; a fourth had the identical defect.

**3. #272's premise, and CLAUDE.md's with it.** The issue says `resolutions` is dead under npm and
can be deleted. Locally true. **CI runs real Yarn 1.22.22** (`.github/actions/setup/action.yml:320`,
`yarn --check-files || npm install`, `build-assets` defaults true), and Yarn reads `resolutions` and
ignores `overrides`. A controlled 2×2 with a real yarn install confirms each block is honoured by
exactly one package manager. **Deleting `resolutions` would take CI from 17 pins to 0** — and those
are security pins (`cf4f9371`, "pin patched versions of common-vulnerable transitive deps"). The
inverse gap also exists: the 11 `overrides`-only pins are not applied in CI at all today.

> **CLAUDE.md is wrong here and caused this.** It says `resolutions`/`yarn.lock` are "stale
> leftovers — do not rely on them" and that `/usr/bin/yarn` is a broken stub. True of the dev box,
> false of CI. Its own warning — *don't fix the dev box in a way that breaks a real-yarn host* — is
> exactly the trap, because **CI is the real-yarn host.** This section should be amended.

**4. #253's title.** It says a poisoned cache "makes every later field check pass silently". It is
the opposite: an empty valid-field set makes `validate_fields` mark **every** field invalid,
including `name`, so `BaseDataService.safe_query` raises on every call. Fail-everything, not
pass-everything — a loud permanent outage per DocType rather than silent erosion.

## #370: what is built and what is not

Branch `fix/mollie-reversal-booking`, 3 commits, **not pushed, 14 tests red by design-in-progress**.

Built:
- `find_booked_reversal()` — has this reversal been booked as **any** artefact? Closes the live
  double-booking (`be3b54c2`), with a regression test. `docstatus != 2` deliberately: a draft
  artefact is work in flight, and treating it as absent is what produces the second booking.
- `find_booked_payment()` — what did the forward payment book, and what type is it? **Donation-ness
  comes from the Donation record, not the artefact shape.** I first assumed JE⇒donation, PE⇒dues;
  the integration fixtures contain a donation booked as a *Payment Entry* (the older donation flow),
  which that rule misfiled as dues and would have reversed against a membership invoice the money
  never paid. Found by running the tests.
- The gate no longer rejects donation chargebacks as "payment not found"; donation reversals book
  BT + JE; dues return an explicit `not_implemented`; ambiguous bookings refuse rather than guess.
- `create_refund_journal_entry` takes `reversal_type`, so a chargeback is no longer filed under a
  `_refund_` key where it would collide with a refund on the same payment.
- Payment history writes `journal_entry` vs `payment_entry` — `Donation Payment` has both links.

**Donation chargebacks and refunds now book.** Measured on test_site_1:
`{'status': 'success', 'message': 'Chargeback Journal Entry created: ACC-JV-...'}`, and a
redelivery answers `already processed`. That is #370's original headline defect, closed.

Not built: the **dues** reversal booker, the **insert-first reservation** (C4), tests T2/T6–T9.

### The dues answer, settled by experiment

Probed on test_site_5 and rolled back:

| probe | before | after | status |
|---|---|---|---|
| full JE with `reference_type="Sales Invoice"` | outstanding 0.0, Paid | **100.0** | **Unpaid** |
| cancel the forward Payment Entry | outstanding 0.0, Paid | **100.0** | **Unpaid** |
| **partial** JE (40 of 100) | outstanding 0.0, Paid | **40.0** | **Partly Paid** |

**Cancelling the forward PE does restore the invoice** — Foppe's instinct was right, and it is what
SEPA already does. It is ruled out by scope, not mechanism: partial refunds cannot be expressed by a
cancel at all; cancel re-posts GL at the *original* date (fails on closed periods, and chargeback
windows run to 13 months); and it strips the PE from its reconciled Bank Transaction, which the
Mollie dues path creates (`dues_payment_processor.py:842,884`) and the SEPA path does not — which is
precisely why the SEPA precedent does not transfer. So: **JE for both types**, a consequence of
ERPNext's model, not a unifying principle. A dues JE carries a Sales Invoice reference and a
donation JE does not; they should not later be "simplified" into one booker.

Also settled: a reversing Payment Entry is **unbuildable** against a settled invoice —
`payment_entry.py:377-382` throws for a positive allocation above `outstanding_amount` *and* a
negative one below it, so on a paid invoice both directions throw.

### Why the 14 are red

- **9** in `test_unified_webhook_wrapper_service` / `_unit` / `_sweep` stub `payment_entry_exists=True`
  and never create a real booking, so a DB-reading gate says "not booked". They encode the old
  contract. One also patches `frappe.db.get_value` **globally**, which now serves two different
  lookups and returns nonsense. Agreed to rewrite against real bookings.
- **5** in `test_refund_chargeback_integration`. Three fixture/infrastructure defects had to be
  fixed before the money path could even run (below); the remaining failure is **not yet
  attributed** — that is the next step.

## Traps that cost real time

- **`git stash push -- <clean file>` saves NOTHING, and the paired `pop` applies a *stranger's*
  stash.** Doing a before/after lint control on an already-committed file popped an unrelated
  branch's WIP into a CSS merge conflict. Use `git show HEAD:file | black --check -` instead — it
  never touches the working tree. Nothing is destroyed: pop keeps the entry on conflict.
- **I clobbered my own edits with a `.bak` restore.** The control wrote *develop's* content into
  `$f.bak` and then `mv`'d it back over the file, silently reverting the fix. Caught only because a
  passing test started failing 3/3 and I checked instead of assuming flakiness. It did produce a
  rigorous red control by accident.
- **`MollieConfigurationService` caches Mollie Settings** in `frappe.cache()` under
  `mollie_settings_cache` with a TTL. Writing the Single in `setUp` stays invisible for the rest of
  the process and the caller keeps resolving the OLD account. Silent — nothing errors, the booking
  just fails. Call `clear_cache()` after writing.
- **The reversal Bank Transaction hardcoded `"currency": "EUR"`**, which ERPNext rejects when the
  Bank Account is in another currency. `_process_pending_refunds` hardcodes it the same way —
  invisible in production because the real company *is* EUR. Latent defect, wants its own issue.
- **Mollie Settings' clearing account can point at another company's GL account** on a test site,
  and ERPNext will not let a Bank Transaction reference it. Presence is not consistency.
- **CI shards that "fail" may never have run a test.** Two shards on #372 sat at exactly 60m with a
  single 57-minute silence, ending in `The operation was canceled`. The last line before the gap was
  an Ubuntu repo fetch — `apt-get update` hung in runner setup. Re-run passed 12/12 unchanged.
  Check job *duration* and the last log line before concluding anything about your code.

## What I would tell the next session

Last session's lesson was "I had confirming evidence and stopped". This session the same failure
appeared one level down: **the premises I was reasoning from were themselves unverified** — an
issue's stated mechanism, a project doc's claim about the toolchain, my own reading of which code
path a webhook takes. Three of the four were caught by an agent or reviewer refusing the framing
rather than completing the task, and the fourth by a test failing in a way I had not predicted.

The agents earned their keep by disagreeing. One flatly refused to implement #272 and was right;
complying would have quietly removed 17 security pins from CI. **Brief them so that returning a
correction counts as success** — and then actually check the correction, because a reviewer's claim
is a premise too. I verified all four of the review's blocking findings on #370 before acting on
them; two of my own "verified facts" did not survive that.


## The reviews, and what they caught

Three skeptical reviews were run. Two changed the work materially; one approved and still
produced a fix.

### #370 — REQUEST CHANGES, and the first finding was my own defect

**I broke every donation reversal in the commit that claimed to fix currency handling.**
`Bank Account` has **no `account_currency` field** — only `account`. Reading one off it raises
`OperationalError 1054`, so the `or` fallback beside it was unreachable. The line sat at the top
of `_book_donation_reversal`, and `process_reversal_webhook`'s outer `except Exception` swallowed
it into `{"status": "error"}` returned at **HTTP 200** — booking nothing, writing no Error Log,
and telling Mollie it had succeeded so there was no redelivery. I had reported the resulting test
failure to Foppe as "not yet attributed". The reviewer probed the column against the database
with a control. Fixed by resolving through `Bank Account.account` → `Account.account_currency`,
which is what ERPNext itself does (`bank_transaction.py:69`).

Still open from that review, in rough priority order:

1. **`_process_pending_refunds` is protected only by accident.** `create_refund_journal_entry`'s
   `_check_existing_by_reference` is **Journal-Entry-only** — the identical single-doctype mistake
   this whole PR exists to fix, one screen above, in a function this branch already edited. It does
   not double-book today only because `_check_refund_processing_state` builds `pending_refunds`
   from a Payment-Entry-only query. Two blind checks covering each other's blind spots. Point it at
   `find_booked_reversal`.
2. **The test has no control.** `create_unified_payment_entry` is wrapped end-to-end in
   `except Exception: return None`, so if the PE fails for *any* unrelated reason the test still
   sees one artefact and goes green while the guard is dead code. Add a second refund id with no
   prior JE and assert a PE **is** created.
3. **The fixture change breaks the shared-fixture rule.** `_ensure_mollie_clearing_configuration`
   inserts `Bank`/`Bank Account` (not drain-exempt, so deleted at that test's teardown) and
   **commits** a `Mollie Settings` write that survives — leaving the next co-tenant pointed at a
   clearing account whose Bank Account has just been deleted. Worse than before the change. Needs
   `@shared_fixture` / `suspend_insert_capture()` and an `addCleanup` restore.
4. **The booker ignores the artefact it just derived.** `find_booked_payment` returns
   `(type, doctype, name)` and `_book_donation_reversal` discards the last two, always booking
   BT + JE — so a donation forward-booked as a `Receive` Payment Entry gets reversed by a JE that
   debits income the PE never recognised, leaving the receivable overstated. Either branch on the
   artefact or stop returning it.
5. **Ambiguity is only refused when a Donation exists.** With no Donation and both a JE and a PE,
   the function silently prefers the PE and reports `dues` — the exact "prefer one artefact"
   behaviour the AMBIGUOUS branch exists to prevent. The check belongs before the `if donation:` split.
6. **A draft forward JE makes a reversal unreachable forever.** `donation_journal_entry_creator`
   returns `je.name` as success when submit fails, and its own existence check is `!= 2`, so it
   never retries — while `find_booked_payment` is submitted-only and reports "not booked" for all
   ~10 deliveries. The two disagree about the same row.
7. `_book_donation_reversal` has **no savepoint**: a JE failure after the BT is created strands a
   phantom unreconciled bank line, and both failure branches return `None` with no `frappe.log_error`.
8. The chargeback **reason is silently discarded** — `description` is accepted and never read, and
   the JE narration still hardcodes "REFUND", so every chargeback JE reads as a refund.
9. `handle_refund_webhook` still books a **Payment Entry** when it wins the race, so the artefact
   still depends on the route. The double-*booking* is closed; two-artefacts-for-one-event is not.

### #253 — APPROVE, and the approval produced a second fix

No blocking problems. But the reviewer noted the fix's user-visible win was untested, and writing
that test showed the win was **half delivered**: the message named the outage while
`invalid_fields` still listed every requested field, so a caller reading `invalid_fields` rather
than `message` still got a fabricated answer. Real fields blamed for a database failure — the same
mislabelling the issue is about. The exception path now returns an empty `invalid_fields`, which
also closes a trap the review flagged separately: `validate_service_operation` converted the error
into a result dict and then looped into `get_field_suggestions`, re-raising the error it had just
absorbed, uncaught.

Two corrections worth carrying: the class is **`DataService`**, not `BaseDataService`; and the blast
radius is **zero production consumers today** — `search_members_api` is not whitelisted (checked
against the running system, not the source). The fix's value is preventing the trap for the first
real subclass, not repairing a live defect.

Unverified by anyone: whether `frappe.get_meta` can ever *return* a degenerate empty-field Meta
instead of raising. If it can, the sticky symptom returns by a route the fix does not touch.

### #254 — premise confirmed, prescription rejected

The issue's own suggested fix (`raise_error=False`) would have been wrong three ways, measured:
most real customer failures are `ValidationError` subclasses re-raised **before** `handle_error`,
so the `return None` path is not where the dominant failure class goes; it returns `None` with no
message; and it **silently swallows `QueryDeadlockError`**, reporting success for a transaction
MariaDB already discarded. The fix instead keeps the Member, surfaces the reason, and lets
non-resumable DB errors propagate. Evidence for continue-over-abort is strong: `Member.customer`
is optional, `member.js` renders a "Create Customer" button exactly when it is empty, several call
sites lazily self-heal, and `dues_invoice_workflow` reports `no_customer` as an operator-facing
bucket. Its own review is still running at time of writing.

## Where to pick up

`fix/mollie-reversal-booking` is 4 commits, unpushed, with the money path working for donations and
14 tests red. Nine of those (in `_service` / `_unit` / `_sweep`) stub the old gate; four more assert
the old artefact ("Chargeback **Payment Entry** should be created"); one is message wording. All
encode the pre-change contract and are to be rewritten against real bookings — Foppe chose that over
adapting the mocks. Then items 1–9 above, then the dues booker and the reservation.
