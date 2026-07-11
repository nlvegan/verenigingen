# Payment Plan "Make Payment" (Mollie, Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a member pay the next payable installment of an Active payment plan online via Mollie, with the installment marked Paid only after Mollie confirms payment (webhook), never by member self-assertion.

**Architecture:** A new `Payment Plan Payment` intent doctype is the reference doc handed to the existing (unchanged) `MollieGateway` — it carries the installment `amount`/`currency`/`payment_id` the gateway reads/writes. A member-facing pay page initiates payment via `PaymentHook.initiate_payment`; the Mollie webhook gains a dispatch (before donation classification) that finalizes the matching installment via the existing `PaymentPlan.process_payment()`.

**Tech Stack:** Frappe/ERPNext (Python 3.12), Mollie payments, Jinja portal pages, `frappe.tests` (real-DB tests).

**Spec:** `docs/superpowers/specs/2026-07-11-payment-plan-make-payment-mollie-design.md`

## Global Constraints

- Site for tests: `test_site_1` (NEVER `veg11`). Run tests with
  `cd ~/frappe-bench && bench --site test_site_1 run-tests --app verenigingen --module <dotted.module>`.
- New doctype lives under `verenigingen/verenigingen_payments/doctype/` and belongs to module **Verenigingen Payments**.
- `@frappe.whitelist()` MUST be the OUTERMOST decorator (above any security decorator).
- User-facing Python strings wrapped in `_()`.
- Money from the stored installment, never from client input.
- `process_payment()` is called ONLY from the webhook after Mollie confirms `paid`.
- Any `ignore_permissions=True` needs a `# Security:` comment justifying it.
- Black line length 110; run `black` + `ruff` before each commit. Prettier for JS/`.vue` only (not `.html`).
- Payable installment = status `Pending` OR `Overdue` (never `Paid`).

---

### Task 1: `Payment Plan Payment` intent doctype

**Files:**
- Create: `verenigingen/verenigingen_payments/doctype/payment_plan_payment/__init__.py`
- Create: `verenigingen/verenigingen_payments/doctype/payment_plan_payment/payment_plan_payment.json`
- Create: `verenigingen/verenigingen_payments/doctype/payment_plan_payment/payment_plan_payment.py`
- Test: `verenigingen/verenigingen_payments/doctype/payment_plan_payment/test_payment_plan_payment.py`

**Interfaces:**
- Produces: DocType `Payment Plan Payment` with fields `payment_plan` (Link→Payment Plan), `installment_number` (Int), `amount` (Currency), `currency` (Data), `member` (Link→Member), `payment_id` (Data), `paid` (Check), `status` (Select: Pending/Paid/Failed/Expired), `gateway` (Data). Controller class `PaymentPlanPayment(Document)`.

- [ ] **Step 1: Create the module `__init__.py`**

Create `verenigingen/verenigingen_payments/doctype/payment_plan_payment/__init__.py` (empty file).

- [ ] **Step 2: Create the DocType JSON**

Create `verenigingen/verenigingen_payments/doctype/payment_plan_payment/payment_plan_payment.json`:

```json
{
 "actions": [],
 "allow_rename": 0,
 "autoname": "hash",
 "creation": "2026-07-11 00:00:00.000000",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": [
  "payment_plan",
  "installment_number",
  "member",
  "column_break_1",
  "amount",
  "currency",
  "gateway",
  "section_break_1",
  "status",
  "paid",
  "payment_id"
 ],
 "fields": [
  {"fieldname": "payment_plan", "fieldtype": "Link", "label": "Payment Plan", "options": "Payment Plan", "reqd": 1, "in_list_view": 1},
  {"fieldname": "installment_number", "fieldtype": "Int", "label": "Installment Number", "reqd": 1, "in_list_view": 1},
  {"fieldname": "member", "fieldtype": "Link", "label": "Member", "options": "Member"},
  {"fieldname": "column_break_1", "fieldtype": "Column Break"},
  {"fieldname": "amount", "fieldtype": "Currency", "label": "Amount", "reqd": 1, "in_list_view": 1},
  {"fieldname": "currency", "fieldtype": "Data", "label": "Currency", "default": "EUR"},
  {"fieldname": "gateway", "fieldtype": "Data", "label": "Gateway"},
  {"fieldname": "section_break_1", "fieldtype": "Section Break"},
  {"fieldname": "status", "fieldtype": "Select", "label": "Status", "options": "Pending\nPaid\nFailed\nExpired", "default": "Pending", "in_list_view": 1},
  {"fieldname": "paid", "fieldtype": "Check", "label": "Paid", "default": "0"},
  {"fieldname": "payment_id", "fieldtype": "Data", "label": "Payment ID", "read_only": 1}
 ],
 "index_web_pages_for_search": 1,
 "links": [],
 "modified": "2026-07-11 00:00:00.000000",
 "modified_by": "Administrator",
 "module": "Verenigingen Payments",
 "name": "Payment Plan Payment",
 "owner": "Administrator",
 "permissions": [
  {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1, "report": 1, "export": 1},
  {"role": "Verenigingen Administrator", "read": 1, "write": 1, "create": 1, "report": 1}
 ],
 "sort_field": "modified",
 "sort_order": "DESC",
 "states": [],
 "track_changes": 1
}
```

- [ ] **Step 3: Create the controller**

Create `verenigingen/verenigingen_payments/doctype/payment_plan_payment/payment_plan_payment.py`:

```python
# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class PaymentPlanPayment(Document):
    """A single online-payment attempt for one payment-plan installment.

    Acts as the reference document handed to the payment gateway: it exposes the
    installment `amount`/`currency` the gateway reads and the `payment_id` it
    writes back, so the shared gateway is reused unchanged. The Mollie webhook
    finalizes the installment (via PaymentPlan.process_payment) and flips this
    record to Paid.
    """

    pass
```

- [ ] **Step 4: Reload the doctype**

Run: `cd ~/frappe-bench && bench --site test_site_1 reload-doctype "Payment Plan Payment"`
Expected: `Success` (creates the DB table).

- [ ] **Step 5: Write the failing test**

Create `verenigingen/verenigingen_payments/doctype/payment_plan_payment/test_payment_plan_payment.py`:

