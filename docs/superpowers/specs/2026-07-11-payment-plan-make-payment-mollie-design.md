# Payment Plan "Make Payment" — Mollie online payment (A3, Phase 1)

**Date:** 2026-07-11
**Audit item:** A3 (2026-07-10 TODO / unfinished-feature audit)
**Status:** Design — revised after skeptical design review (2026-07-11)

> **Revision note:** A skeptical design review found the *initiation* half sound
> but the original *confirmation* half specified against a webhook shape that
> does not exist. Fixed below: (1) the webhook dispatch moves into
> `process_payment_webhook` **before** STEP-0 payment classification, not into
> `handle_payment_webhook` (which has no metadata); (2) a non-"donation"
> `description_override` is passed so the keyword classifier cannot hijack the
> payment; (3) the Mollie return page (`payment-success`) is Donation-whitelisted,
> so "Payment Plan Payment" is added to it and the intent carries the fields it
> reads; (4) idempotent, non-500 handling is built into the new handler;
> (5) **Overdue** installments are payable (the original "Pending only" scope
> locked out exactly the members who missed a payment). There are **three**
> Donation-coupled chokepoints (classifier, donation lookup, return-page
> whitelist), all addressed here.

## Problem

The **Make Payment** button on the member self-service payment-plans portal
(`templates/pages/payment_plans.html`) is a stub: `showPaymentForm()` pops
*"Payment recording feature coming soon. Please contact support to record
payments."* Members cannot pay a payment-plan installment online.

The controller method `PaymentPlan.process_payment(installment_number,
payment_amount, payment_reference, payment_date)` already exists and works: it
marks the installment Paid (handling partial payments), creates an ERPNext
Payment Entry, and sends a confirmation email. What is missing is a **member-
facing way to actually take the payment** and a **path that calls
`process_payment()` only after money is confirmed received** — a member must not
self-certify "paid".

## Goal

Let a member pay the **next due installment** of an Active payment plan **online
via Mollie**, with the installment marked Paid automatically on confirmed
payment (Mollie webhook), never by member self-assertion.

## Scope

**In scope (Phase 1):**
- Mollie online payment only ("Online Payment": iDEAL / card / etc.).
- Paying the **next payable installment** = earliest installment that is
  `Pending` **or** `Overdue`, by due date. (A missed installment is flipped
  `Pending`→`Overdue` by `process_overdue_installments`; excluding `Overdue`
  would lock out precisely the members who need to pay.) The pay page is
  structured so a "choose installment" selector can be added later without
  rework.
- A member-facing pay page that renders available methods from
  `PaymentHook.get_available_methods()` (Phase 1 shows only Mollie, so Pay.nl
  drops in later with no page rewrite).

**Out of scope (explicitly deferred):**
- **Pay.nl / ING Checkout (Phase 2).** Pay.nl is a *separate* integration
  (`verenigingen_payments/ing_checkout/`) not wired into the shared
  `PaymentHook`/`PaymentGatewayFactory`, with a different return path
  (`orderId` + `ING Checkout Transaction`). The pay page's *method listing*
  reuses cleanly, but the *initiation + webhook/return* wiring is **not** shared
  and is genuine new work in Phase 2 — do not assume zero rework.
- SEPA / bank transfer / cash methods for payment plans.
- Paying arbitrary / multiple installments in one transaction.
- Changing `PaymentPlan.process_payment()` behaviour (reused as-is).

## Existing building blocks (reused)

- `PaymentHook.get_available_methods()` — returns the method choices
  (`verenigingen_payments/hooks/payment_hook.py`). Reference-agnostic.
- `PaymentHook.initiate_payment(...)` — needs a **small change**: it currently
  builds `form_data` from a fixed key set (`payment_hook.py:277-289`) and has no
  `description` parameter, so it silently drops any description. Add an optional
  `description: str | None = None` param and forward it as
  `form_data["description_override"]` (which `MollieGateway` already honors,
  `payment_gateways.py:171`). Backward compatible (default `None`).
- `MollieGateway.process_payment(ref_doc, form_data)` — reads
  `ref_doc.amount` / `.currency` / `.doctype` / `.name`, sets
  `ref_doc.db_set("payment_id", …)`, and writes generic
  `metadata: {reference_doctype, reference_docname}` into the Mollie payment,
  returning a redirect URL. Reused **unchanged**.
