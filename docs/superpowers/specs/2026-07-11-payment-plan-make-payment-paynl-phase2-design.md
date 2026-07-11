# Payment Plan "Make Payment" — Pay.nl / iDEAL (A3, Phase 2)

**Date:** 2026-07-11
**Audit item:** A3 Phase 2 (2026-07-10 TODO / unfinished-feature audit). Phase 1 (Mollie) = PR #148 (merged).
**Status:** Design — awaiting skeptical review

## Problem / goal

Phase 1 shipped online payment of a payment-plan installment via **Mollie**. This adds **Pay.nl (iDEAL)** as a second option, exposed through the **same** `/payment_plan_pay` page and `Make Payment` button. Pay.nl lives in this app as the **ING Checkout** integration (`verenigingen_payments/ing_checkout/`), which is NOT wired into the shared `PaymentHook`. Per the chosen approach, we **wire ING Checkout into `PaymentHook`** so the pay page stays gateway-neutral and shows whichever gateways are **enabled** (config-driven: Mollie and/or Pay.nl).

Goal: a member can pay the next payable installment via Pay.nl iDEAL; the installment is marked Paid **only** after Pay.nl confirms payment (webhook), reusing Phase 1's finalization semantics exactly.

## Scope

**In scope:**
- Wire ING Checkout iDEAL into `PaymentHook` as a first-class gateway (a new method id, an `INGCheckoutGateway`, factory registration, availability gating, response normalization).
- Reuse the **Phase-1 `Payment Plan Payment` intent doctype** as the Pay.nl reference (gateway="Pay.nl", `payment_id` = Pay.nl order id).
- Extract Phase 1's installment-finalization core into ONE gateway-agnostic function; call it from BOTH the Mollie webhook dispatch and the ING finalizer (DRY).
- Branch ING's transaction finalizer so a `Payment Plan Payment` reference finalizes the installment instead of creating a generic Payment Entry.
- The pay page automatically offers Pay.nl when its gateway is enabled (no page rewrite — it already renders `PaymentHook.get_available_methods()`; Phase 1 filtered to `mollie` only — widen that filter).

**Out of scope:**
- SEPA/bank/cash for payment plans; recurring/subscription payment plans.
- Changing Mollie's Phase-1 behavior (only the finalizer is extracted/shared, behavior identical).
- Reworking ING Checkout's existing Sales-Invoice/Member payment flows.

## Existing building blocks (verified)

- **`ing_checkout/api/payment.py::create_ideal_payment(reference_doctype, reference_name, amount, description, return_url)`** — already reference-agnostic: checks ref-doc existence + permission, builds a Pay.nl order with a structured `reference = "{DOCTYPE_CODE}:{name}"`, creates an **`ING Checkout Transaction`** tracking record, returns `{success, transaction_id (order id), redirect_url}`. `DOCTYPE_CODES` maps only SINV/MEM/PINV (else `reference_doctype[:4].upper()`).
- **`ing_checkout/api/webhook.py`** — `handle_payment` (allow_guest; HMAC/signature verify, idempotency, rate limit) → `_process_payment_webhook` → `_parse_reference` (`DOCTYPE_MAP` SINV/MEM/PINV) → `ING Checkout Transaction.update_from_webhook(payload)`.
- **`ING Checkout Transaction.update_from_webhook`** — maps Pay.nl status → `status`; on transition to `Paid` calls `_create_payment_entry_with_savepoint()` → a service that creates a **generic** Payment Entry for the reference. Fields: `transaction_id`, `reference_doctype`, `reference_name`, `amount`, `status`, `payment_entry`.
- **`PaymentHook`** (`verenigingen_payments/hooks/payment_hook.py`) — `get_available_methods()` (per-gateway availability), `initiate_payment(method, amount, reference_doctype, reference_name, payer_info, ..., description)` → `PaymentGatewayFactory.get_gateway(name).process_payment(ref_doc, form_data)` → `_normalize_gateway_response(method, result)`. The redirect branch keys on `status in ("redirect_required", …)` and emits `data.url` from `result["payment_url"]`.
- **`PaymentGateway` ABC** (`utils/payment_gateways.py`) — abstract `process_payment(donation, form_data)`, `handle_webhook(payload)`, `get_payment_status(payment_id)`; `PaymentGatewayFactory._gateways` dict maps method → class.
- **Phase-1 finalization** — `mollie/services/payment_plan_payment_handler.py::handle_payment_plan_payment` holds the installment-finalization core (FOR-UPDATE lock, idempotency guard on the locked status, double-payment installment guard, `PaymentPlan.process_payment`, mark intent Paid). `PaymentPlan.process_payment` carries `@high_security_api(FINANCIAL)` (webhook user must hold the tier; defaults to Administrator).

