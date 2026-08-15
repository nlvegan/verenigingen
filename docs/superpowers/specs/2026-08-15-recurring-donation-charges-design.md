# Design — booking recurring donation charges (issue #345, part A)

**Status:** approved design, not yet implemented
**Blocks:** #346 (which closes #343)
**Branch:** `fix/recurring-donation-charge-booking`, off `fix/donation-subscription-activation`

## The problem

Mollie charges a recurring donor every period. Nothing in this app books those charges.

Two independent causes, both measured:

1. **Subscriptions carry no `webhookUrl`.** `_activate_direct_subscription_after_first_payment`
   (`verenigingen_payments/utils/payment_gateways.py`) builds `subscription_data` without one.
   Every `created_from: "direct_subscription"` subscription in the Mollie test account has
   `webhookUrl: None`. Mollie therefore notifies nobody when it charges.
2. **Even a delivered charge cannot be matched to its donation.** The live path resolves the
   donation with `find_donation_for_payment_by_id`, which matches `Donation.payment_id` — the
   *first* payment's id. A recurring charge has a new `tr_` id, so the lookup returns nothing,
   the handler returns `status: error`, the API layer maps that to HTTP 500, and Mollie retries
   ten times over 26 hours and gives up.

Net effect per charge: no Bank Transaction, no Journal Entry, no Donation, no donor history.
The money arrives at Mollie and never reaches the ledger.

This is worse than the bug #346 fixes. Before #346 a recurring donor was charged once and never
again — an under-charge, visible to the donor. After #346 they are charged every period into an
unbooked void. Hence the blocker.

## Measured facts

Against the Mollie **test** API, read-only, on existing subscriptions in the account:

- A subscription-generated charge carries `sequenceType: "recurring"`, `subscriptionId`,
  `customerId`, `mandateId`.
- The subscription's `metadata` and `description` are **copied verbatim onto every charge**. A
  charge of a donation subscription therefore already carries
  `{"payment_id": "tr_<first>", "donation_id": "Assoc-Dnt-2025-00752", "created_from":
  "direct_subscription", ...}`. Note `metadata.payment_id` is the **first** payment's id, not the
  charge's own — anything reading it as "this payment" is wrong.
- `metadata` is **`null`** on charges of a subscription that has none (`sub_5euSBaLzqF`). The copy
  is faithful, including copying nothing. Code must not assume a dict.
- Charges are created `status: "pending"`, `method: "directdebit"`, `paidAt: null`, and settle
  later. **No charge in the test account has ever reached `paid`** — so the `paid` branch cannot
  be exercised end-to-end against Mollie and must be driven by a fake built from a real payload.
- `Mollie Settings.get_webhook_url()` resolves to `mollie/api/webhooks.py::mollie_payment_webhook`,
  which is `allow_guest=True` and delegates to the unified handler. It is the reachable endpoint.
  `get_subscription_webhook_url()` is not: see #343.

## Decisions

### D1 — one Donation per charge

A recurring charge creates its own `Donation`, not a `Donation Payment` child row on the original.

The reason that survives inspection is `PeriodicDonationAgreement.update_donation_tracking`
(`periodic_donation_agreement.py:123-139`): it sums the agreement's `donations` child table, which
`link_donation` populates one row per **Donation**, with no docstatus filter. On a payments-child
model `total_donated` would freeze at the first charge.

Two arguments made earlier for this decision do **not** hold and are recorded here so they are not
repeated: `anbi_operations.get_anbi_statistics` (`:444`, `:460`) and the `donation_summary` report
(`:72`) both filter `docstatus = 1`, while `Donation` has no `is_submittable` and every donation
the app inserts is `docstatus = 0`. Those queries aggregate nothing today. That is a separate
defect (see "Filed separately"); it is neither caused nor worsened here.

Against the decision, and handled below: the `Donation Payment` child table was plainly designed
for the model being rejected; it stays, and continues to record the payment history of a single
gift, including refunds of it.

### D2 — materialize the Donation, then let the existing pipeline book it

