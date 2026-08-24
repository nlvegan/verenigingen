# Handoff — 2026-08-16: the charge that was never announced

Session goal was "continue with the next task, probably the blocker". The blocker was #345,
and it turned out to be a design question first and a code change second. What shipped is
part A of that design: nineteen commits, nine TDD tasks, each implemented by a fresh
subagent and gated by a review.

## State

| | | |
|---|---|---|
| Branch | `fix/recurring-donation-charge-booking` @ `f3336933` | 19 commits over `origin/fix/donation-subscription-activation` |
| Base | PR #346 (`fix/donation-subscription-activation`) | **unmerged** — this stacks on it |
| Design spec | `docs/superpowers/specs/2026-08-15-recurring-donation-charges-design.md` | committed |
| Plan | `docs/superpowers/plans/2026-08-15-recurring-donation-charge-booking.md` | committed |
| Diff | 23 files, +5908 / −118 | ~100 new tests |
| Final review | skeptical, whole-branch, opus | APPROVE after one fix wave |

Both git trees were clean after every run; no fixture exports leaked into the live tree.

## What was broken

Mollie charges a recurring donor every period and POSTs the subscription's `webhookUrl`
with a **new** payment id. Two independent faults meant none of that was ever booked:

1. The subscriptions this app creates carried **no `webhookUrl`**, so Mollie announced
   nothing. Every `created_from: direct_subscription` subscription in the test account has
   `webhookUrl: None` — measured, twice, by different agents.
2. Even a delivered charge could not be matched: the handler resolved donations by
   `Donation.payment_id`, which holds the **first** payment's id. The lookup returned
   nothing, the handler returned an error, the API layer mapped it to HTTP 500, and Mollie
   retried ten times over 26 hours and gave up.

Net: money at Mollie, nothing in the ledger, no record, no donor history.

## What shipped

A charge now becomes **its own Donation**, carrying `payment_id = <charge id>` and a new
`recurring_origin_donation` link back to the donation the donor actually made. Once that
row exists the *existing* pipeline books it — Bank Transaction, Journal Entry, payment
history, donor history, refunds, chargebacks — with no changes. That is the whole point of
the data model, and I did not see it until the review forced it.

Nine tasks: shape-tolerant payment readers · the origin-link field and email guard ·
uniqueness on `Donation.payment_id` · repairing `DonationLookup` · the charge service ·
webhook wiring · a half-booking no longer reports success · `webhookUrl` on new
subscriptions · the donor portal.

## The corrections that mattered

Six of my own claims were wrong. Each was caught by something other than me re-reading.

**My plan's uniqueness patch would never have run.** It created the index itself; a fresh
install calls `set_all_patches_as_completed()` without running patches, and CI does
`reinstall` + `install-app` with no `migrate`. The constraint would have existed on this
bench and nowhere else, while the concurrency guard that depends on it had nothing behind
it. Found with a **control**, not by reading: the repo's existing
`idx_mollie_payment_ref_unique` is absent on both sites, while `Volunteer.member`'s
JSON-flag-owned index is present on both. The approved spec had said "the JSON flag plus a
`pre_model_sync` patch" all along; the plan drifted from it.

**My plan's concurrency guard was dead code.** It caught a lost insert race with
`frappe.db.is_duplicate_entry(e)` — but `Document.insert()` never lets the driver's
`IntegrityError` escape. Frappe re-raises `frappe.UniqueValidationError(doctype, name,
original)`, whose `args[0]` is the doctype string, so that check is `False` for anything
`insert()` can raise. Found by hitting a real 1062.

**Two of my three justifications for the data model were dead code.** `anbi_operations` and
the `donation_summary` report both filter `docstatus = 1` on a doctype with no
`is_submittable`. I read the `SUM` and stopped before the `WHERE`. Only the Periodic
Donation Agreement argument survived — and then only because the service now calls
`link_donation` itself. `link_donation` had **no** production callers, so setting
`Donation.periodic_donation_agreement` alone would never have moved `total_donated`, and
Donation-per-charge would have bought nothing over a payment child row.