- Mollie webhook: entry `verenigingen_payments/mollie/api/webhooks.py`
  → `unified_payment_api.handle_payment_webhook()` (has only the payment **id**,
  no metadata) → `UnifiedWebhookWrapperService.process_payment_webhook`
  (`webhook_wrapper_service_unified.py:346`), whose **STEP 0** fetches the
  payment and classifies it. This path is **Donation-coupled at three points**
  (all must be handled, see below).
- `PaymentPlan.process_payment(...)` — reused as-is to finalize the installment.
  Its `self.save()` re-runs `validate()`→`generate_installments()`, but the
  regenerate guard (`if self.installments: return`, `payment_plan.py:114`) makes
  marking-then-saving safe. It **throws** if the installment is already `Paid`
  (`:278`) — the new handler must guard before calling it (see idempotency).

### Three Donation-coupled chokepoints (all addressed)

1. **Payment classifier** — `process_payment_webhook` STEP 0 runs
   `PaymentTypeRouter.classify_payment` first. The Mollie payment's default
   description is `f"Donation {ref_doc.name}"` (`payment_gateways.py:171`), and
   `DescriptionKeywordClassification` matches the `"donation"` keyword → the
   intent's payment is misclassified as **DONATION**, routed to donation lookup,
   not found → HTTP 500 → Mollie retries forever. **Fix:** dispatch on
   `metadata.reference_doctype` **before** STEP 0, *and* pass a non-"donation"
   `description_override` at initiation as defence-in-depth.
2. **Donation lookup** — the donation branch calls
   `find_donation_for_payment_by_id` which queries only the Donation doctype.
   Bypassed by the pre-classification dispatch.
3. **Return page** — `MollieGateway` ignores `form_data["redirect_url"]` and
   computes `settings.get_redirect_url(doctype, name)` →
   `/payment-success?doctype=Payment Plan Payment&docname=…`, but
   `payment_success.py` whitelists only `{Donation, Member Application, Sales
   Invoice}` (`:16,32-36`) → "Invalid document type". **Fix:** add
   "Payment Plan Payment" to `ALLOWED_PAYMENT_DOCTYPES` and give the intent the
   fields that page reads (`payment_id`, `paid`, `amount`).

## Architecture / flow

1. **Button → pay page.** `Make Payment` links to a new portal page
   `/payment_plan_pay?plan=<name>`. The button is shown when the plan is Active
   **and has a payable (`Pending`/`Overdue`) installment** — not gated on
   `next_payment_date` (which reflects only `Pending`, `payment_plan.py:186-188`,
   and would hide the button for an overdue member). The page loads the plan,
   resolves the **next payable installment**, and shows its number + amount +
   the available methods (Phase 1: Mollie only).
2. **Initiate.** On confirm, a whitelisted endpoint
   `initiate_installment_payment(plan, installment_number, method)`:
   - validates the plan belongs to the current member and the installment is
     `Pending` or `Overdue` (not `Paid`),
   - creates a **Payment Plan Payment** intent record (see below) for that
     installment with `amount` = installment amount (server-derived),
   - calls `PaymentHook.initiate_payment(method="mollie", amount, reference_doctype="Payment Plan Payment", reference_name=<intent>, payer_info=…, description="Payment plan {plan} installment {n}")`.
     This threads through the new `description` param → `form_data["description_override"]`
     → the Mollie payment description. It (a) shows the member a correct
     description on Mollie's checkout instead of "Donation …", and (b) is
     defence-in-depth against the classifier's `"donation"` keyword (the
     pre-classification dispatch below is the primary guarantee),
   - returns the Mollie redirect URL. The page redirects the member to Mollie.