The charge's Donation carries `payment_id = <charge tr_>`. Once it exists,
`find_donation_for_payment_by_id` resolves it and the existing machinery —
`_handle_new_payment_processing`, `_handle_partial_processing`, refund and chargeback processing —
runs unmodified.

So the new code creates a document; it does not book anything.

**This is why the branch must not return early.** `check_payment_processing_state(..., include_mollie_api=True)`
(`webhook_wrapper_service_unified.py:448`) is not only an idempotency check: steps 3 and 4 inside it
(`unified_idempotency_manager.py:108-112`) are the **only** discovery of pending refunds and
chargebacks on the webhook Mollie actually calls. Mollie signals a refund by POSTing the payment's
`webhookUrl` with the same `id=tr_...`. A branch that handled the charge and returned would strand
every refund and chargeback of every recurring charge, while first payments kept theirs.

### D3 — `recurring_origin_donation` link field

A new `Link` field on Donation (options `Donation`), set only on charge Donations.

- The donor portal's `get_recurring_donations` (`templates/pages/manage_donations.py:96-115`)
  filters `status="Recurring"`. Without a discriminator a monthly donor accumulates one identical
  "active recurring donation" row per charge, each with its own Cancel button, and the page makes
  2N live Mollie calls for one subscription.
- Resolving the origin by `mollie_subscription_id` alone is unsafe: `Donation`'s meta sorts
  `modified DESC`, so `frappe.db.get_value` would return the most recently touched *charge*, and
  each charge would be copied from the previous copy.

### D4 — uniqueness on `Donation.payment_id`

`payment_id` is currently a plain `Data` field with no unique constraint. A read-then-insert guard
alone does not hold against two concurrent Mollie deliveries, and the consequence is not benign:
the Bank Transaction and Journal Entry creators are idempotent by reference so the money books
once, but two Donation rows mean two donor-history rows and — because `link_donation` appends per
Donation name — **`total_donated` on the agreement doubles for that period**.

