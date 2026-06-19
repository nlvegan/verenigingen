# PaymentLogger Adoption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the existing-but-unused `PaymentLogger` structured-logging utility into the five money-path events it was designed for, so payment logs become category-tagged + JSON-context-enriched.

**Architecture:** Logging-only additions at concrete call sites. Each site imports a convenience function from `verenigingen.verenigingen_payments.utils.payment_services.logging_utils` and calls it at the event point. No control-flow / return-value changes. Where an ad-hoc log already covers the exact event, replace it (avoid double-logging); otherwise add.

**Tech Stack:** Frappe (Python), `bench run-tests`, the project's `EnhancedTestCase` / `VereningingenTestCase`. Tests verify the wiring by patching the convenience function at the call-site module and asserting it is invoked with the right arguments when the event occurs (an observability-boundary mock, annotated `# Mock justified:`).

**Spec:** `docs/superpowers/specs/2026-06-19-payment-logger-adoption-design.md`

**Canonical import (all sites):**
`from verenigingen.verenigingen_payments.utils.payment_services.logging_utils import <fn>`

**Run a single test module:**
`cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module <dotted.module> --test <method>`

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `verenigingen_payments/utils/payment_services/refund_utility.py` | refund orchestration | add `log_refund_initiated` (success branch ×1) + `log_concurrent_refund_detected` (INSUFFICIENT_REFUNDABLE blocks ×2) |
| `verenigingen_payments/mollie/utils/webhook_security.py` | Mollie webhook auth | replace ad-hoc warning with `log_signature_validation_failed` |
| `verenigingen_payments/ing_checkout/utils/webhook_security.py` | ING webhook auth | add `log_signature_validation_failed` before the throw |
| `verenigingen_payments/mollie/api/payment_webhook.py` | Mollie webhook entry | add `log_webhook_received` at handler entry |
| `verenigingen_payments/ing_checkout/api/webhook.py` | ING webhook entry | replace the existing "Processing payment webhook" info log with `log_webhook_received` |
| `verenigingen_payments/hooks/payment_hook.py` | gateway-agnostic payment dispatch | add `log_payment_initiated` at the successful-result return |
| `verenigingen/tests/payment/test_refund_utility.py` | existing refund tests | + 3 wiring tests |
| `verenigingen/tests/payment/test_webhook_security.py` | existing webhook-security tests | + signature-fail wiring tests |
| `verenigingen/tests/payment/test_payment_logger_adoption.py` | NEW — wiring tests that don't fit existing files (webhook_received, payment_initiated) | create |

---

## Task 1: log_refund_initiated on successful refund

**Files:**
- Modify: `verenigingen_payments/utils/payment_services/refund_utility.py` (success branch, ~L243)
- Test: `verenigingen/tests/payment/test_refund_utility.py`

- [ ] **Step 1: Write the failing test**

Add to `test_refund_utility.py`. Mirror the existing `TestRefundExecution` setUp (it builds `self.pe` as a Receive Mollie Payment Entry with `self.payment_id`, and `ensure_mollie_reversal_accounts()` is already imported). Patch `MolliePaymentService` so `create_refund` returns success, and patch the logging fn to assert the wiring.

```python
def test_successful_refund_logs_refund_initiated(self):
    # Mock justified: MolliePaymentService.create_refund is the outbound Mollie HTTP
    # call; log_refund_initiated is the observability event whose wiring is under test.
    with patch(f"{REFUND_MODULE}.MolliePaymentService") as mock_mollie, patch(
        f"{REFUND_MODULE}.log_refund_initiated"
    ) as mock_log:
        mock_mollie.return_value.create_refund.return_value = {
            "status": "success",
            "refund_id": "re_test_123",
            "amount": 10.0,
        }
        result = initiate_refund(payment_entry_name=self.pe.name, amount=10.0, reason="customer request")

    self.assertEqual(result["status"], "success")
    mock_log.assert_called_once()
    kwargs = mock_log.call_args.kwargs or {}
    posargs = mock_log.call_args.args
    # payment_id (the Mollie id), refund_id, amount, reason — accept pos or kw
    called = list(posargs) + list(kwargs.values())
    self.assertIn("re_test_123", called)
    self.assertIn(10.0, called)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.payment.test_refund_utility --test test_successful_refund_logs_refund_initiated`