## Architecture

### 1. ING Checkout as a `PaymentHook` gateway
- **New method** in `PaymentHook`: id `ing_ideal` (label e.g. "iDEAL (Pay.nl)"), `type=REDIRECT`. Add to `_METHOD_TO_GATEWAY` → gateway name `"ING Checkout"`. `get_available_methods()` gains an ING branch that appends the method **iff** ING Checkout settings are enabled/configured (mirroring the Mollie availability check) — so visibility is config-driven.
- **`INGCheckoutGateway(PaymentGateway)`** in `utils/payment_gateways.py` (or an ING-owned module registered into the factory): `process_payment(ref_doc, form_data)`:
  - reads amount from `form_data["amount"]` (falls back to `ref_doc.amount`), currency EUR, description from `form_data.get("description_override")`;
  - calls the **extracted core** of `create_ideal_payment` (an internal service function, e.g. `ing_checkout/services/transaction_service.py::create_ideal_order(reference_doctype, reference_name, amount, description, return_url)` — refactor `create_ideal_payment` to a thin `@frappe.whitelist()` wrapper over it so the gateway can call the core without the whitelist layer);
  - returns `{"status": "redirect_required", "payment_url": <redirect_url>, "payment_id": <order_id>}` so the existing `_normalize_gateway_response` redirect branch yields `{action: redirect, data:{url}, payment_id}`. No new normalization branch needed.
  - `handle_webhook`/`get_payment_status`: minimal (ING's own webhook route handles confirmation; these can delegate or raise `NotImplementedError` with a comment, matching how other gateways treat unused ABC methods — verify BankTransferGateway's pattern).
- Register `"ING Checkout": INGCheckoutGateway` in `PaymentGatewayFactory._gateways`.

### 2. Shared, gateway-agnostic installment finalizer (DRY)
- Extract the Phase-1 finalization core into `verenigingen_payments/services/payment_plan_finalization.py::finalize_payment_plan_installment(intent_name, payment_reference, mollie_or_gateway_status="paid") -> dict` (module location TBD — a gateway-neutral home, NOT under `mollie/`). It performs: FOR-UPDATE lock on the intent, idempotency guard on the locked status, installment-already-Paid double-payment guard (log + skip), `PaymentPlan.process_payment(...)`, then mark intent Paid — returning `{"status": "success"|"skipped"|"error", ...}`.
- **Refactor Phase 1**: `mollie/services/payment_plan_payment_handler.py::handle_payment_plan_payment` becomes a thin adapter that maps the Mollie payment status to `paid/failed/expired` and calls `finalize_payment_plan_installment`. Phase-1 tests must stay green (behavior identical).

### 3. ING finalization branch + intent reuse
- Add `"Payment Plan Payment": "PPP"` to **`create_ideal_payment`/core `DOCTYPE_CODES`** (payment.py) and `"PPP": "Payment Plan Payment"` to **`_parse_reference` `DOCTYPE_MAP`** (webhook.py). (Fallback `[:4].upper()` would give `PAYM`, colliding-risk and asymmetric — set both explicitly.)
- Branch **`ING Checkout Transaction.update_from_webhook`** (or `_create_payment_entry_with_savepoint`): when `reference_doctype == "Payment Plan Payment"` and status→Paid, call `finalize_payment_plan_installment(reference_name, payment_reference=transaction_id)` **instead of** the generic Payment Entry path. Set the intent `payment_id` = Pay.nl order id at initiation (the gateway/core writes it, mirroring Phase 1).
- The pay-page initiate endpoint (`initiate_installment_payment`) already takes `method`; widen it and the page's method filter from `id == "mollie"` to any REDIRECT online method returned by `get_available_methods()` (i.e. `mollie` + `ing_ideal`). The intent's `gateway` field records which was used.