The repo has done this before (`Volunteer.member`, #268) and the shape is known: the JSON flag
plus a `pre_model_sync` patch that normalises `''` → `NULL` (non-Mollie donations have an empty
`payment_id`, and MariaDB treats `''` as a value but `NULL` as absent) and **throws** on any
duplicate it cannot resolve rather than deleting rows.

### D5 — emails

A charge Donation suppresses the new-donation confirmation (`after_insert` →
`send_donation_confirmation_email`) and keeps the payment confirmation (`on_update` →
`send_payment_confirmation_email`, which fires because `has_value_changed("paid")` is true on
insert). The donor was thanked when they signed up; what they need per period is the receipt.

### D6 — scope split

**Part A (this spec)** makes charges book correctly. **Part B** (separate spec) adds recovery: a
scheduled sweep, and delegating the recurring case from `PaymentTypeRouter`'s DONATION branch so
the existing `mollie_bulk_payment_discovery` admin page — which today counts every donation as
`skipped` — becomes the backfill tool rather than the sweep duplicating it.

Accepted risk of the split: between A and B, a booking that fails past Mollie's 26-hour retry
ladder is not recovered automatically. A's failure paths therefore have to be loud (see F5).

## Changes

### 1. `webhookUrl` on subscription creation

`payment_gateways.py`, both `_activate_direct_subscription_after_first_payment` and
`_activate_donation_subscription_after_first_payment`: add
`"webhookUrl": frappe.get_single("Mollie Settings").get_webhook_url()`.

Two constraints this interacts with:

- **The byte-identical-payload constraint.** The create reuses `idempotency_key=f"donsub-{payment.id}"`,
  and Mollie 400s a reused key whose parameters differ. `get_webhook_url()` is *not* deterministic
  across contexts: it is `frappe.utils.get_url()` + `?env={test|live}`, no `host_name` is set in
  either site config, so the base is derived from the request `Host` header in a request context
  and from `frappe.local.site` in a background one. Within one webhook retry ladder that is stable;
  across a deploy that adds this field mid-ladder it is not. Mitigations: the durable
  `_find_subscription_for_payment` guard already runs before the create and adopts an existing
  subscription, so a 400 cannot double-charge; and a Mollie 400 on key reuse must be classified
  `permanent` so `_handle_new_payment_processing` does not retry-loop into it.
- `_activate_donation_subscription_after_first_payment` has **no** durable guard, only the 1-hour
  key. It gets `_find_subscription_for_payment` too, for the same reason the other one has it.

**Ops note, not code:** setting `host_name` in `site_config.json` would make `get_url()`
context-independent. Recommended, out of scope here.

### 2. `ensure_donation_for_recurring_charge`

New module `verenigingen_payments/mollie/services/recurring_donation_charge.py`, one public
function, returning the Donation name or `None`.

```
ensure_donation_for_recurring_charge(payment) -> str | None
```

- Returns `None` unless `sequence_type == "recurring"` and a `subscription_id` is present.
- Returns `None` unless `status == "paid"`. A `failed`/`expired`/`canceled` charge writes a Mollie
  Audit Log row (`event_category: webhook_processing`, confirmed valid) naming donor, subscription
  and reason, and creates nothing.
- Existing Donation with this `payment_id` → return its name. Whether it still needs financial
  entries is not this function's question; the pipeline it falls through to already answers it.
- Resolve the origin donation (below). Absent → raise, so the caller returns an error and Mollie
  retries; audit-logged.
- Insert the Donation under a named lock keyed on the charge id, with D4's unique index as the
  real guard.

Fields on the new Donation:

| field | value |
|---|---|
| `donor`, `company`, `donor_email` | from origin |
| `amount`, `donation_date` | from the charge (`amount.value`, `paidAt`) |
| `payment_id`, `mollie_subscription_id`, `mollie_customer_id`, `mollie_mandate_id` | from the charge |
| `mode_of_payment` | mapped from the charge's `method`, **not** copied — the origin was iDEAL or card, the charge is always `directdebit`. Explicit map `{"directdebit": "SEPA Direct Debit"}` (that row exists), falling back to the origin's value when the method is unmapped or the mapped row is absent on the site. The field is `reqd=1`, so resolution must always yield something. Deliberately **not** `donation.create_mode_of_payment()`, which would insert a Mode of Payment literally named `directdebit` as a side effect of a webhook |
| `paid` | 1 |
| `status` | `Recurring` |
| `recurring_origin_donation` | origin's name |
| `donation_purpose_type`, `campaign`, `chapter_reference`, `specific_goal_description`, `fund_designation`, `donation_notes` | from origin |
| `anbi_agreement_number`, `anbi_agreement_date`, `belastingdienst_reportable` | from origin |
| `periodic_donation_agreement` | from origin, **unless** its status is not `Active`/`Completed` |
| `recurring_frequency` | from origin |

`donation_notes` is not cosmetic: `validate_donation_purpose` (`donation.py:233-238`) accepts
`purpose_type == "Campaign"` without a `campaign` link only when `"Campaign:"` appears in the
notes. Omitting it makes every charge of such a donation throw at insert.

`validate_periodic_donation_agreement` (`donation.py:171-172`) throws when the agreement is not
`Active`/`Completed`. A donor who cancels the agreement while the Mollie subscription keeps
charging would otherwise turn every subsequent charge into a hard insert failure — Mollie retries,
charge unbooked, which is the exact state this issue exists to prevent. So the link is dropped and
the anomaly audit-logged; the money still books.

### 3. Origin resolution — fix `DonationLookup.find_for_subscription_payment`

The function in `mollie/services/handlers/donation_lookup.py` already implements the right strategy
and is not called from the live path. It is **not correct as written**:

- `hasattr(payment, "subscription_id")` is `False` for a plain dict, so line 39 short-circuits to
  `None` for the normalized dict `_fetch_payment_from_mollie` produces.
- `getattr(payment, "metadata", {})` returns `None` — not `{}` — when the SDK object has a
  `metadata` property whose value is null, and `None.get("donation_id")` raises uncaught.

Its integration tests did not catch either: they build payments with `SimpleNamespace` and
`kwargs.setdefault("metadata", {})`. A fake more permissive than reality in the dimension under
test reports success exactly when the thing is broken — the trap named in the 2026-08-15 handoff.

Fixes: accept dict and object alike; treat a missing/null `metadata` as `{}`; and give the
`mollie_subscription_id` fallback `order_by="creation asc", limit=1` plus
`recurring_origin_donation is not set`, so it can only ever return an origin.

### 4. Wiring

In `process_payment_webhook`, after the classification `try/except` and **before** STEP 1:

- Call `ensure_donation_for_recurring_charge`, then fall through. Do not return.
- It must run for `DONATION` **and** `UNKNOWN` classifications, and also when classification
  *raised* — `Donor.mollie_subscription_id`, which `SubscriptionBasedClassification` needs, is
  written by `_update_donor_record` inside a broad `except` whose `False` return the caller
  ignores, so it is not reliably stamped. The branch must not depend on classification succeeding,
  and must not read a name bound inside the classification `try`.

### 5. Portal

`get_recurring_donations` gains `"recurring_origin_donation": ["is", "not set"]`.

## Failure handling

| case | behaviour |
|---|---|
| F1 charge not `paid` | audit-log if failed/expired/canceled; create nothing; `skipped` |
| F2 origin donation not found | error → Mollie retries; audit-logged |
| F3 Donation exists, no `journal_entry` | fall through; the existing partial-processing path resumes it. `_create_donation_financial_entries` returning `{"partial_success": True, "journal_entry_name": None}` is **truthy** and must be treated as failure, not success — the existing caller's `if not financial_result` does not |
| F4 PDA not Active | link dropped, audit-logged, booking proceeds |
| F5 charge abandoned after Mollie's 10 retries | **no record today.** Part B's sweep is the fix; until then, F2 and F3 audit rows are the only trace, and that is the accepted cost of the split |

## Testing

Run against the branch with `PYTHONPATH=<worktree>`, diffed against untouched `develop`, and
through `scripts/testing/run_without_credentials.sh` — this bench has Mollie test credentials and
CI has none, so a green local run of anything touching the gateway proves nothing about CI.

Fakes must be built from **real** API payloads: a `mollie.api.objects.payment.Payment` constructed
over captured JSON (it is a `dict` subclass — a `SimpleNamespace` exercises branches production
never takes), including a `metadata: null` case.

- recurring + paid → one Donation, correct donor/amount/date, `recurring_origin_donation` set,
  Journal Entry created
- redelivery → still one Donation
- redelivery after a JE failure → resumes to a Journal Entry, does not report success first
- `failed` charge → no Donation, audit row present
- charge whose subscription has no metadata (`metadata: null`) → resolved via
  `mollie_subscription_id`, no crash
- unknown subscription → error, audit row
- origin resolution never returns a charge Donation, even when several share a subscription id
- portal: a subscription with three charges shows **one** recurring row
- PDA `total_donated` after two charges equals both, not one, and not double either
- subscription payload contains `get_webhook_url()` and specifically not
  `get_subscription_webhook_url()`
- non-Active PDA → Donation inserts without the link rather than throwing
- charge insert sends the payment confirmation and not the donation confirmation

Each assertion mutation-proven: change the production line it targets and watch it go red.

## Filed separately, not fixed here

- `anbi_operations.get_anbi_statistics` and the `donation_summary` report filter `docstatus = 1`
  on a doctype that is not submittable. On veg11, 57 of 60 donations are `docstatus 0`. veg11 is a
  test instance, so production incidence is unknown from this bench.
- `manage_donations.get_recurring_donations` mutates the list it is iterating (`:117-123`) and
  calls `get_mollie_subscription_info` twice per row.
- `_update_donor_record`'s donor history is capped at `max_entries=30`; a monthly donor loses
  history after 2.5 years.
- The webhook rate limiter allows 20/minute/IP and 5/minute/webhook-id
  (`webhook_rate_limiter.py:54-56`); Mollie batches subscription charges into a tight window, so a
  large recurring cohort could self-throttle.
- `handle_refund_webhook` / `handle_chargeback_webhook` exist but nothing appears to hand Mollie
  those URLs; refunds are discovered only by polling inside the payment webhook.