Expected: FAIL — `mock_log.assert_called_once()` raises (log not wired yet), or `ImportError`/`AttributeError` if `log_refund_initiated` is not importable in the module namespace.

- [ ] **Step 3: Write minimal implementation**

In `refund_utility.py`, add to the existing top-of-file imports:

```python
from verenigingen.verenigingen_payments.utils.payment_services.logging_utils import (
    log_concurrent_refund_detected,
    log_refund_initiated,
)
```

In `initiate_refund`, the success branch (currently `if refund_result["status"] == "success":`), add the log call before building the response:

```python
        if refund_result["status"] == "success":
            log_refund_initiated(
                payment_id=mollie_payment_id,
                refund_id=refund_result["refund_id"],
                amount=refund_result["amount"],
                reason=reason or f"Refund for payment {payment_entry_name}",
            )
            # Return success - webhook will handle creating reverse Payment Entry
            return _create_success_response(
```

(`mollie_payment_id` is the variable already used as the `create_refund(payment_id=...)` argument a few lines above; reuse it.)

- [ ] **Step 4: Run test to verify it passes**

Run: same command as Step 2.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add verenigingen/verenigingen_payments/utils/payment_services/refund_utility.py verenigingen/tests/payment/test_refund_utility.py
git commit -m "feat(payments): log refund_initiated event on successful refund"
```

---

## Task 2: log_concurrent_refund_detected on over-refund block

**Files:**
- Modify: `verenigingen_payments/utils/payment_services/refund_utility.py` (two `INSUFFICIENT_REFUNDABLE_AMOUNT` blocks: `initiate_refund` ~L224, `initiate_donation_refund` ~L550)
- Test: `verenigingen/tests/payment/test_refund_utility.py`

The import was already added in Task 1.

- [ ] **Step 1: Write the failing test**

Mirror the existing `test_over_refund_blocked_by_existing_reversal` (it sets up `self.pe` + a prior Pay-type reversal consuming part of the amount). Add:

```python
def test_over_refund_logs_concurrent_refund_detected(self):
    # Reuse the over-refund setup: a prior reversal leaves < requested available.
    self.create_test_payment_entry(
        payment_type="Pay",
        company=_bank_company(),
        paid_amount=70.0,
        reference_no="re_existing_70b",
        party_type="Supplier",
        party=_make_supplier(self),
        custom_original_payment_id=self.payment_id,
        custom_reversal_type="Refund",
        submit=True,
    )
    # Mock justified: log_concurrent_refund_detected is the observability event under test;
    # MolliePaymentService must never be reached on the blocked path.
    with patch(f"{REFUND_MODULE}.MolliePaymentService") as mock_mollie, patch(
        f"{REFUND_MODULE}.log_concurrent_refund_detected"
    ) as mock_log:
        result = initiate_refund(payment_entry_name=self.pe.name, amount=50.0)
        mock_mollie.return_value.create_refund.assert_not_called()

    self.assertEqual(result["error_code"], "INSUFFICIENT_REFUNDABLE_AMOUNT")
    mock_log.assert_called_once()
    called = list(mock_log.call_args.args) + list((mock_log.call_args.kwargs or {}).values())
    self.assertIn(50.0, called)  # attempted_amount
```

(This test belongs in the same class as `test_over_refund_blocked_by_existing_reversal` so `self.pe` / `self.payment_id` exist.)

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.payment.test_refund_utility --test test_over_refund_logs_concurrent_refund_detected`
Expected: FAIL — `mock_log.assert_called_once()` raises.

- [ ] **Step 3: Write minimal implementation**

In `initiate_refund`, the over-refund guard (`if amount > available_amount:`), add before the return:

```python
        if amount > available_amount:
            log_concurrent_refund_detected(
                payment_id=mollie_payment_id,
                attempted_amount=amount,
                available_amount=available_amount,
            )
            return _create_error_response(
                f"Only {available_amount} available for refund (already reversed: {total_reversed})",
                error_code="INSUFFICIENT_REFUNDABLE_AMOUNT",
```

In `initiate_donation_refund`, the over-refund guard there (`if amount > available_amount:` ~L550). Note this function does not have a Mollie payment id in scope; use the payment entry name as the identifier:

```python
        if amount > available_amount:
            log_concurrent_refund_detected(
                payment_id=payment_to_refund.name,
                attempted_amount=amount,
                available_amount=available_amount,
            )
            return _create_error_response(
                f"Only {available_amount} available for refund from this payment",
                error_code="INSUFFICIENT_REFUNDABLE_AMOUNT",
```

