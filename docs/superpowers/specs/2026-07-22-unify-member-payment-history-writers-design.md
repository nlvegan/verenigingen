# Unify Member Payment-History Writers onto One Invoice-Row Builder

**Date:** 2026-07-22
**Status:** Approved (design), pending implementation plan
**Builds on:** PR #174 (payment-history double-write reconcile) — population is now async-only.

## Problem

The `payment_history` child table on `Member` is written by several code paths
that have drifted apart:

- **Incremental writer** — `FinancialHistoryBatchProcessor`
  (`utils/financial_history_batch_processor.py`). The everyday async path.
  Reacts to Sales Invoice and Payment Entry doc-events and adds/updates/removes
  a single invoice row via `MemberFinancialHistoryManager.add_or_update_entry`.
  Row bodies come from `member._build_payment_history_entry(invoice)` →
  `PaymentHistoryEntryBuilder.build_from_invoice_doc`.
- **Full rebuild #1** — `PaymentHistoryService.load_payment_history_batched`
  (`services/member/payment/payment_history_service.py`). Clears the table and
  rebuilds from batch queries. Builds invoice rows **inline** (does not use the
  shared builder) and adds "Unreconciled Payment" / "Donation Payment" rows via
  `_add_unreconciled_payments`.
- **Full rebuild #2** — `background_jobs.load_payment_history_batch_optimized`
  (`utils/background_jobs.py`). A near-duplicate of rebuild #1, also inline, also
  emitting the unreconciled/donation row-types. This is the rebuild actually
  wired to the `load_payment_history()` mixin (via
  `refresh_member_financial_history_optimized`).

So the same three row-types must be kept in sync across three implementations,
and the "unreconciled/donation payment" row-type exists in two of them.

### Ground truth (veg11 production data, 2026-07-22)

The premise behind the unreconciled/donation row-types does not hold on real
data:

| Check | Result |
|---|---|
| `payment_history` row `transaction_type` distribution | 437 Membership Invoice, 52 Regular Invoice. **Zero** payment rows. |
| Member-customer Payment Entries | **0** total (site has 1704 other Customer PEs). |
| Member Sales Invoice status | 467 / 467 Unpaid. |
| Donations | 60, tracked on the **Donor** record (`donor_history`, `pledge_history`), not on `Member`. |

### Corrected financial model (per domain owner)

1. A Sales Invoice always exists first (or should).
2. Cash arrives as a **Bank Transaction**.
3. At reconciliation a **Payment Entry is created referencing that SI**; the SI
   then shows paid.
4. There is no such thing as a member Payment Entry without an SI.
5. One-off donations are Journal Entries; donation tracking lives on the Donor
   record, not the member ledger.

Therefore `payment_history` is legitimately an **invoice ledger** — invoice rows,
each carrying payment status derived from the PE→SI reference. The
"Unreconciled Payment" and "Donation Payment" row-types model an entity
(member PE without SI) that does not occur, and have produced zero rows in their
lifetime. They are dead code.

## Goal

Both writers track the **same record types** by construction. Concretely:

1. `payment_history` contains **invoice rows only** (Membership Invoice / Regular
   Invoice), each with PE-derived payment status.
2. The dead PE-based row-type logic is removed.
3. The two full rebuilds are collapsed into one implementation.
4. Incremental and rebuild both build rows through the single
   `PaymentHistoryEntryBuilder`, so they cannot diverge again.

## Design

### Workstream 1 — Delete the phantom PE row-type logic

The "reader before you delete a writer" rule applies. The only real readers of
these `payment_history` row-types (excluding the unrelated `Donation Payment`
**child DocType** on Donation, and unrelated notification/SEPA labels) are:

- `public/js/member/js_modules/payment-utils.js:160-162` — UI display branches
  for `'Donation Payment'` / `'Unreconciled Payment'` rows.
- `verenigingen/doctype/member/mixins/financial_mixin.py:149-151` — summary
  counters keyed on those `transaction_type` strings.

Changes:

- Remove `PaymentHistoryService._add_unreconciled_payments` (lines 450-528) and
  its call site (lines 206-209).
- Remove the unreconciled-payment block in
  `background_jobs.load_payment_history_batch_optimized` (~line 766).
- Remove the JS display branches in `payment-utils.js`.
- Remove the `donations` / unreconciled counters in `financial_mixin.py` (they
  would always be zero).

### Workstream 2 — Collapse the two rebuilds into one

- Canonical home: **`PaymentHistoryService.load_payment_history_batched`**
  (service layer, `StatelessService`, integrates `PaymentCoverageService`).
- `background_jobs.load_payment_history_batch_optimized` and
  `refresh_member_financial_history_optimized` become thin wrappers that keep
  their orchestration (30-minute cache, `member_doc.save()`) but delegate row
  population to the service.
- Rewire the `load_payment_history()` mixin so the single service
  implementation is the one that runs.