**One instruction I gave was untestable as written.** I asked for an assertion that
`@frappe.whitelist()` stays outermost. The implementer wrote it, mutation-tested it, and
found swapping the decorators leaves everything green — see the CLAUDE.md correction below.

**Another rested on a false premise.** I directed a test built on `expectErrorLog`. It only
*whitelists*: it appends to the set `tearDown` ignores, gated behind an env var that is off
by default. It asserts nothing.

**A finding I overruled was itself wrong in the other direction.** A reviewer reported that
the agreement link would fail because the webhook runs as Guest. Its grep covered
`mollie/api/` and the wrapper but not `webhook_security.py:93`, where `frappe.set_user`
lives; and the webhook user holds `Accounts User`, which the agreement grants write to.
Refuted on both legs — but the narrower residual is real and now documented on the method:
the link works because that user happens to hold that role, and nothing guarantees it.

## Findings that outlive this branch

**The CLAUDE.md decorator-order rule is narrower than it says.** "`@frappe.whitelist()` MUST
be OUTERMOST — Frappe checks by object identity" is compensated for by
`utils/security/frappe_whitelist_adapter.py:110-137`: `register_wrapper_in_whitelist()`
adds the *wrapper* to `frappe.whitelisted` whenever the inner function was already
whitelisted, so the identity check passes either way. **Scope:** verified only for this
project's `api_security_framework`-based `*_api` decorators on **non-guest** endpoints.
`preserve_common_attributes` copies `allow_guest` cosmetically and never touches
`frappe.guest_methods` — so a wrong-order `allow_guest` endpoint still breaks silently for
Guest callers while working for authenticated ones, which is harder to diagnose than a 403.
Keep the rule as the safe default; correct its absoluteness.

**`expectErrorLog` does not assert.** `error_log_guard.py:96` — it only suppresses. Query
Error Log directly. Related: this repo calls `frappe.log_error(message, category)` against
Frappe's `log_error(title, message)`, and the swap heuristic (`"\n" in title`) puts a
single-line message in `method` and the **category in `error`**. Match both fields.

**`run_without_credentials.sh` passes no `PYTHONPATH`,** so it runs the *installed* tree.
A branch validated with it is validating `develop` unless you export `PYTHONPATH` yourself.
Caught only because a test count differed — `Ran 6` where the branch had 7.

**When a diff edits a shared entry point, derive the regression set by grep** —
`grep -rn "<entry point>(" verenigingen/` — not from the modules the branch happens to have
added. Task 6 broke six pre-existing tests in two `develop` modules precisely by scoping it
the other way; its develop control was *vacuous* because all three modules it ran were new
on the branch, and "no baseline exists for the modules I chose" got read as "no attribution
gap exists". The same rule then caught a third file in each of Tasks 8 and 9.

**Two different functions are named `mollie_subscription_webhook`.** The one in
`mollie/api/webhooks.py` **is** guest-reachable; the one in `payment_gateways.py` — the
endpoint #343 argued is unreachable — is not. A test matching on the bare name would have
resolved the wrong one, passed, and appeared to disprove #343. Resolve the full dotted path
and compare identity.

**Mollie rejects a `status` query parameter** on `GET /v2/customers/{id}/subscriptions`
(`Non-existent query parameter "status"`). Filtering canceled subscriptions has to be
client-side.

**`_handle_partial_processing` is dead for donation webhooks.** `_check_payment_entry_state`
queries the legacy `Payment Entry` doctype that the Bank-Transaction+Journal-Entry
architecture never creates, so `is_fully_processed()` is always `False` and routing always
takes `_handle_new_payment_processing`.

## Defects found in passing, not fixed here — worth issues