3. **Pay.** Member completes payment on Mollie's hosted checkout.
4. **Confirm (webhook, source of truth).** Mollie calls the webhook. A new
   dispatch is inserted at the **top of `process_payment_webhook`, before STEP-0
   classification** (`webhook_wrapper_service_unified.py:360`): it fetches the
   payment, reads `metadata.reference_doctype`, and when it is
   `Payment Plan Payment` routes to a new handler `handle_payment_plan_payment`
   that:
   - loads the intent by `payment_id`,
   - takes a **`FOR UPDATE` row lock on the intent** for the whole guard →
     finalize → mark-paid sequence, so concurrent duplicate deliveries serialize,
   - **idempotency guard:** if the intent is already `Paid`, return a success
     (HTTP 200) no-op — never let it reach `process_payment` (which throws on an
     already-Paid installment → would become a 500 retry loop),
   - on Mollie status `paid`: call `plan.process_payment(intent.installment_number,
     intent.amount, payment_reference=payment_id)` **first**, and only mark the
     intent `Paid` **after it returns successfully**. Ordering matters: if the
     intent were flipped to `Paid` before `process_payment`'s `self.save()`
     (`payment_plan.py:294`) threw, the installment would never finalize yet every
     retry would short-circuit at the `Paid` guard → payment permanently lost.
     (`process_payment` swallows Payment-Entry/email errors at `:332,366`, so the
     realistic throw point is the `save()`.)
   - on `failed`/`expired`: mark the intent `Failed`/`Expired` (installment
     stays payable so the member can retry).
   Non-`Payment Plan Payment` metadata falls through to the existing Donation
   classification/flow unchanged.
5. **Return (UX).** Mollie redirects to the gateway-computed
   `/payment-success?doctype=Payment Plan Payment&docname=<intent>`.
   "Payment Plan Payment" is added to `payment_success.py`'s
   `ALLOWED_PAYMENT_DOCTYPES`, and the intent exposes the fields that page reads
   (`payment_id`, `paid`, `amount`). The displayed status reflects the intent;
   the installment itself is finalized by the webhook (eventual consistency,
   same as the donate flow).

## New: "Payment Plan Payment" intent doctype

One record per payment attempt. It is the reference doc handed to the
gateway, giving a clean `.amount` (installment amount, not the plan total) and a
`payment_id` field the gateway can write to — so `MollieGateway` is reused
unchanged — plus an auditable trail of every attempt.

Fields:
- `payment_plan` — Link → Payment Plan (required)
- `installment_number` — Int (required)
- `amount` — Currency (required; the installment amount at attempt time). Also
  the field `MollieGateway` reads and the `payment-success` page displays.
- `currency` — Data (default "EUR"; read by `MollieGateway`)
- `member` — Link → Member (for permission scoping)
- `payment_id` — Data (Mollie payment id; set by the gateway via `db_set`;
  read by the `payment-success` page)
- `paid` — Check (default 0; set 1 when the intent reaches `Paid`; read by the
  `payment-success` page to show success)
- `status` — Select: `Pending` (default) / `Paid` / `Failed` / `Expired`
- `gateway` — Data (e.g. "Mollie"; forward-looking for Phase 2)

Naming: autoname hash. Submittable: no (status field carries state). The doc
must expose `amount`, `payment_id`, `paid` because the reused `payment-success`
page reads them (`payment_success.py:48,314-315`).

Permissions: created/updated by the initiating endpoint and the webhook
(system/guest context) with `ignore_permissions` where required, documented with
a `# Security:` note. Members do not directly write it.

## New / changed components

**New**
- DocType `Payment Plan Payment` (+ controller, minimal).
- `templates/pages/payment_plan_pay.py` / `.html` — member-facing pay page
  (login + member + plan-ownership gated; renders installment + methods; posts
  to the initiate endpoint; redirects to the gateway URL).
- API `api/payment_plan_management.py :: initiate_installment_payment(...)`
  (whitelisted; `@critical_api(FINANCIAL)`; member-ownership + installment-state
  validation).
- Webhook handler: `handle_payment_plan_payment(payment_data)` invoked from the
  reference-type dispatch.

**Changed**
- `templates/pages/payment_plans.html` — `showPaymentForm(planId)` navigates to
  `/payment_plan_pay?plan=<planId>` instead of the "coming soon" alert; button
  visibility widened to Active + has payable installment.
- `mollie/services/webhook_wrapper_service_unified.py::process_payment_webhook`
  — add the `metadata.reference_doctype` dispatch at the top, **before** STEP-0
  classification; Donation flow is the fall-through.
- `templates/pages/payment_success.py` — add `"Payment Plan Payment"` to
  `ALLOWED_PAYMENT_DOCTYPES`.
- `verenigingen_payments/hooks/payment_hook.py::initiate_payment` — add optional
  `description` param, forwarded as `form_data["description_override"]`
  (backward compatible). `MollieGateway` itself is unchanged.

## Security & permissions

