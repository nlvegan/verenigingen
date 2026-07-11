# Payment Plan "Make Payment" — Pay.nl / iDEAL (A3 Phase 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add Pay.nl (iDEAL) as a second online method for paying a payment-plan installment, exposed through the same `/payment_plan_pay` page, by wiring the existing ING Checkout integration into the shared `PaymentHook`; the installment is finalized only after Pay.nl confirms payment (webhook), reusing Phase 1's finalization semantics.

**Architecture:** (1) Extract Phase-1 installment finalization into one gateway-agnostic function; (2) add an `INGCheckoutGateway` to `PaymentHook` over an extracted `create_ideal_order` core so the pay page shows enabled gateways; (3) finalize Pay.nl payments at the **top of ING's `handle_payment` webhook** (authenticated, error→500 without a dedup-log entry) via the shared finalizer.

**Tech Stack:** Frappe/ERPNext (Python 3.12), Mollie + ING Checkout (Pay.nl), `frappe.tests` (real-DB).

**Spec:** `docs/superpowers/specs/2026-07-11-payment-plan-make-payment-paynl-phase2-design.md` (2 skeptical review passes).

## Global Constraints

- Site for tests: `test_site_1` (NEVER veg11). `cd ~/frappe-bench && bench --site test_site_1 run-tests --app verenigingen --module <dotted.module>`. Run each module separately (multiple `--module` runs only the last).
- `@frappe.whitelist()` OUTERMOST, above any security decorator.
- User-facing strings in `_()`. Black line length 110. `ruff check` before commit. `.html` not prettier-gated.
- `test-quality-enforcer` blocks `ignore_permissions`/mock patterns in `test_*` methods → extract `_`-prefixed helpers, never weaken assertions.
- Reuse the Phase-1 `Payment Plan Payment` intent doctype (do NOT create a new one).
- Pay.nl status → finalizer status: `100`→`"paid"`; `-63`/`-90`→`"failed"`; `-64`→`"expired"`; `20`/`25`→pending (no-op). (From `STATUS_MAP`, `ing_checkout_transaction.py:25`.)
- The webhook error path MUST return HTTP 500 **without** writing a Webhook Processing Log entry (an error dedup row makes Pay.nl's identical retry short-circuit to a 200 `duplicate` and never re-run the finalizer).

---

### Task 1: Extract the gateway-agnostic installment finalizer

**Files:**
- Create: `verenigingen/verenigingen_payments/services/payment_plan_finalization.py`
- Create: `verenigingen/verenigingen_payments/services/__init__.py` (if missing)
- Modify: `verenigingen/verenigingen_payments/mollie/services/payment_plan_payment_handler.py` (make `handle_payment_plan_payment` delegate)
- Test: `verenigingen/tests/payment/test_payment_plan_finalization.py`

**Interfaces:**
- Produces: `finalize_payment_plan_installment(intent_name: str, payment_reference: str, status: str = "paid") -> dict` — status one of `"paid"`/`"failed"`/`"expired"`/other; returns `{"status": "success"|"skipped"|"error", ...}`. Same behavior as the Phase-1 Mollie handler's core (FOR-UPDATE lock, idempotency guard on locked status, installment-already-Paid double-payment guard, `PaymentPlan.process_payment`, mark intent Paid; keeps its own `commit()`/`rollback()`).

- [ ] **Step 1: Create the shared finalizer by moving the core out of the Mollie handler**

Create `verenigingen/verenigingen_payments/services/__init__.py` (empty if it doesn't exist) and `verenigingen/verenigingen_payments/services/payment_plan_finalization.py`:

```python
# Copyright (c) 2026, Verenigingen
"""Gateway-agnostic finalization of a payment-plan installment payment.

Called from a payment gateway's webhook AT WEBHOOK TOP LEVEL (no enclosing
savepoint), because it commits/rolls back the request transaction. The
installment is marked Paid via PaymentPlan.process_payment ONLY here (never on a
member-triggered path), so a member cannot self-certify payment.
"""

import frappe
from frappe.utils import today


def finalize_payment_plan_installment(intent_name: str, payment_reference: str, status: str = "paid") -> dict:
    """Idempotently finalize the installment for a Payment Plan Payment intent.

    status: the gateway-neutral payment status ("paid" finalizes; "failed"/
    "expired" record and leave the installment payable; anything else is a no-op).
    """
    try:
        # Lock the intent row and read the fields we act on FROM THE LOCKED ROW
        # (CLAUDE.md Pattern 5) so a concurrent duplicate can't read a stale
        # pre-lock snapshot and slip past the idempotency guard.
        locked = frappe.db.sql(
            """SELECT name, status, payment_plan, installment_number, amount, payment_id
               FROM `tabPayment Plan Payment` WHERE name=%s FOR UPDATE""",
            intent_name,
            as_dict=True,
        )
        if not locked:
            # Unknown/missing intent -> error (caller decides HTTP code).
            frappe.db.commit()
            return {"status": "error", "message": f"intent {intent_name} not found"}
        row = locked[0]

        if row.status == "Paid":
            frappe.db.commit()
            return {"status": "skipped", "message": "already processed"}

        if status != "paid":
            new_status = {"failed": "Failed", "expired": "Expired", "canceled": "Failed"}.get(
                status, row.status
            )
            frappe.db.set_value("Payment Plan Payment", intent_name, "status", new_status)
            frappe.db.commit()
            return {"status": "skipped", "message": f"payment status {status}"}

        # Double-payment guard: a SECOND intent for the same installment (both paid).
        installment_status = frappe.db.get_value(
            "Payment Plan Installment",
            {"parent": row.payment_plan, "installment_number": row.installment_number},
            "status",
        )
        if installment_status == "Paid":
            frappe.log_error(
                f"Duplicate payment-plan installment payment: intent {intent_name} for installment "
                f"{row.installment_number} of {row.payment_plan}, already Paid. A real payment "
                f"({payment_reference}) was taken -> MANUAL REFUND REVIEW NEEDED.",
                "Payment Plan Payment Double Payment",
            )
            frappe.db.set_value(
                "Payment Plan Payment",
                intent_name,
                {"status": "Paid", "paid": 1, "payment_id": row.payment_id or payment_reference},
            )
            frappe.db.commit()
            return {"status": "skipped", "message": "installment already paid"}

        # Confirmed paid: finalize FIRST, mark the intent Paid only AFTER it returns.
        # Security: webhook context; the gateway webhook must run as a user holding
        # the FINANCIAL tier (process_payment is @high_security_api(FINANCIAL);
        # defaults to Administrator via the webhook user).
        plan = frappe.get_doc("Payment Plan", row.payment_plan)
        plan.process_payment(
            installment_number=row.installment_number,
            payment_amount=row.amount,
            payment_reference=payment_reference,
            payment_date=today(),
        )
        frappe.db.set_value(
            "Payment Plan Payment",
            intent_name,
            {"status": "Paid", "paid": 1, "payment_id": row.payment_id or payment_reference},
        )
        frappe.db.commit()
        return {"status": "success", "intent": intent_name}

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(
            f"Payment plan payment finalize failed for intent {intent_name}: {e}",
            "Payment Plan Payment Webhook",
        )
        return {"status": "error", "message": str(e)}
```

(This is the Phase-1 handler body verbatim, with the Mollie-payment `status` argument now passed in rather than read from a Mollie object.)

- [ ] **Step 2: Make the Mollie handler delegate (keep its Mollie input adapter)**

In `verenigingen/verenigingen_payments/mollie/services/payment_plan_payment_handler.py`, keep `_payment_status`/`_metadata`, and replace the body of `handle_payment_plan_payment` so it maps the Mollie status and delegates:

```python
def handle_payment_plan_payment(payment_id: str, payment) -> dict:
    """Finalize a payment-plan installment from a confirmed Mollie webhook.

    Thin adapter: read the Mollie payment's status/metadata, then delegate to the
    gateway-agnostic finalizer.
    """
    from verenigingen.verenigingen_payments.services.payment_plan_finalization import (
        finalize_payment_plan_installment,
    )

    intent_name = _metadata(payment).get("reference_docname")
    if not intent_name:
        return {"status": "error", "message": "no reference_docname in metadata"}
    mollie_status = _payment_status(payment)  # "paid" / "failed" / "expired" / ...
    return finalize_payment_plan_installment(intent_name, payment_reference=payment_id, status=mollie_status)
```

Delete the old inline finalization body from this file (it now lives in the shared module). Keep `_payment_status`/`_metadata`.

- [ ] **Step 3: Write the finalizer test**

Create `verenigingen/tests/payment/test_payment_plan_finalization.py` — mirror `verenigingen/tests/payment/test_payment_plan_payment_webhook.py`'s fixtures (member, plan, `_create_intent`), calling `finalize_payment_plan_installment` directly:

```python
# Copyright (c) 2026, Verenigingen
"""Gateway-agnostic installment finalizer (shared by Mollie + Pay.nl)."""

import frappe
from frappe.utils import today

from verenigingen.tests.utils.base import VereningingenTestCase


class TestPaymentPlanFinalization(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.member = self._create_member()
        self.plan = self._create_plan(self.member.name)

    def _create_member(self):
        m = frappe.new_doc("Member")
        m.first_name = "Fin"
        m.last_name = "Member"
        m.email = f"fin-{frappe.generate_hash(length=6)}@example.com"
        m.member_since = today()
        m.save(ignore_permissions=True)
        self.track_doc("Member", m.name)
        return m

    def _create_plan(self, member_name):
        p = frappe.new_doc("Payment Plan")
        p.member = member_name
        p.plan_type = "Equal Installments"
        p.total_amount = 120.0
        p.number_of_installments = 3
        p.frequency = "Monthly"
        p.start_date = today()
        p.status = "Active"
        p.reason = "test"
        p.payment_method = "Bank Transfer"
        p.save(ignore_permissions=True)
        self.track_doc("Payment Plan", p.name)
        return p

    def _create_intent(self, installment_number=1, amount=40.0, payment_id="ref_1"):
        intent = frappe.get_doc(
            {"doctype": "Payment Plan Payment", "payment_plan": self.plan.name,
             "installment_number": installment_number, "amount": amount, "currency": "EUR",
             "member": self.member.name, "gateway": "Pay.nl", "status": "Pending",
             "payment_id": payment_id}
        ).insert(ignore_permissions=True)
        self.track_doc("Payment Plan Payment", intent.name)
        return intent

    def test_paid_finalizes_installment_and_intent(self):
        from verenigingen.verenigingen_payments.services.payment_plan_finalization import (
            finalize_payment_plan_installment,
        )

        intent = self._create_intent(payment_id="ref_paid")
        result = finalize_payment_plan_installment(intent.name, payment_reference="ref_paid", status="paid")
        self.assertEqual(result["status"], "success")
        intent.reload()
        self.assertEqual(intent.status, "Paid")
        plan = frappe.get_doc("Payment Plan", self.plan.name)
        self.assertEqual(plan.installments[0].status, "Paid")

    def test_duplicate_is_skipped(self):
        from verenigingen.verenigingen_payments.services.payment_plan_finalization import (
            finalize_payment_plan_installment,
        )

        intent = self._create_intent(payment_id="ref_dup")
        finalize_payment_plan_installment(intent.name, payment_reference="ref_dup", status="paid")
        result = finalize_payment_plan_installment(intent.name, payment_reference="ref_dup", status="paid")
        self.assertEqual(result["status"], "skipped")

    def test_failed_leaves_installment_payable(self):
        from verenigingen.verenigingen_payments.services.payment_plan_finalization import (
            finalize_payment_plan_installment,
        )

        intent = self._create_intent(payment_id="ref_fail")
        result = finalize_payment_plan_installment(intent.name, payment_reference="ref_fail", status="failed")
        self.assertEqual(result["status"], "skipped")
        intent.reload()
        self.assertEqual(intent.status, "Failed")
        plan = frappe.get_doc("Payment Plan", self.plan.name)
        self.assertEqual(plan.installments[0].status, "Pending")
```

- [ ] **Step 2/3 run order — RED then GREEN**

Run: `cd ~/frappe-bench && bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.payment.test_payment_plan_finalization`
Expected: PASS (3 tests).

- [ ] **Step 4: Regression — Phase-1 Mollie webhook tests still green**

Run: `cd ~/frappe-bench && bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.payment.test_payment_plan_payment_webhook`
Expected: PASS (5 tests — the Mollie handler now delegates, behavior unchanged).

- [ ] **Step 5: Lint and commit**

```bash
cd ~/frappe-bench/apps/verenigingen
black verenigingen/verenigingen_payments/services/payment_plan_finalization.py verenigingen/verenigingen_payments/mollie/services/payment_plan_payment_handler.py verenigingen/tests/payment/test_payment_plan_finalization.py
ruff check verenigingen/verenigingen_payments/services/payment_plan_finalization.py verenigingen/verenigingen_payments/mollie/services/payment_plan_payment_handler.py
git add verenigingen/verenigingen_payments/services/ verenigingen/verenigingen_payments/mollie/services/payment_plan_payment_handler.py verenigingen/tests/payment/test_payment_plan_finalization.py
git commit -m "refactor(payments): extract gateway-agnostic payment-plan finalizer (A3 phase 2)"
```

---

### Task 2: Extract `create_ideal_order` core + add PPP doctype code

**Files:**
- Modify: `verenigingen/verenigingen_payments/ing_checkout/api/payment.py` (refactor `create_ideal_payment` into a thin wrapper over a new `create_ideal_order(...)` core; add `"Payment Plan Payment": "PPP"` to `DOCTYPE_CODES`)
- Test: `verenigingen/tests/payment/test_ing_create_ideal_order.py`

**Interfaces:**
- Produces: `create_ideal_order(reference_doctype: str, reference_name: str, amount: float, description: str | None = None, return_url: str | None = None) -> dict` — the un-whitelisted core that builds the Pay.nl order + `ING Checkout Transaction` and returns `{success, transaction_id, redirect_url, reference}`. `create_ideal_payment` becomes a thin `@frappe.whitelist()` + `@high_security_api(FINANCIAL)` wrapper calling it.

- [ ] **Step 1: Write the failing test**

Create `verenigingen/tests/payment/test_ing_create_ideal_order.py`. Stub the ING client at the HTTP boundary (mirror `ing_checkout/tests/` patterns — patch `create_order` on the client returned by `get_client`), enable ING settings via the test helper, and assert the reference is `PPP:<name>`:

```python
# Copyright (c) 2026, Verenigingen
"""create_ideal_order core: reference-agnostic order creation for Payment Plan Payment."""

from unittest.mock import patch

import frappe
from frappe.utils import today

from verenigingen.tests.utils.base import VereningingenTestCase


class TestINGCreateIdealOrder(VereningingenTestCase):
    def _enable_ing(self):
        s = frappe.get_single("ING Checkout Settings")
        s.enabled = 1
        s.sandbox_mode = 1
        s.service_id = "SL-0000-0000"
        s.token_code = "AT-0000-0000"
        s.api_token = "test-token"
        s.flags.ignore_validate = True
        s.save(ignore_permissions=True)

    def _intent(self):
        intent = frappe.get_doc(
            {"doctype": "Payment Plan Payment", "installment_number": 1, "amount": 40.0,
             "currency": "EUR", "status": "Pending"}
        ).insert(ignore_permissions=True, ignore_mandatory=True, ignore_links=True)
        self.track_doc("Payment Plan Payment", intent.name)
        return intent

    def test_core_creates_order_with_ppp_reference(self):
        from verenigingen.verenigingen_payments.ing_checkout.api import payment as ing_payment

        self._enable_ing()
        intent = self._intent()

        fake_response = {"id": "EX-1234-5678", "links": {"redirect": "https://pay.nl/checkout/EX-1234-5678"}}
        with patch.object(ing_payment, "get_client") as get_client:
            get_client.return_value.create_order.return_value = fake_response
            result = ing_payment.create_ideal_order(
                reference_doctype="Payment Plan Payment",
                reference_name=intent.name,
                amount=40.0,
                description="Payment plan installment",
            )
            # Reference passed to Pay.nl uses the PPP code.
            order_data = get_client.return_value.create_order.call_args[0][0]
            self.assertEqual(order_data["reference"], f"PPP:{intent.name}")

        self.assertTrue(result["success"])
        self.assertEqual(result["transaction_id"], "EX-1234-5678")
        self.assertEqual(result["redirect_url"], "https://pay.nl/checkout/EX-1234-5678")
        # An ING Checkout Transaction now references the intent.
        txn = frappe.get_all("ING Checkout Transaction",
                             filters={"transaction_id": "EX-1234-5678"},
                             fields=["reference_doctype", "reference_name"])
        self.assertEqual(txn[0].reference_doctype, "Payment Plan Payment")
        self.assertEqual(txn[0].reference_name, intent.name)
        self.track_doc("ING Checkout Transaction", frappe.db.get_value(
            "ING Checkout Transaction", {"transaction_id": "EX-1234-5678"}, "name"))
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ~/frappe-bench && bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.payment.test_ing_create_ideal_order`
Expected: FAIL — `create_ideal_order` doesn't exist.

- [ ] **Step 3: Refactor `create_ideal_payment` → thin wrapper + `create_ideal_order` core**

In `verenigingen/verenigingen_payments/ing_checkout/api/payment.py`:
1. Add `"Payment Plan Payment": "PPP"` to the `DOCTYPE_CODES` dict.
2. Move the body of `create_ideal_payment` (everything from `settings = get_ing_checkout_settings()` through the `return {...}`) into a new module-level `def create_ideal_order(reference_doctype, reference_name, amount, description=None, return_url=None) -> dict:` — keeping the `frappe.db.exists` existence check and `ref_doc.check_permission("read")` inside the core (they still run for the gateway path, which is fine — the caller is trusted). Preserve the exact order-building/transaction-creation logic.
3. `create_ideal_payment` keeps its `@frappe.whitelist()` + `@high_security_api(FINANCIAL)` decorators and becomes: validate args, then `return create_ideal_order(reference_doctype, reference_name, amount, description, return_url)`.

Keep the return shape identical (`{success, transaction_id, redirect_url, reference}`).

- [ ] **Step 4: Run to verify it passes + ING regression**

Run: `cd ~/frappe-bench && bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.payment.test_ing_create_ideal_order`
Expected: PASS.
Then the existing ING payment-API tests: `cd ~/frappe-bench && bench --site test_site_1 run-tests --app verenigingen --module verenigingen.verenigingen_payments.ing_checkout.tests.test_api`
Expected: PASS (no regression — `create_ideal_payment` behavior unchanged).

- [ ] **Step 5: Lint and commit**

```bash
cd ~/frappe-bench/apps/verenigingen
black verenigingen/verenigingen_payments/ing_checkout/api/payment.py verenigingen/tests/payment/test_ing_create_ideal_order.py
ruff check verenigingen/verenigingen_payments/ing_checkout/api/payment.py
git add verenigingen/verenigingen_payments/ing_checkout/api/payment.py verenigingen/tests/payment/test_ing_create_ideal_order.py
git commit -m "refactor(ing): extract create_ideal_order core + add PPP doctype code (A3 phase 2)"
```

---

### Task 3: `INGCheckoutGateway` + `PaymentHook` method wiring

**Files:**
- Modify: `verenigingen/verenigingen_payments/utils/payment_gateways.py` (add `INGCheckoutGateway`, register in `PaymentGatewayFactory._gateways`)
- Modify: `verenigingen/verenigingen_payments/hooks/payment_hook.py` (add `ing_ideal` method id, `_METHOD_TO_GATEWAY` entry, guarded availability branch in `get_available_methods`)
- Test: `verenigingen/tests/payment/test_payment_hook_ing.py`

**Interfaces:**
- Consumes: `create_ideal_order` (Task 2).
- Produces: `PaymentHook.get_available_methods()` includes `{"id": "ing_ideal", ...}` when ING enabled; `PaymentHook.initiate_payment(method="ing_ideal", reference_doctype, reference_name, amount, payer_info, description)` returns the normalized redirect (`{success, action: "redirect", data: {url}, payment_id}`).

- [ ] **Step 1: Write the failing tests**

Create `verenigingen/tests/payment/test_payment_hook_ing.py`:

```python
# Copyright (c) 2026, Verenigingen
"""ING Checkout wired into PaymentHook (ing_ideal method)."""

from unittest.mock import patch

import frappe

from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.hooks.payment_hook import PaymentHook


class TestPaymentHookING(FrappeTestCase):
    def test_ing_ideal_listed_when_enabled(self):
        with patch(
            "verenigingen.verenigingen_payments.hooks.payment_hook.PaymentHook._get_ing_config",
            return_value={"available": True},
        ):
            methods = PaymentHook.get_available_methods()
        self.assertTrue(any(m["id"] == "ing_ideal" for m in methods))

    def test_ing_ideal_absent_when_disabled(self):
        with patch(
            "verenigingen.verenigingen_payments.hooks.payment_hook.PaymentHook._get_ing_config",
            return_value={"available": False},
        ):
            methods = PaymentHook.get_available_methods()
        self.assertFalse(any(m["id"] == "ing_ideal" for m in methods))

    def test_initiate_ing_ideal_normalizes_redirect(self):
        methods = [{"id": "ing_ideal", "label": "iDEAL via ING/Pay.nl"}]
        with patch.object(PaymentHook, "get_available_methods", return_value=methods), patch(
            "verenigingen.verenigingen_payments.hooks.payment_hook.frappe.get_doc",
            return_value=frappe._dict(doctype="Payment Plan Payment", name="PPP-x"),
        ), patch(
            "verenigingen.verenigingen_payments.ing_checkout.api.payment.create_ideal_order",
            return_value={"success": True, "transaction_id": "EX-1", "redirect_url": "https://pay.nl/x"},
        ):
            result = PaymentHook.initiate_payment(
                method="ing_ideal", amount=40.0,
                reference_doctype="Payment Plan Payment", reference_name="PPP-x",
                payer_info={"email": "a@b.nl", "name": "A B"}, description="Payment plan installment",
            )
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "redirect")
        self.assertEqual(result["data"]["url"], "https://pay.nl/x")
        self.assertEqual(result["payment_id"], "EX-1")
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ~/frappe-bench && bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.payment.test_payment_hook_ing`
Expected: FAIL — no `ing_ideal` method / no `_get_ing_config` / no gateway.

- [ ] **Step 3: Add `INGCheckoutGateway`**

In `verenigingen/verenigingen_payments/utils/payment_gateways.py`, add a gateway class (near the others) and register it:

```python
class INGCheckoutGateway(PaymentGateway):
    """Pay.nl (iDEAL) via ING Checkout, exposed through PaymentHook."""

    def process_payment(self, ref_doc, form_data):
        from verenigingen.verenigingen_payments.ing_checkout.api.payment import create_ideal_order

        amount = form_data.get("amount") or getattr(ref_doc, "amount", None)
        result = create_ideal_order(
            reference_doctype=ref_doc.doctype,
            reference_name=ref_doc.name,
            amount=amount,
            description=form_data.get("description_override"),
        )
        # Normalize to the shared "redirect_required" shape (PaymentHook._normalize_gateway_response
        # emits data.url from payment_url).
        return {
            "status": "redirect_required",
            "payment_url": result.get("redirect_url"),
            "payment_id": result.get("transaction_id"),
        }

    def handle_webhook(self, payload):
        # ING owns its webhook route (ing_checkout/api/webhook.py); not used here.
        return {"status": "not_applicable"}

    def get_payment_status(self, payment_id):
        return {"status": "delegated"}
```

Register in `PaymentGatewayFactory._gateways`: add `"ING Checkout": INGCheckoutGateway,`.

- [ ] **Step 4: Wire the method into `PaymentHook`**

In `verenigingen/verenigingen_payments/hooks/payment_hook.py`:
1. Add class constant `ING_IDEAL = "ing_ideal"` alongside `MOLLIE`/etc., and `ING_IDEAL: "ING Checkout"` to `_METHOD_TO_GATEWAY`.
2. Add a private config helper mirroring `_get_mollie_config`:

```python
    @classmethod
    def _get_ing_config(cls) -> dict:
        try:
            from verenigingen.verenigingen_payments.doctype.ing_checkout_settings.ing_checkout_settings import (
                is_ing_checkout_enabled,
            )

            return {"available": bool(is_ing_checkout_enabled().get("enabled"))}
        except Exception:
            return {"available": False}
```

3. In `get_available_methods`, after the Mollie branch, add a guarded ING branch (skip when `context.get("recurring")` — iDEAL one-off is not recurring):

```python
        ing_config = cls._get_ing_config()
        if ing_config.get("available") and not context.get("recurring"):
            methods.append(
                {
                    "id": cls.ING_IDEAL,
                    "label": _("iDEAL via ING/Pay.nl"),
                    "description": _("Pay by iDEAL through ING/Pay.nl"),
                    "supports_recurring": False,
                    "type": PaymentAction.REDIRECT,
                }
            )
```

- [ ] **Step 5: Run to verify pass + PaymentHook regression**

Run: `cd ~/frappe-bench && bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.payment.test_payment_hook_ing`
Expected: PASS (3).
Then: `cd ~/frappe-bench && bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.payment.test_payment_hook`
Expected: PASS (no regression).

- [ ] **Step 6: Lint and commit**

```bash
cd ~/frappe-bench/apps/verenigingen
black verenigingen/verenigingen_payments/utils/payment_gateways.py verenigingen/verenigingen_payments/hooks/payment_hook.py verenigingen/tests/payment/test_payment_hook_ing.py
ruff check verenigingen/verenigingen_payments/utils/payment_gateways.py verenigingen/verenigingen_payments/hooks/payment_hook.py
git add verenigingen/verenigingen_payments/utils/payment_gateways.py verenigingen/verenigingen_payments/hooks/payment_hook.py verenigingen/tests/payment/test_payment_hook_ing.py
git commit -m "feat(payments): wire ING Checkout (Pay.nl iDEAL) into PaymentHook (A3 phase 2)"
```

---

### Task 4: ING webhook dispatch → shared finalizer (the critical path)

**Files:**
- Modify: `verenigingen/verenigingen_payments/ing_checkout/api/webhook.py` (`_parse_reference` DOCTYPE_MAP; top-of-`handle_payment` dispatch)
- Test: `verenigingen/tests/payment/test_ing_payment_plan_webhook.py`

**Interfaces:**
- Consumes: `finalize_payment_plan_installment` (Task 1); `_parse_reference` (this file); `authenticate_webhook` (`ing_checkout/utils/webhook_security.py`).
- Produces: a paid Pay.nl webhook for a `Payment Plan Payment` reference finalizes the installment; error → HTTP 500 without a Webhook Processing Log entry.

- [ ] **Step 1: Add `PPP` to `_parse_reference` DOCTYPE_MAP**

In `verenigingen/verenigingen_payments/ing_checkout/api/webhook.py`, add `"PPP": "Payment Plan Payment"` to the `DOCTYPE_MAP` inside `_parse_reference`.

- [ ] **Step 2: Write the failing tests**

Create `verenigingen/tests/payment/test_ing_payment_plan_webhook.py`. Build a payload and call the dispatch helper directly (see Step 3 for the extracted helper name `_maybe_finalize_payment_plan`), plus one test that a paid webhook finalizes end-to-end:

```python
# Copyright (c) 2026, Verenigingen
"""Pay.nl webhook -> payment-plan installment finalization."""

import frappe
from frappe.utils import today

from verenigingen.tests.utils.base import VereningingenTestCase


def _order_payload(order_id, intent_name, status_code=100):
    return {
        "id": order_id,
        "object": {
            "reference": f"PPP:{intent_name}",
            "status": {"code": status_code, "action": "PAID" if status_code == 100 else "OTHER"},
            "amount": {"value": 4000, "currency": "EUR"},
        },
    }


class TestINGPaymentPlanWebhook(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.member = self._create_member()
        self.plan = self._create_plan(self.member.name)

    def _create_member(self):
        m = frappe.new_doc("Member")
        m.first_name = "IngHook"; m.last_name = "Member"
        m.email = f"inghook-{frappe.generate_hash(length=6)}@example.com"
        m.member_since = today(); m.save(ignore_permissions=True)
        self.track_doc("Member", m.name); return m

    def _create_plan(self, member_name):
        p = frappe.new_doc("Payment Plan")
        p.member = member_name; p.plan_type = "Equal Installments"; p.total_amount = 120.0
        p.number_of_installments = 3; p.frequency = "Monthly"; p.start_date = today()
        p.status = "Active"; p.reason = "test"; p.payment_method = "Bank Transfer"
        p.save(ignore_permissions=True); self.track_doc("Payment Plan", p.name); return p

    def _create_intent(self, payment_id="EX-hook"):
        intent = frappe.get_doc(
            {"doctype": "Payment Plan Payment", "payment_plan": self.plan.name,
             "installment_number": 1, "amount": 40.0, "currency": "EUR",
             "member": self.member.name, "gateway": "Pay.nl", "status": "Pending",
             "payment_id": payment_id}
        ).insert(ignore_permissions=True)
        self.track_doc("Payment Plan Payment", intent.name); return intent

    def test_paid_webhook_finalizes_installment(self):
        from verenigingen.verenigingen_payments.ing_checkout.api.webhook import (
            _maybe_finalize_payment_plan,
        )

        intent = self._create_intent(payment_id="EX-paid")
        handled = _maybe_finalize_payment_plan("EX-paid", _order_payload("EX-paid", intent.name, 100))
        self.assertTrue(handled)  # dispatch consumed the webhook
        intent.reload()
        self.assertEqual(intent.status, "Paid")
        plan = frappe.get_doc("Payment Plan", self.plan.name)
        self.assertEqual(plan.installments[0].status, "Paid")

    def test_non_plan_reference_not_handled(self):
        from verenigingen.verenigingen_payments.ing_checkout.api.webhook import (
            _maybe_finalize_payment_plan,
        )

        payload = {"id": "EX-si", "object": {"reference": "SINV:ACC-SINV-2025-00001",
                   "status": {"code": 100}, "amount": {"value": 100, "currency": "EUR"}}}
        self.assertFalse(_maybe_finalize_payment_plan("EX-si", payload))

    def test_failed_webhook_leaves_installment_payable(self):
        from verenigingen.verenigingen_payments.ing_checkout.api.webhook import (
            _maybe_finalize_payment_plan,
        )

        intent = self._create_intent(payment_id="EX-fail")
        handled = _maybe_finalize_payment_plan("EX-fail", _order_payload("EX-fail", intent.name, -63))
        self.assertTrue(handled)
        intent.reload()
        self.assertEqual(intent.status, "Failed")
        plan = frappe.get_doc("Payment Plan", self.plan.name)
        self.assertEqual(plan.installments[0].status, "Pending")
```

- [ ] **Step 3: Run to verify fail, then implement the dispatch**

Run the test (expect FAIL — `_maybe_finalize_payment_plan` missing). Then in `verenigingen/verenigingen_payments/ing_checkout/api/webhook.py` add the helper and call it at the top of `handle_payment`, immediately AFTER `reference = order_object.get("reference")` / `log_webhook_received(...)` and BEFORE `savepoint_name = _safe_savepoint_name(...)`:

```python
def _maybe_finalize_payment_plan(order_id: str, payload: dict) -> bool:
    """If this Pay.nl order references a Payment Plan Payment, finalize the
    installment and return True (webhook consumed). Otherwise return False.

    Runs at webhook TOP LEVEL (no enclosing savepoint) so the shared finalizer's
    commit/rollback are safe.
    """
    order_object = payload.get("object", {}) or {}
    reference = order_object.get("reference", "")
    reference_doctype, reference_name = _parse_reference(reference)
    if reference_doctype != "Payment Plan Payment" or not reference_name:
        return False

    # Authenticate: process_payment is @high_security_api(FINANCIAL) and would
    # reject the Guest webhook context. Runs AFTER signature verification.
    from verenigingen.verenigingen_payments.ing_checkout.utils.webhook_security import (
        authenticate_webhook,
    )

    authenticate_webhook()

    status_code = (order_object.get("status") or {}).get("code")
    gateway_status = {100: "paid", -63: "failed", -90: "failed", -64: "expired"}.get(
        status_code, "pending"
    )
    if gateway_status == "pending":
        # Not final yet; ack 200 so Pay.nl doesn't hammer, do not finalize.
        return True

    from verenigingen.verenigingen_payments.services.payment_plan_finalization import (
        finalize_payment_plan_installment,
    )

    result = finalize_payment_plan_installment(
        reference_name, payment_reference=order_id, status=gateway_status
    )

    # Keep the ING Checkout Transaction status in sync for ops clarity (no PE).
    txn_name = frappe.db.get_value("ING Checkout Transaction", {"transaction_id": order_id}, "name")
    if txn_name:
        frappe.db.set_value(
            "ING Checkout Transaction", txn_name,
            "status", "Paid" if result["status"] == "success" else "Pending",
        )

    if result["status"] == "error":
        # Return 500 WITHOUT writing a Webhook Processing Log entry (an error
        # dedup row would make Pay.nl's identical retry short-circuit to 200
        # duplicate and never re-run). The finalizer already wrote an Error Log.
        frappe.local.response["http_status_code"] = 500
    return True
```

Then, in `handle_payment`, right before the savepoint block:

```python
        # Payment-plan payments finalize here, at top level, before the savepoint
        # block — the shared finalizer commits/rolls back and must not run inside
        # ING's savepoint.
        if _maybe_finalize_payment_plan(order_id, payload):
            if frappe.local.response.get("http_status_code") == 500:
                return {"status": "error", "message": "payment plan finalization failed"}
            return {"status": "success", "order_id": order_id, "handled": "payment_plan"}
```

(The early `return` skips `_process_payment_webhook` and the generic Payment Entry. On the 500 path it returns WITHOUT reaching the generic `except`/`log_webhook(status="error")`, so no dedup row is written.)

- [ ] **Step 4: Run to verify pass + ING webhook regression**

Run: `cd ~/frappe-bench && bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.payment.test_ing_payment_plan_webhook`
Expected: PASS (3).
Then the existing ING webhook tests: `cd ~/frappe-bench && bench --site test_site_1 run-tests --app verenigingen --module verenigingen.verenigingen_payments.ing_checkout.tests.test_webhook_endpoints`
Expected: PASS (Sales-Invoice/other references still route through `_process_payment_webhook` — no regression).

- [ ] **Step 5: Lint and commit**

```bash
cd ~/frappe-bench/apps/verenigingen
black verenigingen/verenigingen_payments/ing_checkout/api/webhook.py verenigingen/tests/payment/test_ing_payment_plan_webhook.py
ruff check verenigingen/verenigingen_payments/ing_checkout/api/webhook.py
git add verenigingen/verenigingen_payments/ing_checkout/api/webhook.py verenigingen/tests/payment/test_ing_payment_plan_webhook.py
git commit -m "feat(payments): finalize payment-plan installments from Pay.nl webhook (A3 phase 2)"
```

---

### Task 5: Endpoint gateway map + widen the pay-page method filter

**Files:**
- Modify: `verenigingen/api/payment_plan_management.py` (`initiate_installment_payment`: `method → gateway` map for `intent.gateway`)
- Modify: `verenigingen/templates/pages/payment_plan_pay.py` (widen the method filter from `mollie`-only to enabled online REDIRECT methods)
- Test: `verenigingen/tests/api/test_payment_plan_make_payment.py` (extend), `verenigingen/tests/backend/portal/test_page_payment_plan_pay.py` (extend)

**Interfaces:**
- Consumes: `PaymentHook.get_available_methods` (Task 3).

- [ ] **Step 1: Write the failing tests**

Add to `verenigingen/tests/api/test_payment_plan_make_payment.py` a test that `initiate_installment_payment(method="ing_ideal")` records `gateway="Pay.nl"` on the intent (stub `PaymentHook.initiate_payment` to a redirect, as the existing happy-path test does):

```python
    def test_ing_ideal_records_paynl_gateway(self):
        from verenigingen.api import payment_plan_management as m

        _captured, fake = self._spy_initiate()
        with patch.object(m.PaymentHook, "initiate_payment", side_effect=fake), self.as_user(self.member.email):
            result = m.initiate_installment_payment(plan=self.plan.name, installment_number=1, method="ing_ideal")
        self.assertTrue(result["success"], result)
        intent_name = (result.get("data") or result)["intent"]
        self.track_doc("Payment Plan Payment", intent_name)
        self.assertEqual(frappe.db.get_value("Payment Plan Payment", intent_name, "gateway"), "Pay.nl")
```

Add to `verenigingen/tests/backend/portal/test_page_payment_plan_pay.py` a test that when ING is enabled the pay-page context includes `ing_ideal` among `payment_methods` (patch `PaymentHook.get_available_methods` to return both):

```python
    def test_page_lists_enabled_online_methods(self):
        from unittest.mock import patch
        from verenigingen.templates.pages import payment_plan_pay

        both = [{"id": "mollie", "label": "Online payment"}, {"id": "ing_ideal", "label": "iDEAL via ING/Pay.nl"}]
        frappe.form_dict = frappe._dict({"plan": self.plan.name})
        with patch.object(payment_plan_pay.PaymentHook, "get_available_methods", return_value=both), \
             self.as_user(self.member.email):
            ctx = frappe._dict()
            payment_plan_pay.get_context(ctx)
        ids = {m["id"] for m in ctx.payment_methods}
        self.assertIn("ing_ideal", ids)
        self.assertIn("mollie", ids)
```

- [ ] **Step 2: Run to verify fail**

Run both modules separately; expect the two new tests to FAIL (gateway hardcoded "Mollie"; page filter is `mollie`-only).

- [ ] **Step 3: Implement**

In `verenigingen/api/payment_plan_management.py::initiate_installment_payment`, replace the hardcoded `"gateway": "Mollie"` with a map:

```python
        gateway_label = {"mollie": "Mollie", "ing_ideal": "Pay.nl"}.get(method, method)
```
and use `"gateway": gateway_label` in the intent dict.

In `verenigingen/templates/pages/payment_plan_pay.py`, change the filter from `m["id"] == "mollie"` to the set of enabled online REDIRECT methods:

```python
    ONLINE_METHODS = {"mollie", "ing_ideal"}
    context.payment_methods = [
        m for m in PaymentHook.get_available_methods() if m["id"] in ONLINE_METHODS
    ]
```

- [ ] **Step 4: Run to verify pass**

Run: `cd ~/frappe-bench && bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.api.test_payment_plan_make_payment` (expect 5/5).
Run: `cd ~/frappe-bench && bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.backend.portal.test_page_payment_plan_pay` (expect 3/3).

- [ ] **Step 5: Lint and commit**

```bash
cd ~/frappe-bench/apps/verenigingen
black verenigingen/api/payment_plan_management.py verenigingen/templates/pages/payment_plan_pay.py verenigingen/tests/api/test_payment_plan_make_payment.py verenigingen/tests/backend/portal/test_page_payment_plan_pay.py
ruff check verenigingen/api/payment_plan_management.py verenigingen/templates/pages/payment_plan_pay.py
git add verenigingen/api/payment_plan_management.py verenigingen/templates/pages/payment_plan_pay.py verenigingen/tests/api/test_payment_plan_make_payment.py verenigingen/tests/backend/portal/test_page_payment_plan_pay.py
git commit -m "feat(payments): offer Pay.nl on the pay page + record gateway on intent (A3 phase 2)"
```

---

### Task 6: Full regression + PR

- [ ] **Step 1: Run every affected/new module (each separately)**

```bash
cd ~/frappe-bench
for m in \
  verenigingen.tests.payment.test_payment_plan_finalization \
  verenigingen.tests.payment.test_payment_plan_payment_webhook \
  verenigingen.tests.payment.test_ing_create_ideal_order \
  verenigingen.tests.payment.test_payment_hook_ing \
  verenigingen.tests.payment.test_payment_hook \
  verenigingen.tests.payment.test_ing_payment_plan_webhook \
  verenigingen.tests.api.test_payment_plan_make_payment \
  verenigingen.tests.backend.portal.test_page_payment_plan_pay \
  verenigingen.verenigingen_payments.ing_checkout.tests.test_api \
  verenigingen.verenigingen_payments.ing_checkout.tests.test_webhook_endpoints ; do
  echo "=== $m ==="; bench --site test_site_1 run-tests --app verenigingen --module "$m" 2>&1 | grep -E "^Ran |^OK|^FAILED"; done
```
Expected: all OK.

- [ ] **Step 2: Push + PR**

```bash
cd ~/frappe-bench/apps/verenigingen
git push -u origin feat/payment-plan-paynl-phase2-a3
gh pr create --base develop --title "feat(payments): Make Payment via Pay.nl / iDEAL (A3 Phase 2)" --body "<summary: wires ING Checkout into PaymentHook; shared finalizer; webhook finalization at top of handle_payment with authenticated user + error->500-without-dedup-log; deployment note: ING webhook_user needs FINANCIAL tier (defaults to Administrator)>"
```

- [ ] **Step 3: Request a skeptical code review of the implementation before merge.**

## Notes for the implementer
- Do NOT branch `ING Checkout Transaction.update_from_webhook` — all payment-plan finalization happens at the top of `handle_payment` (before the savepoint), so the finalizer's commit/rollback are safe.
- The error path must NOT create a Webhook Processing Log entry (return 500 directly), else Pay.nl's retry dedupes and never re-runs.
- If `authenticate_webhook()`'s signature/args differ from a no-arg call, adapt (it must result in `frappe.set_user(<webhook_user>)`); verify the ING webhook user resolves to Administrator by default.
- **Test note:** `_maybe_finalize_payment_plan` calls `authenticate_webhook()`, which `frappe.set_user()`s the webhook user for the rest of the request. In the Task-4 tests, save/restore `frappe.session.user` in `setUp`/`tearDown` (or assert after restoring) so the user switch doesn't disturb `track_doc` cleanup or later assertions. If `authenticate_webhook()` also expects a verified signature/request context that isn't present in a direct unit call, either stub `frappe.set_user`/the webhook-user lookup for the test, or factor the `set_user` into a tiny helper the test can drive — do not skip the auth in production code.
- Keep Phase-1 Mollie tests green at every step (Task 1 is the only one that touches Mollie code).