```python
# Copyright (c) 2026, Verenigingen and contributors
import frappe

from verenigingen.tests.utils.base import VereningingenTestCase


class TestPaymentPlanPayment(VereningingenTestCase):
    def test_intent_defaults_and_fields(self):
        # Shape guard only: skip mandatory/link validation so we don't need a real
        # plan (payment_plan is reqd; ignore_mandatory bypasses it for this check).
        intent = frappe.new_doc("Payment Plan Payment")
        intent.installment_number = 1
        intent.amount = 40.0
        intent.insert(ignore_permissions=True, ignore_mandatory=True, ignore_links=True)
        self.track_doc("Payment Plan Payment", intent.name)

        intent.reload()
        self.assertEqual(intent.status, "Pending")
        self.assertEqual(intent.currency, "EUR")
        self.assertEqual(intent.paid, 0)
        self.assertEqual(intent.amount, 40.0)

    def test_status_transition_to_paid(self):
        intent = frappe.new_doc("Payment Plan Payment")
        intent.installment_number = 1
        intent.amount = 25.0
        intent.insert(ignore_permissions=True, ignore_mandatory=True, ignore_links=True)
        self.track_doc("Payment Plan Payment", intent.name)

        intent.status = "Paid"
        intent.paid = 1
        intent.payment_id = "tr_test123"
        intent.save(ignore_permissions=True)
        intent.reload()
        self.assertEqual(intent.status, "Paid")
        self.assertEqual(intent.payment_id, "tr_test123")
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd ~/frappe-bench && bench --site test_site_1 run-tests --app verenigingen --module verenigingen.verenigingen_payments.doctype.payment_plan_payment.test_payment_plan_payment`
Expected: PASS (2 tests). (The doctype table exists from Step 4, so these pass immediately — this task is scaffolding + a shape guard.)

- [ ] **Step 7: Lint and commit**

```bash
cd ~/frappe-bench/apps/verenigingen
black verenigingen/verenigingen_payments/doctype/payment_plan_payment/
ruff check verenigingen/verenigingen_payments/doctype/payment_plan_payment/
git add verenigingen/verenigingen_payments/doctype/payment_plan_payment/
git commit -m "feat(payments): add Payment Plan Payment intent doctype (A3)"
```

---

### Task 2: Thread a `description` through `PaymentHook.initiate_payment`

**Files:**
- Modify: `verenigingen/verenigingen_payments/hooks/payment_hook.py` (`initiate_payment`, signature ~`:176-187`, form_data build ~`:277-289`)
- Test: `verenigingen/tests/payment/test_payment_hook_description.py`

**Interfaces:**
- Consumes: existing `PaymentHook.initiate_payment`.
- Produces: `PaymentHook.initiate_payment(..., description: str | None = None)` that sets `form_data["description_override"] = description` (which `MollieGateway.process_payment` already honors at `payment_gateways.py:171`).

- [ ] **Step 1: Write the failing test**

Create `verenigingen/tests/payment/test_payment_hook_description.py`:

```python
# Copyright (c) 2026, Verenigingen
"""initiate_payment must forward `description` to the gateway as description_override."""

from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.hooks.payment_hook import PaymentHook


class _SpyGateway:
    """Captures the form_data handed to the gateway."""

    def __init__(self):
        self.captured = None

    def process_payment(self, ref_doc, form_data):
        self.captured = form_data
        return {"status": "redirect_required", "redirect_url": "https://x", "payment_id": "tr_1"}


class TestInitiatePaymentDescription(FrappeTestCase):
    def test_description_forwarded_as_description_override(self):
        spy = _SpyGateway()
        methods = [{"id": "mollie", "label": "Online Payment"}]
        with patch.object(PaymentHook, "get_available_methods", return_value=methods), patch(
            "verenigingen.verenigingen_payments.hooks.payment_hook.PaymentGatewayFactory.get_gateway",
            return_value=spy,
        ), patch(
            "verenigingen.verenigingen_payments.hooks.payment_hook.frappe.get_doc",
            return_value=object(),
        ):
            PaymentHook.initiate_payment(
                method="mollie",
                amount=40.0,
                reference_doctype="Payment Plan Payment",
                reference_name="PPP-x",
                payer_info={"email": "a@b.nl", "name": "A B"},
                description="Payment plan PP-1 installment 2",
            )
        self.assertIsNotNone(spy.captured, "gateway was not called")
        self.assertEqual(spy.captured.get("description_override"), "Payment plan PP-1 installment 2")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/frappe-bench && bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.payment.test_payment_hook_description`
Expected: FAIL — `initiate_payment()` got an unexpected keyword argument `description`.

- [ ] **Step 3: Add the parameter and forward it**

In `verenigingen/verenigingen_payments/hooks/payment_hook.py`, add the param to the `initiate_payment` signature (after `interval`):

```python
    def initiate_payment(
        cls,
        method: str,
        amount: float,
        reference_doctype: str,
        reference_name: str,
        payer_info: dict,
        redirect_urls: dict | None = None,
        recurring: bool = False,
        interval: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
```

Then in the `form_data` dict (the `frappe._dict({...})` block ~`:277-289`), add one key:

```python
                    "redirect_url": redirect_urls.get("success") if redirect_urls else None,
                    "cancel_url": redirect_urls.get("cancel") if redirect_urls else None,
                    "description_override": description,
```

