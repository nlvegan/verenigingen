# Mollie Amendment Sync: PATCH Amount + Drift Repair

**Date:** 2026-06-13
**Status:** Approved
**Requested by:** Foppe

## Problem

Member dues changes never reach Mollie. The amendment sync
(`mollie_subscription_sync_service.py`) gates on `member.mollie_mandate_id`
(line 77), a field that was never populated by any creation flow until
2026-06-12, so every applied Contribution Amendment Request silently
returned "skipped". The event handler (`amendment_events.py`) only updates
`mollie_sync_status` on success, so the 3 stuck amendments on veg11 sit at
"In Progress" forever with no admin signal.

Additionally, when the sync *did* work it replaced the subscription
(create new + cancel old) even for amount-only changes, and live
subscriptions carry drifted metadata: Foppe's real subscription points its
webhook at a dead dev host (`dev.veganisme.net`, pre-refactor module path,
`?env=test`) and the in-code description formats disagree with what live
subscriptions actually carry.

## Decision

For amount-only amendments, PATCH the existing subscription instead of
replacing it, and opportunistically repair drifted `description` /
`webhookUrl` in the same PATCH. Keep replacement only for interval-changing
amendments.

## Canonical values

- **Description:** template from
  `Verenigingen Payments Settings.mollie_subscription_description_template`
  (Foppe: "the description is saved on the verpaysett field"), default
  `"Contribution payment for member MEMBER_ID"`, with `MEMBER_ID` →
  `member.member_id` and `MEMBER_NAME` → `member.full_name`. This matches
  the format live subscriptions were created with (verified against
  Foppe's real subscription: "Contribution payment for member 1026").
- **Webhook URL:** `Mollie Settings.get_subscription_webhook_url()` →
  `/api/method/verenigingen.verenigingen_payments.utils.payment_gateways.mollie_subscription_webhook`
  (the real handler with signature verification; the `webhooks.py` twin is
  a back-compat shim).

## Design

### 1. Shared description helper

New `get_member_subscription_description(member)` in the Mollie services
layer (`verenigingen_payments/mollie/services/`): reads the template field,
substitutes placeholders. Consumers:

- the new PATCH path (drift comparison),
- `MollieGateway` subscription creation (`payment_gateways.py` ~line 563,
  currently hardcodes `"Membership dues for {first} {last}"`),
- sync replacement path (`_create_replacement_subscription`, currently
  hardcodes `"Membership dues - {first} {last}"`).

Without converting the creation paths, they keep regenerating drift.

### 2. Sync service: PATCH path

In `sync_subscription_for_amendment`:

- **Gate fix:** require only `mollie_customer_id` + `mollie_subscription_id`.
  Drop the `mollie_mandate_id` requirement entirely (the cause of the
  silent skips).
- Fetch the live subscription object once (SDK, gives `amount`,
  `interval`, `description`, `webhook_url`, `mandate_id`).
- Compute `(new_amount, new_interval)` via existing
  `_get_subscription_parameters`.
- **If `new_interval` equals the live subscription's interval** (Mollie
  format string comparison, e.g. `"3 months"`): PATCH path.
  - Payload: `amount` (always, formatted via `format_mollie_amount`);
    `description` only if live value differs from canonical;
    `webhookUrl` only if live value differs from canonical.
  - One `customer_obj.subscriptions.update(subscription_id, payload)` call.
  - Verify the returned amount equals the requested amount; on mismatch
    return `status="warning"` with `requires_admin_review=True` (mirrors
    the replacement path's verification semantics).
  - Log the change (worker log) including which drifted fields were
    repaired; failures surface via the handler's Failed status + admin
    notification.
  - No mandate validation (PATCH does not touch authorization; a broken
    mandate breaks charging regardless).
  - `member.mollie_subscription_id` is unchanged by design; update
    `subscription_status` / `next_payment_date` on the Member from the
    PATCH response.
- **If the interval changed:** existing replacement path, with two fixes:
  - old mandate sourced from the live subscription's `mandate_id`
    (member field as fallback) — same principle as the 2026-06-12
    bank-account-update fix;
  - mandate validity check stays, but only on this path.

### 3. Handler status lifecycle

`amendment_events.py` + `Contribution Amendment Request.mollie_sync_status`
Select options:

- `skipped` result → status **"Skipped"** (new option).
- `error` result → status **"Failed"** + administrator notification
  (today: only unhandled exceptions mark Failed; errors without
  `requires_admin_review` vanish into the logger).
- `warning` → status "Completed" is NOT set; keep current behavior
  (admin notification when `requires_admin_review`), but set status
  **"Needs Review"** (new option) so it is visible.
- `success` → "Completed" (unchanged).

DocType JSON change + migrate required for the new Select options.

### 4. One-time repair patch

`v2_2` patch: for each member having stuck amendments (Applied +
`mollie_sync_completed = 0`), re-enqueue the sync for the **latest**
applied amendment only; mark older stuck ones "Skipped". On veg11 this is
3 amendments / 2 members; Foppe's subscription ends at €26.50 with
repaired description + webhook.

## Out of scope (flagged)

- Bulk webhook repair for legacy subscriptions that will never see an
  amount change: use the existing admin tool
  (`bulk_update_subscription_webhooks`, subscription audit page).
- PATCHing `startDate` (postponing next charge) — possible per Mollie
  docs, no requirement yet.
- Donation-subscription amount updates (separate staff endpoint).

## Error handling

- Mollie API failure during PATCH → `status="error"`,
  `requires_admin_review=True` → handler marks Failed + notifies. No
  partial state: a failed PATCH changes nothing at Mollie.
- Replacement path keeps its existing create-then-cancel rollback logic.

## Testing

Extend `test_mollie_subscription_consolidation.py` fakes:
`_FakeSubscriptions.update()` recording payloads; `_FakeSubscription`
carries `description` / `webhook_url`.

Unit tests:
1. Amount-only amendment → PATCH (no create, no cancel), payload has only
   `amount` when description/webhook match canonical.
2. Drifted description and/or webhook → included in PATCH payload;
   matching values omitted.
3. Interval-changing amendment → replacement path (create + cancel), no
   PATCH.
4. Member without `mollie_mandate_id` → PATCH path proceeds (gate
   removed).
5. Member without subscription/customer id → skipped, and handler sets
   status "Skipped".
6. PATCH amount verification mismatch → warning + "Needs Review".
7. Handler: error result → "Failed" + notification.

Existing replacement-path tests stay green. Optional live verification on
test_site_1 with the sandbox key (PATCH a real test subscription).