## Security & integrity
- Reuse Phase-1 endpoint ownership/payable-state/server-amount guards unchanged (gateway-independent).
- ING `create_ideal_payment` already `check_permission`s the reference doc; the intent is the caller's own (created by the ownership-checked endpoint).
- Finalization runs from ING's webhook (allow_guest, signature-verified) as the ING webhook context; `process_payment`'s `@high_security_api(FINANCIAL)` applies — confirm the ING webhook runs with sufficient privilege (ING webhook uses its own service-user/system context; verify, same class of concern as Phase 1's `webhook_user`).
- The shared finalizer's idempotency + double-payment guards protect both gateways identically.

## Edge cases
- Both gateways enabled → member sees two online options (config-driven, intended). Only one is used per payment; the intent's `gateway` records it.
- Pay.nl webhook vs return-page eventual consistency: same model as Phase 1 (webhook is source of truth; return page shows intent status). ING's default return is `/payment-success` — add "Payment Plan Payment" to that page's `ALLOWED_PAYMENT_DOCTYPES` was done in Phase 1; ING appends `?orderId=` not `?docname=`, so verify the return page resolves the intent for the ING path (may need the ING transaction→intent lookup, OR set ING `return_url` to the Phase-1 `/payment-success?doctype=Payment Plan Payment&docname=<intent>`).
- Failed/expired Pay.nl status → intent Failed/Expired, installment stays payable (shared finalizer handles).

## Testing (real-DB, no business-logic mocks)
- **Shared finalizer**: the extracted `finalize_payment_plan_installment` keeps all Phase-1 webhook tests green (Mollie adapter unchanged behavior); add gateway-neutral unit tests for the finalizer directly.
- **PaymentHook**: `get_available_methods` includes `ing_ideal` only when ING enabled; `initiate_payment(method="ing_ideal", reference_doctype="Payment Plan Payment", …)` returns a normalized redirect (ING client stubbed at the HTTP boundary, per existing ING test patterns in `ing_checkout/tests/`).
- **ING finalization branch**: a Paid Pay.nl webhook for a `Payment Plan Payment` reference finalizes the installment via the shared finalizer (assert installment Paid + intent Paid), does NOT create a generic Payment Entry, and is idempotent; a Sales-Invoice reference still creates the generic Payment Entry (no regression to ING's existing flow).
- **Reference maps**: `create_ideal_order` emits `PPP:<intent>` and `_parse_reference` round-trips it back to ("Payment Plan Payment", intent).
- **Pay page / endpoint**: `initiate_installment_payment(method="ing_ideal")` creates the intent with gateway="Pay.nl" and returns the Pay.nl redirect; the page lists both online methods when both enabled.

## Open questions for review
1. Best home for `INGCheckoutGateway` and the shared finalizer (avoid a Mollie↔ING import tangle; keep the finalizer gateway-neutral).
2. Does extracting `create_ideal_payment`'s core out of the whitelist wrapper break any assumptions (CSRF, `frappe.session`, the `@standard_api` decorator's audit logging)?
3. The `/payment-success` return for the ING path (orderId vs docname) — confirm the resolution path.
4. Whether `ING Checkout Transaction.update_from_webhook`'s existing STATUS_MAP + savepoint semantics compose cleanly with the shared finalizer's own FOR-UPDATE/commit (nested transaction concerns).

## Deliverable
One PR off `develop`, independent, after Phase 1 (#148) merged. Reuses the Phase-1 intent doctype + pay page + button.