- [ ] **Step 4: Run test to verify it passes**

Run: same command as Step 2.
Expected: PASS. Also re-run the whole module to confirm no regression:
`bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.payment.test_refund_utility`
Expected: all OK.

- [ ] **Step 5: Commit**

```bash
git add verenigingen/verenigingen_payments/utils/payment_services/refund_utility.py verenigingen/tests/payment/test_refund_utility.py
git commit -m "feat(payments): log concurrent_refund_detected on over-refund block"
```

---

## Task 3: log_signature_validation_failed on webhook signature failure

**Files:**
- Modify: `verenigingen_payments/mollie/utils/webhook_security.py` (signature-fail `except`, ~L76-80 — REPLACE the existing `frappe.logger().warning(...)`)
- Modify: `verenigingen_payments/ing_checkout/utils/webhook_security.py` (the `if not verify_ing_checkout_webhook(...)` block, ~L29 — ADD before `frappe.throw`)
- Test: `verenigingen/tests/payment/test_webhook_security.py`

- [ ] **Step 1: Write the failing tests**

The ING site is the simplest to trigger (a plain function). Add to `test_webhook_security.py`:

```python
def test_ing_invalid_signature_logs_event(self):
    from verenigingen.verenigingen_payments.ing_checkout.utils import webhook_security as ing_ws

    # Mock justified: verify_ing_checkout_webhook is the crypto boundary; force a
    # rejection. log_signature_validation_failed is the observability event under test.
    with patch.object(ing_ws, "verify_ing_checkout_webhook", return_value=False), patch.object(
        ing_ws, "log_signature_validation_failed"
    ) as mock_log:
        with self.assertRaises(frappe.AuthenticationError):
            ing_ws.validate_ing_webhook_signature(b"{}", "bad-sig")  # the fn containing the L29 check
    mock_log.assert_called_once()
```

(Confirm the exact name of the function containing the `if not verify_ing_checkout_webhook(...)` check at implementation time — it is the public validate entry in that module; call it with a payload + bad signature.)

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.payment.test_webhook_security --test test_ing_invalid_signature_logs_event`
Expected: FAIL — `mock_log` not called (and `AttributeError` patching a name not yet imported).

- [ ] **Step 3: Write minimal implementation**

ING `ing_checkout/utils/webhook_security.py` — add the import near the top:

```python
from verenigingen.verenigingen_payments.utils.payment_services.logging_utils import (
    log_signature_validation_failed,
)
```

and in the rejection block:

```python
    if not verify_ing_checkout_webhook(payload, signature):
        log_signature_validation_failed(
            webhook_id="ing_checkout",
            expected_vs_actual={"signature_present": bool(signature)},
        )
        frappe.throw("Invalid webhook signature", frappe.AuthenticationError)
```

Mollie `mollie/utils/webhook_security.py` — add the same import, then **replace** the existing ad-hoc warning in the signature-fail `except` (currently `frappe.logger().warning(f"Mollie webhook signature validation failed: {e}", ...)`):

```python
    except Exception as e:
        log_signature_validation_failed(
            webhook_id="mollie",
            expected_vs_actual={"error": str(e)},
        )
        raise
```

(Keep the surrounding `try`/`raise` structure exactly as-is; only swap the log line.)

- [ ] **Step 4: Run test to verify it passes**

Run: same command as Step 2.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add verenigingen/verenigingen_payments/mollie/utils/webhook_security.py verenigingen/verenigingen_payments/ing_checkout/utils/webhook_security.py verenigingen/tests/payment/test_webhook_security.py
git commit -m "feat(payments): log signature_validation_failed on webhook auth failure"
```

---

## Task 4: log_webhook_received at webhook entry

**Files:**
- Modify: `verenigingen_payments/mollie/api/payment_webhook.py` — `handle_mollie_payment_webhook` (~L17), ADD at entry
- Modify: `verenigingen_payments/ing_checkout/api/webhook.py` — `handle_payment` (~L58), REPLACE the existing `frappe.logger().info(f"Processing payment webhook: order={order_id}...")` (~L170) with `log_webhook_received`
- Test: `verenigingen/tests/payment/test_payment_logger_adoption.py` (create)

- [ ] **Step 1: Write the failing test**