- Member-facing endpoint verifies the plan's `member` maps to the current user
  (reuse `get_current_user_member_name`); rejects otherwise. It only ever
  operates on the caller's own plan.
- The installment must be `Pending`/`Overdue` (not `Paid`) before initiation.
- `process_payment()` is called **only** from the webhook after Mollie confirms
  `paid` — never from a member-triggered path — so a member cannot mark an
  installment paid without money moving.
- Amount is taken from the stored installment, not from client input.
- Intent writes in guest/webhook context use `ignore_permissions` with a
  documented `# Security:` justification (scoped to this app's own intent
  records, matched by Mollie `payment_id`).
- **Webhook user permissions:** the webhook runs as the configured
  `webhook_user` (`webhook_security.py:85-93`). `process_payment()` creates and
  **submits** a Payment Entry (`payment_plan.py:329-330`). Confirm the webhook
  user can create/submit Payment Entry; if not, run the finalization via the
  same service-user pattern the donation webhook flow already uses.

## Error handling / edge cases

- Plan not Active, or no `Pending` installment → pay page shows a friendly "no
  payment due" message, no button to initiate.
- Mollie unavailable / initiation fails → endpoint returns an OperationResult
  failure; page shows an error, no intent left in a misleading state (intent
  marked `Failed`).
- Webhook for an intent already `Paid` → HTTP 200 no-op **before** reaching
  `process_payment()` (which throws on an already-Paid installment,
  `payment_plan.py:278` → would otherwise become a 500 → Mollie retry storm).
  The existing `UnifiedIdempotencyManager` is Donation-centric and does not
  track intents, so idempotency rests on the intent's own status transition. Hold
  a `FOR UPDATE` lock on the intent across guard → `process_payment` → mark-`Paid`,
  and set `Paid` **only after** `process_payment` returns (see flow step 4) so a
  mid-finalize failure can't leave a `Paid` intent with an unfinalized
  installment.
- Partial payment: `process_payment()` already handles `payment_amount <
  installment.amount`; Phase 1 always pays the full installment amount, so this
  path is not exercised but is not broken.
- Webhook `failed` / `expired` status → mark intent `Failed` / `Expired`;
  installment stays `Pending` so the member can retry.

## Testing strategy (real-DB, no mocks of business logic)

- **Intent doctype**: create/validate; status transitions.
- **initiate_installment_payment**:
  - happy path creates a `Pending` intent for the next payable installment with
    the correct server-derived amount and returns a redirect (Mollie client
    stubbed at the HTTP boundary only, per existing Mollie test patterns);
  - resolves an **`Overdue`** installment as payable (not just `Pending`);
  - the `description` passed to `initiate_payment` actually threads into the
    payment (assert the Mollie payment description is the installment text, not
    `"Donation …"` — proves the new `payment_hook.py` param works);
  - rejects a plan not owned by the caller;
  - rejects when the installment is `Paid`.
- **Webhook dispatch → confirmation** (the core new behaviour):
  - a `paid` webhook for a `Payment Plan Payment` intent marks the intent `Paid`
    **and** the installment `Paid` via `process_payment()` (assert the real
    installment row + Payment Entry side effects that `process_payment` produces);
  - the dispatch fires **before** classification — a Payment Plan Payment is
    never routed to donation lookup (no 500);
  - a `paid` webhook whose metadata is a Donation still routes to the Donation
    flow (dispatch does not regress donations);
  - a second delivery of the same `paid` webhook returns success and does **not**
    re-run `process_payment` (idempotent, no 500);
  - if `process_payment` raises mid-finalize, the intent is **not** left `Paid`
    (ordering guard — a retry can still finalize the installment);
  - a `failed`/`expired` webhook marks the intent Failed/Expired and leaves the
    installment payable.
- **Return page**: `payment-success` accepts `doctype=Payment Plan Payment`
  (added to `ALLOWED_PAYMENT_DOCTYPES`) and renders from the intent's
  `payment_id`/`paid`/`amount` without "Invalid document type".
- **Button**: `payment_plans.html` `showPaymentForm` navigates to the pay page
  (JS inline-syntax check + assertion the alert is gone).

## Deliverable / PR

One dedicated PR off `develop` (`feat/payment-plan-make-payment-mollie-a3`),
independent of the A5/A1/A4 PRs. Phase 2 (Pay.nl) is a separate spec + PR.
