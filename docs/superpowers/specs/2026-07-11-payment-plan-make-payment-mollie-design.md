# Payment Plan "Make Payment" — Mollie online payment (A3, Phase 1)

**Date:** 2026-07-11
**Audit item:** A3 (2026-07-10 TODO / unfinished-feature audit)
**Status:** Design — awaiting review

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
- Paying the **next due installment** (earliest `Pending` installment by due
  date). The pay page is structured so a "choose installment" selector can be
  added later without rework.
- A member-facing pay page that renders available methods from
  `PaymentHook.get_available_methods()` (Phase 1 shows only Mollie, so Pay.nl
  drops in later with no page rewrite).

**Out of scope (explicitly deferred):**
- **Pay.nl / ING Checkout (Phase 2).** Pay.nl is a *separate* integration
  (`verenigingen_payments/ing_checkout/`) not wired into the shared
  `PaymentHook`. It gets its own spec/PR and reuses this same pay page + button.
- SEPA / bank transfer / cash methods for payment plans.
- Paying arbitrary / multiple installments in one transaction.
- Changing `PaymentPlan.process_payment()` behaviour (reused as-is).

## Existing building blocks (reused)

- `PaymentHook.get_available_methods()` — returns the method choices
  (`verenigingen_payments/hooks/payment_hook.py`). Reference-agnostic.
- `MollieGateway.process_payment(ref_doc, form_data)` — reads
  `ref_doc.amount` / `.currency` / `.doctype` / `.name`, sets
  `ref_doc.db_set("payment_id", …)`, and writes generic
  `metadata: {reference_doctype, reference_docname}` into the Mollie payment,
  returning a redirect URL. Reused **unchanged**.
- Mollie webhook entry `verenigingen_payments/mollie/api/webhooks.py`
  → `unified_payment_api.handle_payment_webhook()` → the unified webhook
  service. Currently **Donation-only**; a reference-type dispatch is added at
  the top (Donation flow untouched via fall-through).
- `PaymentPlan.process_payment(...)` — reused as-is to finalize the installment.

## Architecture / flow

1. **Button → pay page.** `Make Payment` on an Active plan links to a new
   portal page `/payment_plan_pay?plan=<name>`. The page loads the plan, resolves
   the **next due installment**, and shows its number + amount + the available
   methods (Phase 1: Mollie only).
2. **Initiate.** On confirm, a whitelisted endpoint
   `initiate_installment_payment(plan, installment_number, method)`:
   - validates the plan belongs to the current member and the installment is
     `Pending`,
   - creates a **Payment Plan Payment** intent record (see below) for that
     installment with `amount` = installment amount,
   - calls `PaymentHook.initiate_payment(method="mollie", amount, reference_doctype="Payment Plan Payment", reference_name=<intent>, payer_info=…, redirect_urls=…)`,
   - returns the Mollie redirect URL. The page redirects the member to Mollie.
3. **Pay.** Member completes payment on Mollie's hosted checkout.
4. **Confirm (webhook, source of truth).** Mollie calls the webhook. A new
   dispatch reads the payment's `metadata.reference_doctype`; when it is
   `Payment Plan Payment`, it routes to a new handler that, on Mollie status
   `paid`:
   - loads the intent by `payment_id`,
   - guards against double-processing (intent already `Paid`),
   - calls `plan.process_payment(intent.installment_number, intent.amount,
     payment_reference=payment_id)`,
   - marks the intent `Paid`.
   Non-`Payment Plan Payment` metadata falls through to the existing Donation
   flow unchanged.
5. **Return (UX only).** Mollie redirects the member back to `/payment_plans`;
   the list reflects the updated installment once the webhook has processed
   (same eventual-consistency model the donate flow already uses).

## New: "Payment Plan Payment" intent doctype

One record per payment attempt. It is the reference doc handed to the
gateway, giving a clean `.amount` (installment amount, not the plan total) and a
`payment_id` field the gateway can write to — so `MollieGateway` is reused
unchanged — plus an auditable trail of every attempt.

Fields:
- `payment_plan` — Link → Payment Plan (required)
- `installment_number` — Int (required)
- `amount` — Currency (required; the installment amount at attempt time)
- `currency` — Data (default "EUR")
- `member` — Link → Member (for permission scoping)
- `payment_id` — Data (Mollie payment id; set by the gateway)
- `status` — Select: `Pending` (default) / `Paid` / `Failed` / `Expired`
- `gateway` — Data (e.g. "Mollie"; forward-looking for Phase 2)

Naming: autoname hash. Submittable: no (status field carries state).

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
  `/payment_plan_pay?plan=<planId>` instead of the "coming soon" alert.
- `unified_payment_api.handle_payment_webhook` (or the unified service entry) —
  add the `metadata.reference_doctype` dispatch, Donation flow as fall-through.

## Security & permissions

- Member-facing endpoint verifies the plan's `member` maps to the current user
  (reuse `get_current_user_member_name`); rejects otherwise. It only ever
  operates on the caller's own plan.
- The installment must be `Pending` before initiation (prevents paying an
  already-paid / non-existent installment).
- `process_payment()` is called **only** from the webhook after Mollie confirms
  `paid` — never from a member-triggered path — so a member cannot mark an
  installment paid without money moving.
- Amount is taken from the stored installment, not from client input.
- Intent writes in guest/webhook context use `ignore_permissions` with a
  documented `# Security:` justification (scoped to this app's own intent
  records, matched by Mollie `payment_id`).

## Error handling / edge cases

- Plan not Active, or no `Pending` installment → pay page shows a friendly "no
  payment due" message, no button to initiate.
- Mollie unavailable / initiation fails → endpoint returns an OperationResult
  failure; page shows an error, no intent left in a misleading state (intent
  marked `Failed`).
- Webhook for an intent already `Paid` → no-op (idempotent), mirroring the
  donation idempotency guard.
- Partial payment: `process_payment()` already handles `payment_amount <
  installment.amount`; Phase 1 always pays the full installment amount, so this
  path is not exercised but is not broken.
- Webhook `failed` / `expired` status → mark intent `Failed` / `Expired`;
  installment stays `Pending` so the member can retry.

## Testing strategy (real-DB, no mocks of business logic)

- **Intent doctype**: create/validate; status transitions.
- **initiate_installment_payment**:
  - happy path creates a `Pending` intent for the next due installment with the
    correct amount and returns a redirect (Mollie client stubbed at the HTTP
    boundary only, per existing Mollie test patterns);
  - rejects a plan not owned by the caller;
  - rejects when the installment is not `Pending`.
- **Webhook dispatch → confirmation** (the core new behaviour):
  - a `paid` webhook for a `Payment Plan Payment` intent marks the intent `Paid`
    **and** the installment `Paid` via `process_payment()` (assert the real
    installment row + Payment Entry side effects that `process_payment` produces);
  - a `paid` webhook whose metadata is a Donation still routes to the Donation
    flow (dispatch does not regress donations);
  - a second delivery of the same `paid` webhook is a no-op (idempotent).
- **Button**: `payment_plans.html` `showPaymentForm` navigates to the pay page
  (JS inline-syntax check + assertion the alert is gone).

## Deliverable / PR

One dedicated PR off `develop` (`feat/payment-plan-make-payment-mollie-a3`),
independent of the A5/A1/A4 PRs. Phase 2 (Pay.nl) is a separate spec + PR.