Create `test_payment_logger_adoption.py`. The ING `handle_payment` parses `order_id`/`reference` from the request body; rather than build a full webhook request, assert wiring by patching at the module and invoking the handler with a minimal valid body via `frappe.local.form_dict` / request stub the existing ING webhook tests use (mirror `tests/.../test_webhook*.py` for ING). If constructing the request is heavy, assert at the narrowest seam: patch `log_webhook_received` and the downstream processing, then call the handler.

```python
import frappe
from unittest.mock import patch
from verenigingen.tests.utils.base import VereningingenTestCase


class TestWebhookReceivedLogging(VereningingenTestCase):
    def test_mollie_webhook_logs_received(self):
        from verenigingen.verenigingen_payments.mollie.api import payment_webhook as pw

        # Mock justified: stub the downstream webhook processing + request so only the
        # entry-point log_webhook_received wiring is exercised.
        with patch.object(pw, "log_webhook_received") as mock_log, patch.object(
            pw, "_process_mollie_payment_webhook", create=True, return_value={"status": "ok"}
        ):
            frappe.local.form_dict = frappe._dict({"id": "tr_webhook_1"})
            try:
                pw.handle_mollie_payment_webhook()
            except Exception:
                pass  # downstream may still raise; we only assert the entry log fired
        mock_log.assert_called_once()
```

(At implementation time, confirm the actual downstream call name inside `handle_mollie_payment_webhook` to patch; the assertion is that `log_webhook_received` fired at entry regardless.)

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.payment.test_payment_logger_adoption --test test_mollie_webhook_logs_received`
Expected: FAIL — `mock_log` not called.

- [ ] **Step 3: Write minimal implementation**

Mollie `mollie/api/payment_webhook.py` — add import + log at the very start of `handle_mollie_payment_webhook`, reading the payment id defensively:

```python
from verenigingen.verenigingen_payments.utils.payment_services.logging_utils import (
    log_webhook_received,
)

# inside handle_mollie_payment_webhook(), first line of the body:
    _pid = (frappe.local.form_dict or {}).get("id", "")
    log_webhook_received(webhook_id=_pid or "unknown", webhook_type="mollie", payload_size=len(frappe.request.data) if getattr(frappe, "request", None) else 0)