Rationale for choosing the service over the `background_jobs` implementation
(they are near-duplicates today, so one must win):

1. **Correctness gain, not a lateral move.** The service derives coverage dates
   through `PaymentCoverageService` (dues-schedule overrides + validation); the
   `background_jobs` version only reads the raw `custom_coverage_*` fields and so
   silently drops schedule-derived coverage. Consolidating onto the service
   *improves* coverage-date accuracy.
2. **Separation of concerns.** `background_jobs.py` should own job orchestration
   (enqueue / cache / save / status); the service should own row content. The
   only reason a full rebuild leaked into `background_jobs` is that boundary was
   never drawn.
3. **Convention.** This app homes business logic in `services/`.

Cost: `load_payment_history()` is currently wired to the `background_jobs` path,
so we rewire it — a change to a hot path, but a cheap one. "It is the currently
wired one" is the only argument for keeping `background_jobs` canonical, and it
is an accident of history.

### Workstream 3 — Unify onto the shared builder (anti-divergence core)

- The canonical rebuild builds invoice rows via
  `PaymentHistoryEntryBuilder.build_from_query_row` (batch mode — caller
  pre-fetches, no N+1) instead of inline construction.
- Reconcile the builder's two methods to emit **identical fields**. Today
  `build_from_query_row` omits fields that `build_from_invoice_doc` sets:
  coverage dates, `has_mandate`/`sepa_mandate`/`mandate_status`/
  `mandate_reference`, `reconciled`, `payment_method`. Bring `build_from_query_row`
  up to parity.
- Collapse the **three** membership-detection signals to one. Today
  `build_from_invoice_doc` uses `invoice_doc.membership`; `build_from_query_row`
  uses `row.membership_id`; the rebuilds use `is_membership_invoice`.

  **Verified** (`services/billing/invoice_generator.py:686-694`): the dues
  generator sets `is_membership_invoice = 1` **unconditionally**, but sets
  `invoice.membership = member_doc.current_membership_plan` only **when
  `current_membership_plan` is truthy**. So the two are *not* guaranteed to be
  set together — a membership invoice can exist with the boolean set but no
  `membership` link.

  Decision (split classifier from reference):
  - **`is_membership_invoice` (the reliable, unconditional boolean) classifies
    the row type** — `transaction_type = "Membership Invoice"` if set, else
    `"Regular Invoice"`. Both builder methods use this one signal.
  - **The `membership` link only supplies the reference** — when present, set
    `reference_doctype = "Membership"`, `reference_name = invoice.membership`;
    when absent, leave the reference blank but keep the row classified as a
    Membership Invoice.

  The rebuild's batch query selects both `is_membership_invoice` and
  `membership` and feeds them to `build_from_query_row`.

  **Intended behavior change:** `build_from_invoice_doc` today classifies purely
  on `invoice_doc.membership`, so a membership invoice lacking the link is
  currently mislabelled "Regular Invoice". Under this decision it correctly
  becomes "Membership Invoice" (with no Membership reference). This is a
  deliberate fix, not a regression — call it out in the plan and cover it with a
  test.

Outcome: incremental (`build_from_invoice_doc`) and rebuild
(`build_from_query_row`) provably produce the same row for the same invoice.

### Workstream 4 — Incremental writer needs no new record type

Because there are no PE-without-SI rows, the incremental writer already tracks
the correct record type (invoices). A reconciliation PE fires the Payment Entry
hook → `drain_member_payment_history` re-queues the customer's invoices →
`queue_payment_update` → the invoice row's payment status flips to Paid. Parity
holds with no new "payment-entry operation" on the batch processor.

## Testing

Real-DB integration tests (no business-logic mocks, per project rules):

- For a member with membership + regular invoices, assert that the row produced
  by the incremental builder and the row produced by the rebuild are
  **field-identical** (regression guard against future divergence).
- Reconcile an invoice with a PE and assert the invoice row's `payment_status`
  becomes `Paid` / `reconciled = 1` via the incremental path.
- Assert no row with `transaction_type` in {"Unreconciled Payment",
  "Donation Payment"} is ever emitted by the rebuild.

## Out of scope

- Bank-transaction / Journal-Entry donation tracking in the member ledger —
  donations belong on the Donor record.
- Volunteer expenses (`volunteer_expenses`) — a separate child table, written
  only by the incremental path; not touched here.
- Why veg11's member Sales Invoices are all Unpaid — an accounting/reconciliation
  operations question, not a defect in this code.

## Risks / notes

- The unrelated **`Donation Payment` DocType** (child table on Donation, used by
  the Mollie/donation payment flow) must not be touched — it shares a name with
  the phantom `transaction_type` string but is a different thing.
- `build_from_query_row` currently produces fewer fields than the doc path; any
  consumer relying on the rebuild's current (partial) rows must be re-checked
  when the two methods are brought to parity — parity can only *add* fields the
  incremental path already sets, so this should be safe, but verify.
