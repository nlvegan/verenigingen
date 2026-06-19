# Adopt PaymentLogger at key money-path events — design

Date: 2026-06-19
Status: Approved (design), pending implementation plan

## Context

`verenigingen_payments/utils/payment_services/logging_utils.py` defines a
`PaymentLogger` (a thin wrapper over `frappe.logger()` + `frappe.log_error()`)
plus five convenience functions. It is well-formed but **never adopted** —
zero importers anywhere in the codebase; payment modules log ad-hoc via
`frappe.logger()` / `frappe.log_error()` directly. `PaymentLogger` adds, on top
of those primitives: category tags (`[Payment Refund]` …), a JSON `Context:`
block, automatic timestamp/session-user enrichment, and (for errors) writing to
**both** the log file and the Error Log doctype.

Decision (Foppe): adopt it rather than delete it, at the **key money-path
events** it was designed for. Not a full migration of all payment logging.

## Goal

Make the five designed events emit structured `PaymentLogger` records at their
natural call sites, so payment logs become category-tagged and searchable.
**Logging only — no control-flow or behavior change** beyond richer log output.

## Scope — call sites

Import the convenience functions from the canonical module
`verenigingen.verenigingen_payments.utils.payment_services.logging_utils`.

| Event fn | Site | Add / Replace |
|---|---|---|
| `log_payment_initiated(payment_id, amount, payment_method)` | `verenigingen_payments/hooks/payment_hook.py` — `PaymentHook.initiate_payment`, at the successful-result return (gateway-agnostic chokepoint: covers mollie / sepa / bank_transfer / cash). Uses `method`, validated `amount`, and `result.get("payment_id")` | **Add** |
| `log_refund_initiated(payment_id, refund_id, amount, reason)` | `verenigingen_payments/utils/payment_services/refund_utility.py` — `initiate_refund`, in the `refund_result["status"] == "success"` branch (~L237); and the equivalent success branch in `initiate_donation_refund` | **Add** |
| `log_concurrent_refund_detected(payment_id, attempted_amount, available_amount)` | `refund_utility.py` — the `INSUFFICIENT_REFUNDABLE_AMOUNT` guard (`if amount > available_amount`, ~L224) and its donation twin (~L553), before the error return | **Add** |
| `log_webhook_received(webhook_id, webhook_type, payload_size)` | Mollie webhook entry handler and ING checkout webhook entry handler (at handler start, once a webhook/payment id is available) | **Add** |
| `log_signature_validation_failed(webhook_id, expected_vs_actual)` | `verenigingen_payments/mollie/utils/webhook_security.py` (the signature-fail `except`, currently `logger().warning(...)` ~L77) and `verenigingen_payments/ing_checkout/utils/webhook_security.py` equivalent | **Replace** the existing ad-hoc warning (same event → avoid a duplicate line) |

## Principle

- **Additive** where no equivalent log exists at the site.
- **Replace** where an ad-hoc log already covers the exact same event (only the
  signature-validation-failed sites today).
- Do not change any `raise`, return value, or control flow. Logging calls are
  best-effort and must not throw into the money path — where a site is inside a
  critical try/except, ensure the logging call cannot raise (the convenience
  functions already serialize defensively; `webhook_id`/ids passed must be plain
  values).

## Testing

Each wired event gets an assertion it fires, reusing the sweep's existing test
files (`tests/payment/test_refund_utility.py`, `tests/payment/test_webhook_security.py`)
plus the gateway/webhook test modules:

- **Error-severity event** (`log_signature_validation_failed` → `log_error`):
  assertable via the **Error Log** doctype — a new row with the
  `[Payment Security]` category appears on a failed signature.
- **Info / warning events** (`log_payment_initiated`, `log_refund_initiated`,
  `log_webhook_received`, `log_concurrent_refund_detected`): these go to
  `frappe.logger()` only. Tests capture the logger (patch `frappe.logger` — an
  infrastructure mock, annotated `# Mock justified:`) and assert the structured
  message carries the right category and key fields (payment_id, amounts).
- Tests assert the **event fires with correct fields**, not log-file contents;
  control-flow assertions (refund still blocked, signature still raises) remain.

~6 focused tests. Run serially; the suite is part of `tests/payment/`.

## Out of scope (YAGNI)

- The many other ad-hoc `frappe.logger()` / `frappe.log_error()` calls across
  `verenigingen_payments/` — left as-is (not a full migration).
- The deprecation shim `verenigingen/utils/payment_services/logging_utils.py`
  stays; we import from the canonical `verenigingen_payments` path.
- No new event types beyond the five existing convenience functions.

## Acceptance criteria

1. Each of the five events emits a `PaymentLogger` record at the listed site(s).
2. No production control-flow/return-value changes; existing behavior tests pass.
3. The signature-fail sites no longer double-log (replaced, not duplicated).
4. ~6 tests assert each event fires with the right category/fields; all green.
5. CI gate stays green (mind shard rebucketing from added tests — same caveat as
   the coverage sweep; expect to fix/baseline any surfaced order-dependence).