```

ING `ing_checkout/api/webhook.py` — add the same import; **replace** the existing `frappe.logger().info(f"Processing payment webhook: order={order_id}, reference={reference}")` (~L170) with:

```python
    log_webhook_received(
        webhook_id=order_id or reference or "unknown",
        webhook_type="ing_checkout",
        payload_size=len(frappe.request.data) if getattr(frappe, "request", None) else 0,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: same command as Step 2.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add verenigingen/verenigingen_payments/mollie/api/payment_webhook.py verenigingen/verenigingen_payments/ing_checkout/api/webhook.py verenigingen/tests/payment/test_payment_logger_adoption.py
git commit -m "feat(payments): log webhook_received at Mollie/ING webhook entry"
```

---

## Task 5: log_payment_initiated at the gateway-agnostic chokepoint

**Files:**
- Modify: `verenigingen_payments/hooks/payment_hook.py` — `PaymentHook.initiate_payment`, the success return `return cls._normalize_gateway_response(method, result)` (~L295)
- Test: `verenigingen/tests/payment/test_payment_logger_adoption.py`

- [ ] **Step 1: Write the failing test**

Stub the gateway so `initiate_payment` reaches a successful normalized result, and assert the log fired. Reuse the sweep's gateway-stub idea (a fake gateway whose `process_payment` returns a redirect/success dict).

```python
class TestPaymentInitiatedLogging(VereningingenTestCase):
    def test_initiate_payment_logs_payment_initiated(self):
        from verenigingen.verenigingen_payments.hooks import payment_hook as ph

        class _FakeGateway:
            def process_payment(self, ref_doc, form_data):
                return {"status": "redirect_required", "payment_url": "https://x", "payment_id": "tr_init_1"}

        member = self.create_test_member(first_name="PayInit")
        # Mock justified: PaymentGatewayFactory.get_gateway is the SDK boundary; the
        # method-availability check and log_payment_initiated wiring run for real.
        with patch.object(ph.PaymentGatewayFactory, "get_gateway", return_value=_FakeGateway()), patch.object(
            ph.PaymentHook, "get_available_methods", return_value=[{"id": "mollie"}]
        ), patch.object(ph, "log_payment_initiated") as mock_log:
            result = ph.PaymentHook.initiate_payment(
                method="mollie",
                amount=25.0,
                reference_doctype="Member",
                reference_name=member.name,
                payer_info={"email": "payinit@example.com"},
                redirect_urls={"success": "/ok", "cancel": "/no"},
            )

        self.assertTrue(result.get("success"))
        mock_log.assert_called_once()
        called = list(mock_log.call_args.args) + list((mock_log.call_args.kwargs or {}).values())
        self.assertIn(25.0, called)
        self.assertIn("mollie", called)
```

(If `_normalize_gateway_response` strips `payment_id` for a redirect action, set the fake's return to include whatever the normalizer maps to `payment_id`; verify the normalized dict's `payment_id` key at implementation time.)

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.payment.test_payment_logger_adoption --test test_initiate_payment_logs_payment_initiated`
Expected: FAIL — `mock_log` not called.

- [ ] **Step 3: Write minimal implementation**

`payment_hook.py` — add the import at top:

```python
from verenigingen.verenigingen_payments.utils.payment_services.logging_utils import (
    log_payment_initiated,
)
```

Replace the success return in `initiate_payment`:

```python
            # Normalize response to standard format
            normalized = cls._normalize_gateway_response(method, result)
            if normalized.get("success") and normalized.get("payment_id"):
                log_payment_initiated(
                    payment_id=normalized["payment_id"],
                    amount=amount,
                    payment_method=method,
                )
            return normalized
```

- [ ] **Step 4: Run test to verify it passes**

Run: same command as Step 2.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add verenigingen/verenigingen_payments/hooks/payment_hook.py verenigingen/tests/payment/test_payment_logger_adoption.py
git commit -m "feat(payments): log payment_initiated at gateway-agnostic chokepoint"
```

---

## Task 6: Full-suite verification + push

- [ ] **Step 1: Run all touched test modules serially**

Run each and confirm `OK`:
```
bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.payment.test_refund_utility
bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.payment.test_webhook_security
bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.payment.test_payment_logger_adoption
```

- [ ] **Step 2: Lint the changed production files**

Run: `ruff check verenigingen/verenigingen_payments/utils/payment_services/refund_utility.py verenigingen/verenigingen_payments/mollie/utils/webhook_security.py verenigingen/verenigingen_payments/ing_checkout/utils/webhook_security.py verenigingen/verenigingen_payments/mollie/api/payment_webhook.py verenigingen/verenigingen_payments/ing_checkout/api/webhook.py verenigingen/verenigingen_payments/hooks/payment_hook.py`
Expected: no errors (fix import sorting with `ruff check --fix` if flagged).

- [ ] **Step 3: Skeptical review**

Dispatch the skeptical-code-reviewer on the diff (`git diff <base>..HEAD`) to confirm: no control-flow changed, no double-logging at the two replace sites, the tests genuinely assert the wiring (would fail if the log call were removed), and the `payload_size`/`webhook_id` reads can't raise inside the webhook try/except.

- [ ] **Step 4: Push and watch the gate**

```bash
git push origin develop
```
Then watch the Server Tests run (`gh run watch <id> --exit-status`). **Note (from the coverage-sweep experience): adding test files rebuckets the 12 shards and may surface latent order-dependence.** If the gate reports NEW failures, triage them: fix any that are ours, baseline pre-existing elusive order-dependence in `verenigingen/tests/known_test_failures.txt` (the new-failure list is between "introduces test failures not in the baseline" and the `##[error]` line).

---

## Notes for the executor

- The convenience functions never raise on bad input (they JSON-serialize defensively with `default=str`), but the **arguments** you pass must be plain values computed without risk — especially inside webhook try/except blocks. The `payload_size` reads guard `frappe.request` with `getattr(...)`.
- Import the convenience functions at **module top level** (not inside the function) so the tests can patch them at `<module>.<fn>`.
- `test-quality-enforcer` (pre-commit, blocking) forbids DB mocks and business-logic mocks in tests. The only mocks here are the **outbound crypto/HTTP/SDK boundary** and the **logging convenience function itself** (the observability boundary whose wiring is the subject under test) — annotate each `# Mock justified:`. Do NOT mock `frappe.db.*`, `frappe.get_roles`, or `frappe.session`.
- Run tests **serially** (concurrent runs on the shared veg11 DB cause spurious `QueryDeadlockError`).