- **`update_recurring_donation` had no "already booked" guard.** Fixed for charges in this
  branch, but the same endpoint still lets a donor rewrite the `amount` of a **settled
  origin** donation that carries a submitted Journal Entry. The donor is emailed each
  document name by `send_payment_confirmation_email`, so this is not a guessing attack.
- **`v2_1/add_mollie_payment_entry_unique_index.py` is dead on every deployment** — Payment
  Entry has no such constraint anywhere. File it with the nuance: absence is consistent
  with the fresh-install mechanism *and* with its `try/except` printing-and-continuing
  where it did run.
- **`api/periodic_donation_operations.py:148`** calls the decorated `link_donation` from
  inside its own `@critical_api`, burning two rate-limit buckets per user action; now that
  `add_donation_link` exists, one line fixes it.
- **`anbi_operations.get_anbi_statistics` and the `donation_summary` report** aggregate
  nothing, because they filter `docstatus = 1` on a non-submittable doctype.
- **`get_recurring_donations` mutates the list it iterates** (`manage_donations.py:127`).
- **`is_recurring_donation_active` returns `False` from a bare `except`**, so a Mollie
  outage reads to a donor as "already cancelled".
- **Two permanent-reason strings agree only by spelling** across a module boundary, and
  `mollie_bad_request` is written in two files and read by nothing that runs — the #341
  shape. Parked: the strings match today and the reachable half is tested.
- **`_repair_agreement_link` fires per redelivery**, so an inactive-agreement audit row is
  now per-delivery rather than per-charge. Verified no re-link and no data damage; log
  noise only.

## What is deliberately not done

**Part B: recovery.** A scheduled sweep that lists each active donation subscription's
payments and books any that have no Donation, plus delegating the recurring case from
`PaymentTypeRouter`'s DONATION branch so the existing `mollie_bulk_payment_discovery` admin
page — which today counts every donation as `skipped` — becomes the backfill instead of the
sweep duplicating it. Part A repairs nothing retroactively and does not need to: **there are
no donation subscriptions live at Mollie today** (confirmed by Foppe), so every subscription
A's fix applies to is one it creates itself, with a `webhookUrl` from the start.

The accepted cost of the split: between A and B, a booking that fails past Mollie's
26-hour ladder is not recovered automatically. Two residuals sit in that gap — a charge
abandoned after the ladder, and an agreement link that fails on the *final* delivery
(the in-branch repair only covers "link failed **and** something later in the same delivery
also failed"; a rate-limited link on its own still returns 200 and is never retried).

## Before merging

- **#346 must merge first**; this branch is stacked on it. #346 in turn must not merge
  without this one — before it, a recurring donor was under-charged once; after it, charged
  every period into an unbooked void.
- CI is unproven for this branch. Every module was run alone on `test_site_1`; shard-scale
  co-tenancy is CI's to prove.
- The uniqueness patch will do real work on veg11: one duplicate pair
  (`test_donation_payment_123`) gets one side cleared, with a Comment recording the value.
  Both rows survive — the resolver clears a field and never deletes a row.
- `"SEPA Direct Debit"` is not shipped as an app fixture. It exists on veg11 and
  `test_site_1`, so nothing breaks today, but a freshly built site will silently label every
  charge with the origin's iDEAL/card mode plus a warning audit row.

## The thing I would tell the next session

The per-task reviews were good; the **whole-branch** review found three things nine
task-scoped reviews structurally could not — a design requirement lost between the design
and the plan so no task owned it, a portal endpoint that became reachable only because
another task created the rows that reach it, and a test-fixture literal that would collide
with a row leaked by a different module. Budget for that pass; it is not a formality.

And the switch Foppe asked for mid-run — using the dedicated skeptical reviewer, which
adjudicates *test meaningfulness* rather than just correctness — paid for itself on its
first outing, catching that a test pinned a call-site spelling instead of the property it
claimed. Several tests on this branch would have shipped green and meaningless without it.
