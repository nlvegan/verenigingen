# Payment Plan "Make Payment" — Pay.nl / iDEAL (A3, Phase 2)

**Date:** 2026-07-11
**Audit item:** A3 Phase 2 (2026-07-10 TODO / unfinished-feature audit). Phase 1 (Mollie) = PR #148 (merged).
**Status:** Design — revised after skeptical review (2026-07-11)

> **Revision note:** A skeptical design review confirmed the *initiation* path (new gateway + factory + normalization) is sound, but found the *finalization* path's chosen insertion point wrong and dangerous. Fixed below:
> 1. **Finalize at the TOP of ING's `handle_payment` webhook entry** (parallel to Mollie's top-level dispatch) — NOT inside `update_from_webhook`, which runs inside `handle_payment`'s savepoint. The shared finalizer calls `frappe.db.commit()`/`rollback()`; inside ING's savepoint that would commit the whole request, destroy the savepoint, and release the FOR-UPDATE lock early.
> 2. **Establish a privileged webhook user before finalizing.** ING's `handle_payment` currently runs as **Guest** (`authenticate_webhook()` is imported but never called); `PaymentPlan.process_payment` is `@high_security_api(FINANCIAL)` and rejects Guest — the finalizer would catch it, return `error`, ING would log success + return 200, and Pay.nl would stop retrying → **silent lost payment**.
> 3. **Translate a finalizer `error` result into an HTTP 500** on the ING path so Pay.nl retries (Mollie inspects the return dict; ING relies on exceptions→500 — the finalizer never raises).
> 4. **Do NOT branch `update_from_webhook`** (it advances `status="Paid"` before finalizing → a retry after a failed finalize would skip forever). The `/payment-success` return path already works for ING via `orderId` (spec's earlier worry was unfounded). Factual corrections: `create_ideal_payment` is `@high_security_api(FINANCIAL)` (not `@standard_api`); `intent.gateway` is currently hardcoded `"Mollie"` and needs a `method→gateway` map; `intent.payment_id` is set at finalize, not initiation.

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
- **New method** in `PaymentHook`: id `ing_ideal`, label **"iDEAL via ING/Pay.nl"** (distinct from Mollie's "Online payment" to avoid two identical-looking iDEAL buttons), `type=REDIRECT`. Add to `_METHOD_TO_GATEWAY` → gateway name `"ING Checkout"`. `get_available_methods()` gains an ING branch that appends the method **iff** ING Checkout is enabled — **guarded in try/except** (like the other gateway branches): `get_ing_checkout_settings()` THROWS when disabled (`ing_checkout_settings.py:99-102`), so an unguarded branch would crash the whole method list and hide Mollie/SEPA/cash on the pay page too. Use `is_ing_checkout_enabled()`/`settings.enabled`.
- **`INGCheckoutGateway(PaymentGateway)`** in `utils/payment_gateways.py` (or an ING-owned module registered into the factory): `process_payment(ref_doc, form_data)`:
  - reads amount from `form_data["amount"]` (falls back to `ref_doc.amount`), currency EUR, description from `form_data.get("description_override")`;
  - calls the **extracted core** of `create_ideal_payment` (an internal service function, e.g. `ing_checkout/services/transaction_service.py::create_ideal_order(reference_doctype, reference_name, amount, description, return_url)` — refactor `create_ideal_payment` to a thin `@frappe.whitelist()` wrapper over it so the gateway can call the core without the whitelist layer);
  - returns `{"status": "redirect_required", "payment_url": <redirect_url>, "payment_id": <order_id>}` so the existing `_normalize_gateway_response` redirect branch yields `{action: redirect, data:{url}, payment_id}`. No new normalization branch needed.
  - `handle_webhook`/`get_payment_status`: ING's own webhook route (`ing_checkout/api/webhook.py`) handles confirmation, so these return a benign dict — `{"status": "not_applicable"}` / `{"status": "delegated"}` — matching the existing convention (`BankTransferGateway.handle_webhook` at `payment_gateways.py:81-83`, `PontoGateway` at `:957-964`). Do NOT raise `NotImplementedError`.
- Register `"ING Checkout": INGCheckoutGateway` in `PaymentGatewayFactory._gateways`.

### 2. Shared, gateway-agnostic installment finalizer (DRY)
- Extract the Phase-1 finalization core into `verenigingen_payments/services/payment_plan_finalization.py::finalize_payment_plan_installment(intent_name, payment_reference, status="paid") -> dict` (gateway-neutral home, NOT under `mollie/`). It performs: FOR-UPDATE lock on the intent, idempotency guard on the locked status, installment-already-Paid double-payment guard (log + skip), `PaymentPlan.process_payment(...)`, then mark intent Paid — returning `{"status": "success"|"skipped"|"error", ...}`. It **keeps its `frappe.db.commit()`/`rollback()`** — these are correct ONLY when the finalizer runs at a webhook top level with no enclosing savepoint (Mollie's dispatch and ING's new top-of-`handle_payment` dispatch both satisfy this; that's precisely why it must NOT be called from inside `update_from_webhook`).
- **Refactor Phase 1**: `mollie/services/payment_plan_payment_handler.py::handle_payment_plan_payment` becomes a thin adapter that maps the Mollie payment status to `paid/failed/expired` and calls `finalize_payment_plan_installment`. Phase-1 tests must stay green (behavior identical).

### 3. ING finalization — at the webhook ENTRY, not in the transaction doctype
- Add `"Payment Plan Payment": "PPP"` to the **initiation core `DOCTYPE_CODES`** (payment.py) and `"PPP": "Payment Plan Payment"` to **`_parse_reference` `DOCTYPE_MAP`** (webhook.py). Set both explicitly (the `[:4].upper()` fallback gives `PAYM`, asymmetric/collision-risk).
- **Dispatch at the top of `ing_checkout/api/webhook.py::handle_payment`** (after signature verification + idempotency, BEFORE the `frappe.db.savepoint(...)` block and BEFORE `_process_payment_webhook`): parse the order's `reference`; when `reference_doctype == "Payment Plan Payment"`:
  1. **Authenticate**: call the existing (currently-unused) `authenticate_webhook()` / set the ING `webhook_user` so `process_payment`'s FINANCIAL tier passes (default Administrator passes; a restricted webhook user must hold the tier — deployment note, same class as Phase 1);
  2. call the shared `finalize_payment_plan_installment(reference_name, payment_reference=order_id, status=<mapped pay.nl status>)` — which runs at top level, so its `commit()`/`rollback()` are safe (no enclosing savepoint / advanced transaction status);
  3. translate the result → HTTP, being careful about the dedup log:
     - `success`/`skipped` → set `http_status_code=200`, write the Webhook Processing Log success entry (so genuine duplicate deliveries dedupe), `db_set` the `ING Checkout Transaction.status`, and `return`.
     - **`error` → set `frappe.local.response["http_status_code"] = 500` and `return` DIRECTLY — do NOT `raise` and do NOT write a Webhook Processing Log entry.** `handle_payment`'s generic `except` (`webhook.py:218-228`) calls `log_webhook(status="error")`, which writes a dedup row keyed on the deterministic `SHA256(event_id:payload)` hash **regardless of status**; `is_duplicate_webhook` (`:140`) then returns True for Pay.nl's identical retry → HTTP 200 `duplicate` → the finalizer **never re-runs** = the silent-lost-payment this fix exists to prevent. So the error path must bypass that logging entirely. Operator visibility is preserved by the finalizer's own Error Log (`payment_plan_payment_handler.py:118-121`), a different table from the dedup log. The finalizer's FOR-UPDATE/status idempotency makes the eventual retry safe.
  4. `return` — do NOT fall through to `_process_payment_webhook`/`update_from_webhook`/generic Payment Entry. **`db_set` the `ING Checkout Transaction.status`** on the 200 paths (non-optional — so the transaction list doesn't show "Pending" for a paid installment; ops clarity).

**Pay.nl status → finalizer status mapping** (used by the dispatch): Pay.nl status code `100` → `"paid"`; `-63`/`-90` → `"failed"`; `-64` → `"expired"`; `20`/`25` (pending/verify) → treat as not-yet-final (no-op 200, do not finalize). Verify against `STATUS_MAP` in `ing_checkout_transaction.py` when implementing.
  Other reference types fall through to the existing ING flow unchanged.
- **Do NOT branch `update_from_webhook`** — it advances `status="Paid"` and `save()`s before finalizing, and its "already paid" guard keys on `old_status != "Paid"`; a first-finalize failure there would make every Pay.nl retry short-circuit and never finalize.
- **Intent reuse:** the Phase-1 intent doctype is the reference. `payment_id` is set by the shared finalizer at finalize time (Pay.nl order id), exactly as Phase 1 does for Mollie — NOT at initiation.
- **`intent.gateway`:** `initiate_installment_payment` currently hardcodes `"Mollie"` (`payment_plan_management.py:350`). Add a `method → gateway` map (`mollie→"Mollie"`, `ing_ideal→"Pay.nl"`) and record the chosen gateway.
- **Pay page:** widen the method filter in `templates/pages/payment_plan_pay.py` (and the endpoint) from `id == "mollie"` to the set of enabled REDIRECT online methods `get_available_methods()` returns (`mollie` + `ing_ideal`). No template rewrite (it already loops `payment_methods`).

## Security & integrity
- Reuse Phase-1 endpoint ownership/payable-state/server-amount guards unchanged (gateway-independent).
- ING `create_ideal_payment` is `@high_security_api(FINANCIAL)` and already `check_permission`s the reference doc; the intent is the caller's own (created by the ownership-checked endpoint). When the gateway calls the extracted core, that FINANCIAL gate is lost — but the PaymentHook/endpoint path has already validated ownership + membership, so the core call is trusted.
- **CRITICAL:** ING's `handle_payment` webhook currently runs as **Guest** (`authenticate_webhook()` is imported but never called — verified zero call sites). `process_payment` is `@high_security_api(FINANCIAL)`, whose `validate_authentication` fires even on in-process calls and rejects Guest → the finalizer catches it, returns `error`. The new dispatch MUST set a privileged webhook user (`authenticate_webhook()` / a `webhook_user` holding the FINANCIAL tier; default Administrator passes) **before** calling the finalizer, and MUST surface an `error` result as HTTP 500 so Pay.nl retries — returning 500 **directly without writing a Webhook Processing Log entry** (see finalization step 3: an error dedup-log row would make the retry short-circuit to a 200 `duplicate` and never re-run). Auth must happen AFTER signature verification (so an unauthenticated attacker cannot trigger a privileged `set_user` + finalize).
- The shared finalizer's idempotency (intent FOR-UPDATE + status guard) + double-payment (installment-already-Paid) guards protect both gateways identically. Two tracking records exist per Pay.nl payment (the `Payment Plan Payment` intent = domain state; the `ING Checkout Transaction` = gateway tracking) — finalization idempotency keys on the **intent** status, not the ING transaction.

## Edge cases
- Both gateways enabled → member sees two online options (config-driven, intended). Only one is used per payment; the intent's `gateway` records it.
- **Return page already works for ING** (spec's earlier worry was unfounded): `payment_success.py` checks `orderId` first → `handle_ing_checkout_return` looks up the `ING Checkout Transaction` by order id and resolves `reference_doctype/name` generically; `"Payment Plan Payment"` is already in `ALLOWED_PAYMENT_DOCTYPES` (added in Phase 1). `initiate_installment_payment` passes no `redirect_urls`, so the ING core defaults `return_url=/payment-success` and Pay.nl appends `?orderId=`. Webhook remains source of truth; the return page shows current status.
- **Status-ordering:** because finalization happens at the top of `handle_payment` (before `_process_payment_webhook`/`update_from_webhook` runs), the ING transaction's `status`/`old_status` short-circuit never gates payment-plan finalization — avoiding the "first finalize fails → retry sees Paid → never finalizes" trap.
- Failed/expired Pay.nl status → intent Failed/Expired, installment stays payable (shared finalizer handles).
- ING disabled → `get_available_methods` omits `ing_ideal` (guarded); the pay page simply shows Mollie (or a "not available" message if neither is enabled).

## Testing (real-DB, no business-logic mocks)
- **Shared finalizer**: the extracted `finalize_payment_plan_installment` keeps all Phase-1 webhook tests green (Mollie adapter unchanged behavior); add gateway-neutral unit tests for the finalizer directly.
- **PaymentHook**: `get_available_methods` includes `ing_ideal` only when ING enabled; `initiate_payment(method="ing_ideal", reference_doctype="Payment Plan Payment", …)` returns a normalized redirect (ING client stubbed at the HTTP boundary, per existing ING test patterns in `ing_checkout/tests/`).
- **ING webhook dispatch (the critical path)**: a Paid Pay.nl webhook for a `Payment Plan Payment` reference finalizes via the shared finalizer (assert installment Paid + intent Paid), does NOT create a generic Payment Entry, and is idempotent; a Sales-Invoice reference still creates the generic Payment Entry (no regression). Specifically assert:
  - the finalizer runs with a **privileged user** (not Guest) — a test that the dispatch does not get rejected by `process_payment`'s FINANCIAL gate;
  - a finalizer **`error` → HTTP 500 AND no Webhook Processing Log entry written** — assert that a subsequent identical retry is NOT deduped to 200 and actually re-runs the finalizer (this is the subtle failure mode: an error dedup-row would short-circuit the retry);
  - finalization happens at `handle_payment` top level (dispatch fires **before** `_process_payment_webhook`; the ING transaction's status short-circuit never blocks a payment-plan retry).
- **Reference maps**: `create_ideal_order` emits `PPP:<intent>` and `_parse_reference` round-trips it back to ("Payment Plan Payment", intent).
- **Pay page / endpoint**: `initiate_installment_payment(method="ing_ideal")` creates the intent with gateway="Pay.nl" and returns the Pay.nl redirect; the page lists both online methods when both enabled.

## Resolved by review (were open questions)
1. **Home:** `finalize_payment_plan_installment` → `verenigingen_payments/services/payment_plan_finalization.py` (gateway-neutral, no Mollie/ING import tangle); `INGCheckoutGateway` → `utils/payment_gateways.py` beside the others (or an ING-owned module registered into the factory).
2. **Extracting the core** out of the whitelist wrapper is safe: the body only touches `frappe.session` via `check_permission`; refactor `create_ideal_payment` into a thin `@high_security_api(FINANCIAL)` `@frappe.whitelist()` wrapper over a `create_ideal_order(...)` core the gateway calls. (Decorator is `@high_security_api`, not `@standard_api`.)
3. **Return path already works** (see Edge cases) — no extra plumbing.
4. **Transaction composition is the whole reason** finalization moved to the top of `handle_payment` (no enclosing savepoint), NOT inside `update_from_webhook`. The finalizer keeps its own FOR-UPDATE + commit/rollback.

## Deployment note
The ING `webhook_user` (like Mollie's) must hold the FINANCIAL tier for `process_payment` to run; it defaults to Administrator (which passes). Document in the PR.

## Deliverable
One PR off `develop`, independent, after Phase 1 (#148) merged. Reuses the Phase-1 intent doctype + pay page + button.