(`MollieGateway.process_payment` uses `form_data.get("description_override", ...)`, so a `None` value simply falls back to the default — backward compatible.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/frappe-bench && bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.payment.test_payment_hook_description`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
cd ~/frappe-bench/apps/verenigingen
black verenigingen/verenigingen_payments/hooks/payment_hook.py verenigingen/tests/payment/test_payment_hook_description.py
ruff check verenigingen/verenigingen_payments/hooks/payment_hook.py
git add verenigingen/verenigingen_payments/hooks/payment_hook.py verenigingen/tests/payment/test_payment_hook_description.py
git commit -m "feat(payments): forward description through PaymentHook.initiate_payment (A3)"
```

---

### Task 3: `initiate_installment_payment` API + next-payable helper

**Files:**
- Modify: `verenigingen/api/payment_plan_management.py` (append two functions)
- Test: `verenigingen/tests/api/test_payment_plan_make_payment.py`

**Interfaces:**
- Consumes: `Payment Plan Payment` doctype (Task 1); `PaymentHook.initiate_payment(..., description=)` (Task 2); `get_current_user_member_name` (`verenigingen/utils/member_utils.py`).
- Produces:
  - `get_next_payable_installment(plan_doc) -> dict | None` — returns the earliest installment row (as a dict with `installment_number`, `amount`, `status`, `due_date`) whose status is `Pending` or `Overdue`, else `None`.
  - `@frappe.whitelist() initiate_installment_payment(plan: str, installment_number: int, method: str = "mollie") -> OperationResult` returning `{"redirect_url": str, "intent": str}` on success.

- [ ] **Step 1: Write the failing tests**

Create `verenigingen/tests/api/test_payment_plan_make_payment.py`:

```python
# Copyright (c) 2026, Verenigingen
"""initiate_installment_payment: ownership, payable-state, and initiation."""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.utils.base import VereningingenTestCase


class TestPaymentPlanMakePayment(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.member = self._make_member_with_user()
        self.plan = self._make_active_plan(self.member.name)

    def _make_member_with_user(self):
        email = f"ppay-{frappe.generate_hash(length=6)}@example.com"
        member = frappe.new_doc("Member")
        member.first_name = "Pay"
        member.last_name = "Member"
        member.email = email
        member.member_since = today()
        member.save(ignore_permissions=True)
        self.track_doc("Member", member.name)
        if not frappe.db.exists("User", email):
            user = frappe.get_doc(
                {"doctype": "User", "email": email, "first_name": "Pay",
                 "send_welcome_email": 0, "roles": [{"role": "Verenigingen Member"}]}
            ).insert(ignore_permissions=True)
            self.track_doc("User", user.name)
        member.db_set("user", email)
        member.db_set("email", email)
        return member

    def _make_active_plan(self, member_name):
        plan = frappe.new_doc("Payment Plan")
        plan.member = member_name
        plan.plan_type = "Equal Installments"
        plan.total_amount = 120.0
        plan.number_of_installments = 3
        plan.frequency = "Monthly"
        plan.start_date = today()
        plan.status = "Active"
        plan.reason = "test"
        plan.payment_method = "Bank Transfer"
        plan.save(ignore_permissions=True)
        self.track_doc("Payment Plan", plan.name)
        return plan

    def _spy_initiate(self):
        # Stub the gateway boundary: PaymentHook.initiate_payment returns a redirect
        # without touching Mollie. Returns the captured kwargs for assertions.
        captured = {}

        def _fake(**kwargs):
            captured.update(kwargs)
            return {"success": True, "action": "redirect", "payment_id": "tr_test",
                    "data": {}, "redirect_url": "https://mollie/checkout"}

        return captured, _fake

    def test_rejects_plan_not_owned_by_caller(self):
        from verenigingen.api.payment_plan_management import initiate_installment_payment

        other = self._make_member_with_user()
        with self.as_user(other.email):
            result = initiate_installment_payment(plan=self.plan.name, installment_number=1)
        self.assertFalse(result["success"])

    def test_rejects_paid_installment(self):
        from verenigingen.api.payment_plan_management import initiate_installment_payment

        # Mark installment 1 Paid directly.
        plan = frappe.get_doc("Payment Plan", self.plan.name)
        plan.installments[0].status = "Paid"
        plan.save(ignore_permissions=True)
        with self.as_user(self.member.email):
            result = initiate_installment_payment(plan=self.plan.name, installment_number=1)
        self.assertFalse(result["success"])

    def test_happy_path_creates_intent_and_returns_redirect(self):
        from verenigingen.api import payment_plan_management as m

        captured, fake = self._spy_initiate()
        with patch.object(m.PaymentHook, "initiate_payment", side_effect=fake), self.as_user(self.member.email):
            result = m.initiate_installment_payment(plan=self.plan.name, installment_number=1)
        self.assertTrue(result["success"], result)
        data = result.get("data") or result
        self.assertEqual(data["redirect_url"], "https://mollie/checkout")
        # Intent created for installment 1 with the installment amount.
        intent_name = data["intent"]
        self.track_doc("Payment Plan Payment", intent_name)
        intent = frappe.get_doc("Payment Plan Payment", intent_name)
        self.assertEqual(intent.installment_number, 1)
        self.assertEqual(intent.amount, 40.0)  # 120 / 3
        self.assertEqual(intent.status, "Pending")
        # description threaded (not "Donation ...")
        self.assertIn("Payment plan", captured["description"])
        self.assertNotIn("Donation", captured["description"])

    def test_overdue_installment_is_payable(self):
        from verenigingen.api import payment_plan_management as m

        plan = frappe.get_doc("Payment Plan", self.plan.name)
        plan.installments[0].status = "Overdue"
        plan.installments[0].due_date = add_days(today(), -10)
        plan.save(ignore_permissions=True)

        _captured, fake = self._spy_initiate()
        with patch.object(m.PaymentHook, "initiate_payment", side_effect=fake), self.as_user(self.member.email):
            result = m.initiate_installment_payment(plan=self.plan.name, installment_number=1)
        self.assertTrue(result["success"], result)
        self.track_doc("Payment Plan Payment", (result.get("data") or result)["intent"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/frappe-bench && bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.api.test_payment_plan_make_payment`
Expected: FAIL — `cannot import name 'initiate_installment_payment'`.

- [ ] **Step 3: Implement the helper and endpoint**

Append to `verenigingen/api/payment_plan_management.py` (note the existing imports of `frappe`, `_`, `OperationResult`, and the security decorators at the top of that file; add `from verenigingen.verenigingen_payments.hooks.payment_hook import PaymentHook` and `from verenigingen.utils.member_utils import get_current_user_member_name` if not already imported):

```python
PAYABLE_INSTALLMENT_STATUSES = ("Pending", "Overdue")


def get_next_payable_installment(plan_doc):
    """Return the earliest Pending/Overdue installment (dict) or None."""
    payable = [
        i for i in plan_doc.installments if i.status in PAYABLE_INSTALLMENT_STATUSES
    ]
    if not payable:
        return None
    nxt = min(payable, key=lambda i: (i.due_date or plan_doc.start_date, i.installment_number))
    return {
        "installment_number": nxt.installment_number,
        "amount": nxt.amount,
        "status": nxt.status,
        "due_date": nxt.due_date,
    }


@frappe.whitelist()
@self_service_api(operation_type=OperationType.FINANCIAL, implicit_allowed=True)
def initiate_installment_payment(plan, installment_number, method="mollie") -> OperationResult:
    """Start an online payment for one payment-plan installment.

    Validates the plan belongs to the current member and the installment is
    payable (Pending/Overdue), creates a Payment Plan Payment intent for the
    server-derived installment amount, and initiates the gateway payment,
    returning the redirect URL. Never marks anything Paid — that happens only on
    the confirmed webhook.
    """
    try:
        installment_number = int(installment_number)
        plan_doc = frappe.get_doc("Payment Plan", plan)

        # Ownership: the plan's member must map to the current user.
        member_name = get_current_user_member_name()
        if not member_name or plan_doc.member != member_name:
            return OperationResult.fail(message=_("You can only pay your own payment plans"))

        if plan_doc.status != "Active":
            return OperationResult.fail(message=_("This payment plan is not active"))

        installment = next(
            (i for i in plan_doc.installments if i.installment_number == installment_number), None
        )
        if not installment:
            return OperationResult.fail(message=_("Installment not found"))
        if installment.status not in PAYABLE_INSTALLMENT_STATUSES:
            return OperationResult.fail(message=_("This installment is not payable"))

        # Amount is server-derived from the stored installment.
        amount = flt(installment.amount)

        intent = frappe.get_doc(
            {
                "doctype": "Payment Plan Payment",
                "payment_plan": plan_doc.name,
                "installment_number": installment_number,
                "amount": amount,
                "currency": "EUR",
                "member": member_name,
                "gateway": "Mollie",
                "status": "Pending",
            }
        )
        # Security: intent is scoped to the caller's own plan (ownership checked
        # above); created on their behalf so the gateway has a reference doc.
        intent.insert(ignore_permissions=True)

        member_doc = frappe.get_doc("Member", member_name)
        result = PaymentHook.initiate_payment(
            method=method,
            amount=amount,
            reference_doctype="Payment Plan Payment",
            reference_name=intent.name,
            payer_info={"email": member_doc.email, "name": member_doc.full_name},
            description=_("Payment plan {0} installment {1}").format(plan_doc.name, installment_number),
        )

        if not result.get("success"):
            intent.db_set("status", "Failed")
            return OperationResult.fail(message=result.get("message") or _("Payment could not be started"))

        redirect_url = result.get("redirect_url") or (result.get("data") or {}).get("redirect_url")
        return OperationResult.ok(
            {"redirect_url": redirect_url, "intent": intent.name},
            message=_("Payment started"),
        )

    except Exception as e:
        frappe.log_error(
            f"initiate_installment_payment failed for {plan}/{installment_number}: {e}",
            "Payment Plan Payment",
        )
        return OperationResult.from_exception(e, message=_("Failed to start payment"))
```

Confirm the file already imports `flt` (it uses it elsewhere); if not, add `from frappe.utils import flt`. `self_service_api` / `OperationType` are already imported at the top of this module (used by `request_payment_plan`/`get_member_payment_plans`) — reuse the SAME decorator as those member-facing siblings; do NOT use `@critical_api` (its tier would reject a plain member, locking out exactly the users who need to pay).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/frappe-bench && bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.api.test_payment_plan_make_payment`
Expected: PASS (4 tests).

- [ ] **Step 5: Lint and commit**

```bash
cd ~/frappe-bench/apps/verenigingen
black verenigingen/api/payment_plan_management.py verenigingen/tests/api/test_payment_plan_make_payment.py
ruff check verenigingen/api/payment_plan_management.py
git add verenigingen/api/payment_plan_management.py verenigingen/tests/api/test_payment_plan_make_payment.py
git commit -m "feat(payments): initiate_installment_payment endpoint + next-payable helper (A3)"
```

---

### Task 4: Webhook confirmation handler + dispatch

**Files:**
- Create: `verenigingen/verenigingen_payments/mollie/services/payment_plan_payment_handler.py`
- Modify: `verenigingen/verenigingen_payments/mollie/services/webhook_wrapper_service_unified.py` (`process_payment_webhook`, insert after the `payment = router.fetch_payment(payment_id)` line ~`:368`, before `classify_payment` ~`:369`)
- Test: `verenigingen/tests/payment/test_payment_plan_payment_webhook.py`

**Interfaces:**
- Consumes: `Payment Plan Payment` doctype (Task 1); `PaymentPlan.process_payment(installment_number, payment_amount, payment_reference, payment_date)`.
- Produces: `handle_payment_plan_payment(payment_id: str, payment) -> dict` — finalizes the installment for a paid intent (idempotent, row-locked), returns `{"status": "success"|"skipped"|"error", ...}`.

- [ ] **Step 1: Write the failing tests**

Create `verenigingen/tests/payment/test_payment_plan_payment_webhook.py`:

```python
# Copyright (c) 2026, Verenigingen
"""Webhook confirmation for payment-plan installment payments."""

import frappe
from frappe.utils import today

from verenigingen.tests.utils.base import VereningingenTestCase


def _payment(payment_id, intent_name, status="paid"):
    """A minimal Mollie-payment-like dict as the router.fetch_payment would return."""
    return {
        "id": payment_id,
        "status": status,
        "metadata": {"reference_doctype": "Payment Plan Payment", "reference_docname": intent_name},
    }


class TestPaymentPlanPaymentWebhook(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.member = self._member()
        self.plan = self._plan(self.member.name)

    def _member(self):
        m = frappe.new_doc("Member")
        m.first_name = "Hook"
        m.last_name = "Member"
        m.email = f"hook-{frappe.generate_hash(length=6)}@example.com"
        m.member_since = today()
        m.save(ignore_permissions=True)
        self.track_doc("Member", m.name)
        return m

    def _plan(self, member_name):
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

    def _intent(self, installment_number=1, amount=40.0, payment_id="tr_hook1"):
        intent = frappe.get_doc(
            {"doctype": "Payment Plan Payment", "payment_plan": self.plan.name,
             "installment_number": installment_number, "amount": amount, "currency": "EUR",
             "member": self.member.name, "gateway": "Mollie", "status": "Pending",
             "payment_id": payment_id}
        ).insert(ignore_permissions=True)
        self.track_doc("Payment Plan Payment", intent.name)
        return intent

    def test_paid_webhook_marks_installment_and_intent_paid(self):
        from verenigingen.verenigingen_payments.mollie.services.payment_plan_payment_handler import (
            handle_payment_plan_payment,
        )

        intent = self._intent()
        result = handle_payment_plan_payment("tr_hook1", _payment("tr_hook1", intent.name))
        self.assertEqual(result["status"], "success")

        intent.reload()
        self.assertEqual(intent.status, "Paid")
        self.assertEqual(intent.paid, 1)

        plan = frappe.get_doc("Payment Plan", self.plan.name)
        self.assertEqual(plan.installments[0].status, "Paid")
        self.assertEqual(plan.installments[0].payment_reference, "tr_hook1")

    def test_duplicate_paid_webhook_is_idempotent_noop(self):
        from verenigingen.verenigingen_payments.mollie.services.payment_plan_payment_handler import (
            handle_payment_plan_payment,
        )

        intent = self._intent()
        handle_payment_plan_payment("tr_hook1", _payment("tr_hook1", intent.name))
        # Second delivery must not raise and must not re-run process_payment.
        result = handle_payment_plan_payment("tr_hook1", _payment("tr_hook1", intent.name))
        self.assertIn(result["status"], ("success", "skipped"))
        plan = frappe.get_doc("Payment Plan", self.plan.name)
        # Still exactly one Paid installment (no double processing / no throw).
        self.assertEqual(plan.installments[0].status, "Paid")

    def test_failed_webhook_marks_intent_failed_installment_stays_payable(self):
        from verenigingen.verenigingen_payments.mollie.services.payment_plan_payment_handler import (
            handle_payment_plan_payment,
        )

        intent = self._intent()
        result = handle_payment_plan_payment("tr_hook1", _payment("tr_hook1", intent.name, status="failed"))
        self.assertEqual(result["status"], "skipped")
        intent.reload()
        self.assertEqual(intent.status, "Failed")
        plan = frappe.get_doc("Payment Plan", self.plan.name)
        self.assertEqual(plan.installments[0].status, "Pending")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/frappe-bench && bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.payment.test_payment_plan_payment_webhook`
Expected: FAIL — module `payment_plan_payment_handler` does not exist.

- [ ] **Step 3: Implement the handler**

Create `verenigingen/verenigingen_payments/mollie/services/payment_plan_payment_handler.py`:

```python
# Copyright (c) 2026, Verenigingen
"""Finalize a payment-plan installment payment from a confirmed Mollie webhook.

Invoked from the unified webhook dispatch when a Mollie payment's metadata
reference_doctype is "Payment Plan Payment". The installment is marked Paid via
the existing PaymentPlan.process_payment ONLY here (never on a member-triggered
path), so a member cannot self-certify payment.
"""

import frappe
from frappe.utils import today


def _payment_status(payment) -> str:
    if isinstance(payment, dict):
        return payment.get("status") or ""
    return getattr(payment, "status", "") or ""


def _metadata(payment) -> dict:
    if isinstance(payment, dict):
        md = payment.get("metadata")
    else:
        md = getattr(payment, "metadata", None)
    return md if isinstance(md, dict) else {}


def handle_payment_plan_payment(payment_id: str, payment) -> dict:
    """Idempotently finalize the installment for a Payment Plan Payment intent."""
    intent_name = _metadata(payment).get("reference_docname")
    if not intent_name or not frappe.db.exists("Payment Plan Payment", intent_name):
        # Nothing we can do; do not 500 (Mollie would retry forever).
        return {"status": "error", "message": f"intent {intent_name} not found"}

    status = _payment_status(payment)

    try:
        # Serialize concurrent duplicate deliveries on this intent.
        frappe.db.sql(
            "SELECT name FROM `tabPayment Plan Payment` WHERE name=%s FOR UPDATE", intent_name
        )
        intent = frappe.get_doc("Payment Plan Payment", intent_name)

        # Idempotency guard: already finalized -> success no-op (never reach
        # process_payment, which throws on an already-Paid installment).
        if intent.status == "Paid":
            frappe.db.commit()
            return {"status": "skipped", "message": "already processed"}

        if status != "paid":
            # failed / expired / open -> record and leave installment payable.
            new_status = {"failed": "Failed", "expired": "Expired", "canceled": "Failed"}.get(
                status, intent.status
            )
            intent.db_set("status", new_status)
            frappe.db.commit()
            return {"status": "skipped", "message": f"payment status {status}"}

        # Confirmed paid: finalize the installment FIRST, mark intent Paid only
        # after it returns (so a mid-finalize failure leaves the intent
        # re-processable rather than a Paid intent with an unfinalized installment).
        # Security: webhook context; finalization runs as the webhook user.
        plan = frappe.get_doc("Payment Plan", intent.payment_plan)
        plan.process_payment(
            installment_number=intent.installment_number,
            payment_amount=intent.amount,
            payment_reference=payment_id,
            payment_date=today(),
        )
        intent.db_set("status", "Paid")
        intent.db_set("paid", 1)
        if not intent.payment_id:
            intent.db_set("payment_id", payment_id)
        frappe.db.commit()
        return {"status": "success", "intent": intent_name}

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(
            f"Payment plan payment finalize failed for intent {intent_name}: {e}",
            "Payment Plan Payment Webhook",
        )
        # Return error (not raise) so the caller decides the HTTP code; a 500 here
        # would trigger Mollie retries, which is acceptable since we rolled back.
        return {"status": "error", "message": str(e)}
```

- [ ] **Step 4: Run the handler tests to verify they pass**

Run: `cd ~/frappe-bench && bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.payment.test_payment_plan_payment_webhook`
Expected: PASS (3 tests).

- [ ] **Step 5: Add the dispatch to the unified webhook (write the failing test first)**

Append this test to `verenigingen/tests/payment/test_payment_plan_payment_webhook.py`:

```python
    def test_dispatch_routes_plan_payment_before_donation_classification(self):
        from unittest.mock import Mock, patch

        from verenigingen.verenigingen_payments.mollie.services.webhook_wrapper_service_unified import (
            get_unified_webhook_service,
        )

        intent = self._intent(payment_id="tr_dispatch")
        fake = _payment("tr_dispatch", intent.name)

        with patch(
            "verenigingen.verenigingen_payments.mollie.services.webhook_wrapper_service_unified.get_payment_router"
        ) as get_router:
            router = Mock()
            router.fetch_payment.return_value = fake
            # If classification were reached it would raise, proving we dispatched first.
            router.classify_payment.side_effect = AssertionError("should not classify plan payments")
            get_router.return_value = router

            svc = get_unified_webhook_service()
            result = svc.process_payment_webhook("tr_dispatch", {})

        self.assertEqual(result["status"], "success")
        frappe.get_doc("Payment Plan Payment", intent.name).reload()
        plan = frappe.get_doc("Payment Plan", self.plan.name)
        self.assertEqual(plan.installments[0].status, "Paid")
```

Run it and confirm it FAILS (classification AssertionError is raised because no dispatch exists yet):
`cd ~/frappe-bench && bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.payment.test_payment_plan_payment_webhook`
Expected: the new test FAILS with "should not classify plan payments".

- [ ] **Step 6: Insert the dispatch**

In `verenigingen/verenigingen_payments/mollie/services/webhook_wrapper_service_unified.py`, inside `process_payment_webhook`, immediately after the line `payment = router.fetch_payment(payment_id)` (~`:368`) and BEFORE `classification = router.classify_payment(payment)`:

```python
                payment = router.fetch_payment(payment_id)

                # PAYMENT PLAN PAYMENTS: finalize the installment and return
                # BEFORE donation classification (whose "donation" keyword would
                # otherwise misroute these to the donation lookup -> 500 loop).
                _md = payment.get("metadata") if isinstance(payment, dict) else getattr(payment, "metadata", None)
                if isinstance(_md, dict) and _md.get("reference_doctype") == "Payment Plan Payment":
                    from .payment_plan_payment_handler import handle_payment_plan_payment

                    result = handle_payment_plan_payment(payment_id, payment)
                    result["duration_seconds"] = time.time() - start_time
                    return result

                classification = router.classify_payment(payment)
```

- [ ] **Step 7: Run the full webhook test module to verify all pass**

Run: `cd ~/frappe-bench && bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.payment.test_payment_plan_payment_webhook`
Expected: PASS (4 tests).

- [ ] **Step 8: Regression — donation webhook still classifies**

Run the existing webhook suite to confirm the dispatch does not regress donations:
`cd ~/frappe-bench && bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.payment.test_unified_webhook_error_scenarios`
Expected: PASS (no new failures vs. baseline).

- [ ] **Step 9: Lint and commit**

```bash
cd ~/frappe-bench/apps/verenigingen
black verenigingen/verenigingen_payments/mollie/services/payment_plan_payment_handler.py verenigingen/verenigingen_payments/mollie/services/webhook_wrapper_service_unified.py verenigingen/tests/payment/test_payment_plan_payment_webhook.py
ruff check verenigingen/verenigingen_payments/mollie/services/payment_plan_payment_handler.py verenigingen/verenigingen_payments/mollie/services/webhook_wrapper_service_unified.py
git add verenigingen/verenigingen_payments/mollie/services/payment_plan_payment_handler.py verenigingen/verenigingen_payments/mollie/services/webhook_wrapper_service_unified.py verenigingen/tests/payment/test_payment_plan_payment_webhook.py
git commit -m "feat(payments): webhook confirmation for payment-plan installments (A3)"
```

---

### Task 5: Allow "Payment Plan Payment" on the payment-success return page

**Files:**
- Modify: `verenigingen/templates/pages/payment_success.py` (`ALLOWED_PAYMENT_DOCTYPES`, `:16,32-36`)
- Test: `verenigingen/tests/backend/portal/test_payment_success_plan_payment.py`

**Interfaces:**
- Consumes: `Payment Plan Payment` doctype (Task 1) with `payment_id`/`paid`/`amount` fields.

- [ ] **Step 1: Write the failing test**

Create `verenigingen/tests/backend/portal/test_payment_success_plan_payment.py`:

```python
# Copyright (c) 2026, Verenigingen
"""payment-success must accept a Payment Plan Payment docname."""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase


class TestPaymentSuccessPlanPayment(VereningingenTestCase):
    def test_payment_plan_payment_is_allowed_doctype(self):
        from verenigingen.templates.pages.payment_success import ALLOWED_PAYMENT_DOCTYPES

        self.assertIn("Payment Plan Payment", ALLOWED_PAYMENT_DOCTYPES)

    def test_get_context_renders_for_plan_payment(self):
        from verenigingen.templates.pages import payment_success

        intent = frappe.get_doc(
            {"doctype": "Payment Plan Payment", "installment_number": 1, "amount": 40.0,
             "currency": "EUR", "status": "Paid", "paid": 1, "payment_id": "tr_ok"}
        )
        intent.insert(ignore_permissions=True, ignore_mandatory=True, ignore_links=True)
        self.track_doc("Payment Plan Payment", intent.name)

        frappe.form_dict = frappe._dict({"doctype": "Payment Plan Payment", "docname": intent.name})
        context = frappe._dict()
        payment_success.get_context(context)
        # Must NOT be the "invalid document type" error path.
        self.assertNotIn("Invalid document type", str(context.get("error") or ""))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/frappe-bench && bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.backend.portal.test_payment_success_plan_payment`
Expected: FAIL — `"Payment Plan Payment"` not in `ALLOWED_PAYMENT_DOCTYPES`.

- [ ] **Step 3: Add the doctype to the whitelist**

In `verenigingen/templates/pages/payment_success.py`, add `"Payment Plan Payment"` to the `ALLOWED_PAYMENT_DOCTYPES` set (`:16`):

```python
ALLOWED_PAYMENT_DOCTYPES = {"Donation", "Member Application", "Sales Invoice", "Payment Plan Payment"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/frappe-bench && bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.backend.portal.test_payment_success_plan_payment`
Expected: PASS. (If `get_context` reads a field the intent lacks, add it to the doctype JSON and reload — the intent already has `payment_id`/`paid`/`amount`/`title` via `name`.)

- [ ] **Step 5: Commit**

```bash
cd ~/frappe-bench/apps/verenigingen
black verenigingen/templates/pages/payment_success.py verenigingen/tests/backend/portal/test_payment_success_plan_payment.py
git add verenigingen/templates/pages/payment_success.py verenigingen/tests/backend/portal/test_payment_success_plan_payment.py
git commit -m "feat(payments): allow Payment Plan Payment on payment-success page (A3)"
```

---

### Task 6: Member-facing pay page (`/payment_plan_pay`)

**Files:**
- Create: `verenigingen/templates/pages/payment_plan_pay.py`
- Create: `verenigingen/templates/pages/payment_plan_pay.html`
- Test: `verenigingen/tests/backend/portal/test_page_payment_plan_pay.py`

**Interfaces:**
- Consumes: `get_current_user_member_name`; `get_next_payable_installment` (Task 3); `PaymentHook.get_available_methods`.
- Produces: portal route `/payment_plan_pay?plan=<name>`; context keys `plan`, `installment` (dict or None), `payment_methods`, `member`, plus `no_access`/`message` on rejection.

- [ ] **Step 1: Write the failing tests**

Create `verenigingen/tests/backend/portal/test_page_payment_plan_pay.py`:

```python
# Copyright (c) 2026, Verenigingen
"""Pay page get_context: ownership gating + next payable installment."""

import frappe
from frappe.utils import today

from verenigingen.tests.utils.base import VereningingenTestCase


class TestPagePaymentPlanPay(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.member = self._member()
        self.plan = self._plan(self.member.name)

    def _member(self):
        email = f"pp-{frappe.generate_hash(length=6)}@example.com"
        m = frappe.new_doc("Member")
        m.first_name = "Pp"
        m.last_name = "Member"
        m.email = email
        m.member_since = today()
        m.save(ignore_permissions=True)
        self.track_doc("Member", m.name)
        if not frappe.db.exists("User", email):
            u = frappe.get_doc({"doctype": "User", "email": email, "first_name": "Pp",
                                "send_welcome_email": 0, "roles": [{"role": "Verenigingen Member"}]}).insert(ignore_permissions=True)
            self.track_doc("User", u.name)
        m.db_set("user", email)
        return m

    def _plan(self, member_name):
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

    def test_owner_sees_next_installment(self):
        from verenigingen.templates.pages import payment_plan_pay

        frappe.form_dict = frappe._dict({"plan": self.plan.name})
        with self.as_user(self.member.email):
            ctx = frappe._dict()
            payment_plan_pay.get_context(ctx)
        self.assertEqual(ctx.plan.name, self.plan.name)
        self.assertIsNotNone(ctx.installment)
        self.assertEqual(ctx.installment["installment_number"], 1)

    def test_non_owner_denied(self):
        from verenigingen.templates.pages import payment_plan_pay

        other = self._member()
        frappe.form_dict = frappe._dict({"plan": self.plan.name})
        with self.as_user(other.email):
            ctx = frappe._dict()
            payment_plan_pay.get_context(ctx)
        self.assertTrue(ctx.get("no_access"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/frappe-bench && bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.backend.portal.test_page_payment_plan_pay`
Expected: FAIL — module `payment_plan_pay` does not exist.

- [ ] **Step 3: Implement the page controller**

Create `verenigingen/templates/pages/payment_plan_pay.py`:

```python
"""Context for the payment-plan installment pay page."""

import frappe
from frappe import _

from verenigingen.api.payment_plan_management import get_next_payable_installment
from verenigingen.utils.member_utils import get_current_user_member_name
from verenigingen.verenigingen_payments.hooks.payment_hook import PaymentHook


def get_context(context):
    context.no_cache = 1
    context.show_sidebar = False
    context.title = _("Pay Installment")

    if frappe.session.user == "Guest":
        frappe.local.flags.redirect_location = "/login"
        raise frappe.Redirect

    plan_name = frappe.form_dict.get("plan")
    member = get_current_user_member_name()
    if not member or not plan_name or not frappe.db.exists("Payment Plan", plan_name):
        context.no_access = True
        context.message = _("Payment plan not found.")
        return context

    plan = frappe.get_doc("Payment Plan", plan_name)
    if plan.member != member:
        context.no_access = True
        context.message = _("You can only pay your own payment plans.")
        return context

    context.plan = plan
    context.installment = get_next_payable_installment(plan)
    # Phase 1: only online (Mollie) methods are wired for payment plans.
    context.payment_methods = [
        m for m in PaymentHook.get_available_methods() if m["id"] == "mollie"
    ]
    return context
```

- [ ] **Step 4: Implement the page template**

Create `verenigingen/templates/pages/payment_plan_pay.html`:

```html
{% extends "templates/web.html" %}
{% block title %}{{ _("Pay Installment") }}{% endblock %}
{% block page_content %}
<div class="container mt-4" style="max-width: 560px;">
    <h2>{{ _("Pay Installment") }}</h2>
    {% if no_access %}
        <div class="alert alert-danger">{{ message }}</div>
    {% elif not installment %}
        <div class="alert alert-info">{{ _("This payment plan has no payment due right now.") }}</div>
        <a href="/payment_plans" class="btn btn-secondary">{{ _("Back to payment plans") }}</a>
    {% else %}
        <p>
            {{ _("Installment") }} #{{ installment.installment_number }} —
            <strong>€{{ "%.2f"|format(installment.amount or 0) }}</strong>
        </p>
        {% if not payment_methods %}
            <div class="alert alert-warning">{{ _("Online payment is not available right now. Please contact support.") }}</div>
        {% else %}
            <form id="pay-form">
                <div class="form-group">
                    <label>{{ _("Payment method") }}</label>
                    {% for m in payment_methods %}
                    <div class="form-check">
                        <input class="form-check-input" type="radio" name="method" value="{{ m.id }}"
                               id="method-{{ m.id }}" {% if loop.first %}checked{% endif %}>
                        <label class="form-check-label" for="method-{{ m.id }}">{{ m.label }}</label>
                    </div>
                    {% endfor %}
                </div>
                <button type="submit" class="btn btn-primary" id="pay-btn">{{ _("Pay now") }}</button>
                <a href="/payment_plans" class="btn btn-link">{{ _("Cancel") }}</a>
            </form>
        {% endif %}
    {% endif %}
</div>
{% if installment and payment_methods %}
<script>
document.getElementById('pay-form').addEventListener('submit', function (e) {
    e.preventDefault();
    var btn = document.getElementById('pay-btn');
    btn.disabled = true;
    var method = document.querySelector('input[name=method]:checked').value;
    frappe.call({
        method: 'verenigingen.api.payment_plan_management.initiate_installment_payment',
        args: { plan: '{{ plan.name }}', installment_number: {{ installment.installment_number }}, method: method },
        callback: function (r) {
            var data = (r.message && r.message.data) || r.message || {};
            if (data.redirect_url) {
                window.location.href = data.redirect_url;
            } else {
                btn.disabled = false;
                frappe.msgprint(__('Could not start the payment. Please try again or contact support.'));
            }
        },
        error: function () { btn.disabled = false; }
    });
});
</script>
{% endif %}
{% endblock %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd ~/frappe-bench && bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.backend.portal.test_page_payment_plan_pay`
Expected: PASS (2 tests).

- [ ] **Step 6: Verify the template parses**

Run (from sites dir):
```bash
cd ~/frappe-bench/sites && ../env/bin/python -c "import frappe; frappe.init(site='test_site_1'); frappe.connect(); frappe.get_jenv().parse(open('/home/frappeuser/frappe-bench/apps/verenigingen/verenigingen/templates/pages/payment_plan_pay.html').read()); print('JINJA OK')"
```
Expected: `JINJA OK`.

- [ ] **Step 7: Lint and commit**

```bash
cd ~/frappe-bench/apps/verenigingen
black verenigingen/templates/pages/payment_plan_pay.py verenigingen/tests/backend/portal/test_page_payment_plan_pay.py
ruff check verenigingen/templates/pages/payment_plan_pay.py
git add verenigingen/templates/pages/payment_plan_pay.py verenigingen/templates/pages/payment_plan_pay.html verenigingen/tests/backend/portal/test_page_payment_plan_pay.py
git commit -m "feat(payments): payment-plan installment pay page (A3)"
```

---

### Task 7: Wire the "Make Payment" button to the pay page

**Files:**
- Modify: `verenigingen/templates/pages/payment_plans.html` (`showPaymentForm`, `:437-440`; button visibility, `:342-343`)

**Interfaces:**
- Consumes: the `/payment_plan_pay` route (Task 6). The plan objects rendered here already carry `installments` (each with `status`) from `get_member_payment_plans`.

- [ ] **Step 1: Widen the button visibility to any payable installment**

In `verenigingen/templates/pages/payment_plans.html`, replace the button render condition (`:342-343`). Add a helper near the other JS helpers:

```javascript
function hasPayableInstallment(plan) {
    return (plan.installments || []).some(function (i) {
        return i.status === 'Pending' || i.status === 'Overdue';
    });
}
```

And change the button line from:

```javascript
                ${plan.status === 'Active' && plan.next_payment_date ?
                    `<button class="btn btn-primary" onclick="showPaymentForm('${escapeHtml(plan.name)}')">Make Payment</button>` : ''}
```

to:

```javascript
                ${plan.status === 'Active' && hasPayableInstallment(plan) ?
                    `<button class="btn btn-primary" onclick="showPaymentForm('${escapeHtml(plan.name)}')">Make Payment</button>` : ''}
```

- [ ] **Step 2: Navigate to the pay page instead of the stub alert**

Replace `showPaymentForm` (`:437-440`):

```javascript
function showPaymentForm(planId) {
    window.location.href = '/payment_plan_pay?plan=' + encodeURIComponent(planId);
}
```

- [ ] **Step 3: Verify the inline JS parses and the stub is gone**

```bash
cd ~/frappe-bench/apps/verenigingen
python3 -c "import re; s=open('verenigingen/templates/pages/payment_plans.html').read(); js='\n'.join(re.findall(r'<script[^>]*>(.*?)</script>', s, re.DOTALL)); open('/tmp/pp.js','w').write(js); assert 'coming soon' not in js, 'stub alert still present'; assert 'payment_plan_pay' in js, 'navigation missing'; print('checks pass')"
node --check /tmp/pp.js && echo "NODE SYNTAX OK"
```
Expected: `checks pass` then `NODE SYNTAX OK`.

- [ ] **Step 4: Verify the Jinja template still parses**

```bash
cd ~/frappe-bench/sites && ../env/bin/python -c "import frappe; frappe.init(site='test_site_1'); frappe.connect(); frappe.get_jenv().parse(open('/home/frappeuser/frappe-bench/apps/verenigingen/verenigingen/templates/pages/payment_plans.html').read()); print('JINJA OK')"
```
Expected: `JINJA OK`.

- [ ] **Step 5: Commit**

```bash
cd ~/frappe-bench/apps/verenigingen
git add verenigingen/templates/pages/payment_plans.html
git commit -m "feat(payments): route Make Payment button to the pay page (A3)"
```

---

### Task 8: Full-module regression + open the PR

- [ ] **Step 1: Run all new test modules together**

Run:
```bash
cd ~/frappe-bench && bench --site test_site_1 run-tests --app verenigingen \
  --module verenigingen.verenigingen_payments.doctype.payment_plan_payment.test_payment_plan_payment \
  && bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.payment.test_payment_hook_description \
  && bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.api.test_payment_plan_make_payment \
  && bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.payment.test_payment_plan_payment_webhook \
  && bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.backend.portal.test_payment_success_plan_payment \
  && bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.backend.portal.test_page_payment_plan_pay
```
Expected: all PASS.

- [ ] **Step 2: Push and open the PR**

```bash
cd ~/frappe-bench/apps/verenigingen
git push -u origin feat/payment-plan-make-payment-mollie-a3
gh pr create --base develop --title "feat(payments): Make Payment for payment plans via Mollie (A3 phase 1)" --body "<summary of the spec + that Pay.nl is phase 2>"
```

- [ ] **Step 3: Request a skeptical code review of the implementation (per repo practice) before merge.**

---

## Notes for the implementer

- **Do not** modify `MollieGateway.process_payment` — it is reused unchanged (it reads `amount`/`currency`, writes `payment_id`, all `hasattr`-guarded).
- The webhook finalization runs as the configured `webhook_user`; if `process_payment`'s Payment Entry submit fails on a permission error in that context, wrap the `plan.process_payment(...)` call in the same service-user pattern the donation flow uses (`frappe.set_user`), and re-run Task 4 Step 4/7. Verify by inspecting the Error Log after the webhook tests.
- `get_member_payment_plans` already returns each installment's `status` (verified: its installment `fields` include `installment_number` and `status`), so `hasPayableInstallment` (Task 7) works without a backend change.
- The `initiate_installment_payment` endpoint uses `@self_service_api(FINANCIAL, implicit_allowed=True)` (the same decorator as `request_payment_plan`/`get_member_payment_plans`) so a plain member may call it for their own plan. On direct test invocation the security decorator serializes the returned `OperationResult` to the nested dict `{"success":..., "data":{...}}` (same contract the C1 tests rely on), which is why the tests read `result["success"]` and `result["data"]`.
