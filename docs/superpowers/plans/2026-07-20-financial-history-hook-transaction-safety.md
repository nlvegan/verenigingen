# Financial-history hook transaction-safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `FinancialHistoryBatchProcessor` from executing transaction-wide `commit()`/`rollback()` inside document submit/cancel hooks, by deferring the five affected handlers to background jobs.

**Architecture:** Each Class-A doc-event handler (Payment Entry + Expense Claim submit/cancel) is reduced to a cheap member lookup plus a `frappe.enqueue(..., enqueue_after_commit=True, job_id=..., deduplicate=True)` of a new per-member *drain function*. The drain function runs in a worker job, calls the existing `queue_*` API, then `force_process_all()` — so the batch processor's inline commit/rollback executes only inside the dedicated job. The batch processor and `MemberFinancialHistoryManager` are unchanged. Two follow-on parts fix a miscadenced catch-all cron and de-circularize the payment catch-all.

**Tech Stack:** Frappe/ERPNext v16.19, Python, `bench run-tests`.

**Spec:** `docs/superpowers/specs/2026-07-20-financial-history-hook-transaction-safety-design.md`

## Global Constraints

- **Frappe v16.19 enqueue API:** deferral until the enclosing transaction commits = `enqueue_after_commit=True`. Deduplication = `job_id=<str>` + `deduplicate=True` (Frappe throws if `deduplicate` without `job_id`). **Never** pass `delay=` (not a parameter — leaks into kwargs) or `dedupe=`/`job_name=` for dedup (`dedupe` is not a parameter; `job_name` is deprecated/cosmetic). Reference correct usage: `patches/v2_2/resync_stuck_mollie_amendment_syncs.py:68`.
- **Handlers must never raise into the submit** — keep the existing try/except that logs and returns (never `raise`).
- **Test site:** run tests on `test_site_1` (never `veg11`). Command form: `bench --site test_site_1 run-tests --app verenigingen --module <dotted.module>`.
- **`@frappe.whitelist()` stays outermost** on any decorated endpoint touched.
- **Drain functions take explicit named params only** (member/customer/expense/operation) — no `**kwargs` needed once the enqueue call passes only real parameters.
- **Three PRs:** Part 1 (Tasks 1–7) is one PR; Part 2 (Task 8) and Part 3 (Task 9) are separate PRs.

---

### Task 0: Audit the real test-breakage set (prerequisite)

`frappe.enqueue(is_async=True)` genuinely defers in tests, so once handlers stop draining inline, any test that submits a Payment Entry / Expense Claim and then synchronously asserts `payment_history` / `volunteer_expenses` **without** `force_process_all()` (and without the `load_payment_history()` synchronous-rebuild escape hatch) will break. Enumerate them before writing fixes.

**Files:**
- Temporary: stub the 5 handlers to `return` (do not commit this stub).
- Output: `docs/superpowers/plans/2026-07-20-test-breakage-audit.md` (list of breakers + which escape hatch, if any).

- [ ] **Step 1: Grep candidate tests**

Run:
```bash
cd ~/frappe-bench/apps/verenigingen
grep -rlE "\.submit\(\)" verenigingen/tests | xargs grep -lE "payment_history|volunteer_expenses" \
  | xargs grep -L "force_process_all" | sort -u
```
Record the list.

- [ ] **Step 2: Stub the 5 handlers locally (uncommitted) and run the affected test dirs**

Temporarily edit each of the 5 handlers (see Tasks 2–5 for exact locations) to `return` at the top, then:
```bash
for m in \
  verenigingen.tests.payment \
  verenigingen.tests.events ; do
  bench --site test_site_1 run-tests --app verenigingen --module $m 2>&1 | tail -30
done
```
(Also run any module from the Step 1 grep not covered above.)

- [ ] **Step 3: Record the definitive breaker list**

For each failing test, note whether it (a) drives an affected hook and asserts sync history (→ must be fixed in Task 6 by calling `force_process_all()` or driving the drain fn), or (b) uses `member.load_payment_history()` / `refresh_member_financial_history_optimized` (→ unaffected, ignore). Write the list to the audit file. Revert the stubs.

- [ ] **Step 4: Commit the audit doc**

```bash
git add docs/superpowers/plans/2026-07-20-test-breakage-audit.md
git commit -m "docs(audit): enumerate tests relying on inline financial-history drain"
```

---

## Part 1 — Enqueue-per-hook (PR 1)

### Task 1: Correct the enqueue params on the existing Sales Invoice / event_emitter paths

These are the template the new code copies; fix them first so the template is correct (and to fix the same latent no-op there).

**Files:**
- Modify: `verenigingen/events/invoice_events.py:126-159`
- Modify: `verenigingen/events/event_emitter.py:59-66`
- Test: `verenigingen/tests/events/test_invoice_events_coverage.py`

**Interfaces:**
- Produces: the canonical enqueue call shape reused by Tasks 2–5.

- [ ] **Step 1: Write the failing test**

Add to `test_invoice_events_coverage.py`:
```python
def test_invoice_event_enqueues_with_real_dedup_params(self):
    """emit_invoice_submitted must enqueue with job_id + deduplicate +
    enqueue_after_commit, not the no-op delay/dedupe/job_name kwargs."""
    from unittest.mock import patch
    from verenigingen.events import invoice_events

    captured = {}

    def fake_enqueue(method, **kwargs):
        captured["method"] = method
        captured["kwargs"] = kwargs

    with patch("verenigingen.events.invoice_events.frappe.enqueue", side_effect=fake_enqueue):
        invoice_events._emit_invoice_event(
            "invoice_submitted",
            {"customer": "SOME-CUST", "invoice": "SI-X"},
        )
    # If a member resolves, an enqueue happened; assert param hygiene when it did.
    if captured:
        assert "delay" not in captured["kwargs"], "delay is a no-op kwarg"
        assert "dedupe" not in captured["kwargs"], "dedupe is not a real param"
        assert captured["kwargs"].get("deduplicate") is True
        assert captured["kwargs"].get("enqueue_after_commit") is True
        assert captured["kwargs"].get("job_id")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.events.test_invoice_events_coverage --test test_invoice_event_enqueues_with_real_dedup_params`
Expected: FAIL (current code passes `delay`/`dedupe`/`job_name`).

- [ ] **Step 3: Fix the enqueue calls**

In `invoice_events.py`, replace each `frappe.enqueue(... delay=2, ... job_name=f"payment_history_update_{member['name']}", dedupe=True, ...)` with:
```python
frappe.enqueue(
    method=subscriber,
    queue="short",
    job_id=f"payment_history_update_{member['name']}",
    deduplicate=True,
    enqueue_after_commit=True,
    timeout=300,
    event_name=event_name,
    event_data=event_data,
)
```
Apply the same correction to the two other `frappe.enqueue` calls in the function (the no-customer fallback and the else branch), using a stable `job_id` (e.g. `f"{event_name}_{event_data.get('invoice')}_{subscriber}"`). In `event_emitter.py:59-66`, likewise replace `job_name=`/`dedupe=` with `job_id=`/`deduplicate=True` and add `enqueue_after_commit=True`; drop any `delay=`.

- [ ] **Step 4: Run test to verify it passes**

Run: same command as Step 2. Expected: PASS. Then run the whole module:
`bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.events.test_invoice_events_coverage` → all green.

- [ ] **Step 5: Commit**

```bash
git add verenigingen/events/invoice_events.py verenigingen/events/event_emitter.py verenigingen/tests/events/test_invoice_events_coverage.py
git commit -m "fix(events): use real enqueue dedup/commit params (job_id/deduplicate/enqueue_after_commit)"
```

---

### Task 2: Defer the Payment Entry handler

**Files:**
- Modify: `verenigingen/utils/background_jobs.py:794-826` (`queue_member_payment_history_update_handler`)
- Create (same file): `drain_member_payment_history(member, customer)`
- Test: `verenigingen/tests/payment/test_payment_entry_hook_defers.py` (new)

**Interfaces:**
- Produces: `drain_member_payment_history(member: str, customer: str)` — worker entry point; re-derives the customer's submitted invoices, queues each, drains.

- [ ] **Step 1: Write the failing test**

Create `test_payment_entry_hook_defers.py`:
```python
import frappe
from unittest.mock import patch
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPaymentEntryHookDefers(EnhancedTestCase):
    def test_handler_enqueues_per_member_and_does_not_process_inline(self):
        from verenigingen.utils import background_jobs

        member = self.create_test_member(
            first_name="HookDefer", last_name="Payment",
            email="hookdefer.payment@test.invalid",
        )
        doc = frappe._dict(doctype="Payment Entry", name="PE-TEST",
                           party_type="Customer", party=member.customer)

        calls = []
        with patch("verenigingen.utils.background_jobs.frappe.enqueue",
                   side_effect=lambda *a, **k: calls.append(k)):
            with patch(
                "verenigingen.utils.financial_history_batch_processor."
                "FinancialHistoryBatchProcessor._process_member_payment_batch"
            ) as proc:
                background_jobs.queue_member_payment_history_update_handler(doc)

        self.assertTrue(calls, "handler must enqueue a drain job")
        k = calls[0]
        self.assertEqual(k.get("member"), member.name)
        self.assertTrue(k.get("enqueue_after_commit"))
        self.assertTrue(k.get("deduplicate"))
        self.assertEqual(k.get("job_id"), f"fin_history_payment_{member.name}")
        proc.assert_not_called()  # no inline processing in the hook
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.payment.test_payment_entry_hook_defers`
Expected: FAIL (handler currently calls `queue_payment_update` inline, which processes).

- [ ] **Step 3: Rewrite the handler + add the drain function**

Replace the body of `queue_member_payment_history_update_handler` and add the drain fn:
```python
def queue_member_payment_history_update_handler(doc, method=None):
    """Payment Entry hook: enqueue a per-member payment-history drain job.

    Deferred via enqueue_after_commit so the batch processor's commit/rollback
    never runs inside the Payment Entry submit transaction.
    """
    try:
        if doc.party_type != "Customer":
            return
        members = frappe.get_all("Member", filters={"customer": doc.party}, fields=["name"])
        for member_doc in members:
            frappe.enqueue(
                "verenigingen.utils.background_jobs.drain_member_payment_history",
                queue="short",
                job_id=f"fin_history_payment_{member_doc.name}",
                deduplicate=True,
                enqueue_after_commit=True,
                timeout=300,
                member=member_doc.name,
                customer=doc.party,
            )
    except Exception as e:
        frappe.log_error(f"Failed to enqueue payment history update for payment {doc.name}: {e}")
        # Don't raise - we don't want to block the payment entry submission


def drain_member_payment_history(member, customer):
    """Worker job: queue the customer's submitted invoices for `member` and drain."""
    from verenigingen.utils.financial_history_batch_processor import (
        FinancialHistoryBatchProcessor,
        queue_payment_update,
    )

    invoices = frappe.get_all(
        "Sales Invoice", filters={"customer": customer, "docstatus": 1}, fields=["name"]
    )
    for invoice in invoices:
        queue_payment_update(member, invoice.name)
    FinancialHistoryBatchProcessor.force_process_all()
```

- [ ] **Step 4: Run test to verify it passes**

Run: same command as Step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add verenigingen/utils/background_jobs.py verenigingen/tests/payment/test_payment_entry_hook_defers.py
git commit -m "fix(payment): defer Payment Entry payment-history hook to a worker job"
```

---

### Task 3: Defer the Expense Claim `on_submit` handler

**Files:**
- Modify: `verenigingen/services/volunteer/expense_handlers.py:20-64` (`update_member_expense_history`)
- Create (same file): `drain_member_expense_history(member, expense, operation)`
- Test: `verenigingen/tests/events/test_expense_hook_defers.py` (new)

**Interfaces:**
- Produces: `drain_member_expense_history(member: str, expense: str, operation: str)` where `operation` ∈ {`"add"`, `"remove"`} — worker entry point reused by Task 4.

- [ ] **Step 1: Write the failing test**

Create `test_expense_hook_defers.py`:
```python
import frappe
from unittest.mock import patch
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestExpenseHookDefers(EnhancedTestCase):
    def _patch_lookup(self, member):
        # Stub the Volunteer->member resolution so the test needs no HR fixtures.
        return patch(
            "verenigingen.services.volunteer.expense_handlers.frappe.db.get_value",
            side_effect=lambda dt, *a, **k: {"Volunteer": "VOL-X"}.get(dt, member)
            if dt == "Volunteer" and "employee_id" in str(a) else member,
        )

    def test_submit_handler_enqueues_add_and_no_inline_process(self):
        from verenigingen.services.volunteer import expense_handlers

        doc = frappe._dict(doctype="Expense Claim", name="EXP-1", employee="EMP-1")
        calls = []
        with patch(
            "verenigingen.services.volunteer.expense_handlers.frappe.db.get_value",
            return_value="MEMBER-X",
        ), patch(
            "verenigingen.services.volunteer.expense_handlers.frappe.enqueue",
            side_effect=lambda *a, **k: calls.append(k),
        ):
            expense_handlers.update_member_expense_history(doc)

        self.assertTrue(calls)
        k = calls[0]
        self.assertEqual(k.get("member"), "MEMBER-X")
        self.assertEqual(k.get("expense"), "EXP-1")
        self.assertEqual(k.get("operation"), "add")
        self.assertTrue(k.get("enqueue_after_commit"))
        self.assertTrue(k.get("deduplicate"))
        self.assertEqual(k.get("job_id"), "fin_history_expense_MEMBER-X_EXP-1")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.events.test_expense_hook_defers --test test_submit_handler_enqueues_add_and_no_inline_process`
Expected: FAIL.

- [ ] **Step 3: Rewrite the handler tail + add the drain fn**

In `update_member_expense_history`, replace the `queue_expense_update(member_name, doc.name)` call (and its log) with an enqueue, and add the shared drain fn:
```python
        frappe.enqueue(
            "verenigingen.services.volunteer.expense_handlers.drain_member_expense_history",
            queue="short",
            job_id=f"fin_history_expense_{member_name}_{doc.name}",
            deduplicate=True,
            enqueue_after_commit=True,
            timeout=300,
            member=member_name,
            expense=doc.name,
            operation="add",
        )
```
Add at module level:
```python
def drain_member_expense_history(member, expense, operation):
    """Worker job: queue an expense add/remove for `member` and drain."""
    from verenigingen.utils.financial_history_batch_processor import (
        FinancialHistoryBatchProcessor,
        queue_expense_removal,
        queue_expense_update,
    )

    if operation == "remove":
        queue_expense_removal(member, expense)
    else:
        queue_expense_update(member, expense)
    FinancialHistoryBatchProcessor.force_process_all()
```

- [ ] **Step 4: Run test to verify it passes**

Run: same command as Step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add verenigingen/services/volunteer/expense_handlers.py verenigingen/tests/events/test_expense_hook_defers.py
git commit -m "fix(expense): defer Expense Claim on_submit history hook to a worker job"
```

---

### Task 4: Defer + converge the Expense Claim `on_cancel` handlers

Two handlers fire on Expense Claim `on_cancel` (`hooks/doc_events.py:194-197`):
`expense_handlers.on_expense_claim_cancel` and
`delayed_expense_hooks.schedule_member_expense_history_removal`. Both call
`queue_expense_removal(member, doc.name)`. Converge to a single enqueue and let
the other become a no-op that defers to it.

**Files:**
- Modify: `verenigingen/services/volunteer/expense_handlers.py:67-95` (`on_expense_claim_cancel`)
- Modify: `verenigingen/events/delayed_expense_hooks.py:150-168` (`schedule_member_expense_history_removal`)
- Test: `verenigingen/tests/events/test_expense_hook_defers.py`

- [ ] **Step 1: Write the failing test**

Add:
```python
    def test_cancel_handler_enqueues_remove_once(self):
        from verenigingen.services.volunteer import expense_handlers

        doc = frappe._dict(doctype="Expense Claim", name="EXP-2", employee="EMP-1")
        calls = []
        with patch(
            "verenigingen.services.volunteer.expense_handlers.frappe.db.get_value",
            return_value="MEMBER-Y",
        ), patch(
            "verenigingen.services.volunteer.expense_handlers.frappe.enqueue",
            side_effect=lambda *a, **k: calls.append(k),
        ):
            expense_handlers.on_expense_claim_cancel(doc)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].get("operation"), "remove")
        self.assertEqual(calls[0].get("job_id"), "fin_history_expense_MEMBER-Y_EXP-2")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.events.test_expense_hook_defers --test test_cancel_handler_enqueues_remove_once`
Expected: FAIL.

- [ ] **Step 3: Rewrite `on_expense_claim_cancel`; neutralize the duplicate**

In `on_expense_claim_cancel`, replace `queue_expense_removal(member_name, doc.name)` (+ log) with the same enqueue as Task 3 but `operation="remove"` and `job_id=f"fin_history_expense_{member_name}_{doc.name}"` (same key → `deduplicate` collapses any duplicate). In
`delayed_expense_hooks.schedule_member_expense_history_removal`, replace its body's `queue_expense_removal(...)` call with a delegation comment + `return` (the removal is now owned by `on_expense_claim_cancel`), keeping the function defined so the hook wiring in `doc_events.py` stays valid. (Alternatively remove it from `doc_events.py:195` — but keeping a no-op avoids touching hook wiring in this task.)

- [ ] **Step 4: Run test to verify it passes**

Run: same command as Step 2. Expected: PASS. Then full module green:
`bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.events.test_expense_hook_defers`

- [ ] **Step 5: Commit**

```bash
git add verenigingen/services/volunteer/expense_handlers.py verenigingen/events/delayed_expense_hooks.py verenigingen/tests/events/test_expense_hook_defers.py
git commit -m "fix(expense): defer + converge Expense Claim on_cancel history hooks"
```

---

### Task 5: Defer the Expense Claim `on_update_after_submit` handler

**Files:**
- Modify: `verenigingen/events/delayed_expense_hooks.py:18-45` (`schedule_member_expense_history_update`)
- Test: `verenigingen/tests/events/test_expense_hook_defers.py`

- [ ] **Step 1: Write the failing test**

Add:
```python
    def test_update_after_submit_handler_enqueues_add(self):
        from verenigingen.events import delayed_expense_hooks

        doc = frappe._dict(doctype="Expense Claim", name="EXP-3", employee="EMP-1")
        calls = []
        with patch(
            "verenigingen.events.delayed_expense_hooks.frappe.db.get_value",
            return_value=frappe._dict(name="VOL-Z", member="MEMBER-Z"),
        ), patch(
            "verenigingen.events.delayed_expense_hooks.frappe.enqueue",
            side_effect=lambda *a, **k: calls.append(k),
        ):
            delayed_expense_hooks.schedule_member_expense_history_update(doc)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].get("operation"), "add")
        self.assertEqual(calls[0].get("member"), "MEMBER-Z")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.events.test_expense_hook_defers --test test_update_after_submit_handler_enqueues_add`
Expected: FAIL.

- [ ] **Step 3: Rewrite the handler tail**

In `schedule_member_expense_history_update`, replace `queue_expense_update(volunteer_record.member, doc.name)` (+ logs) with an enqueue of `drain_member_expense_history` (`operation="add"`, `job_id=f"fin_history_expense_{volunteer_record.member}_{doc.name}"`, `enqueue_after_commit=True`, `deduplicate=True`, `queue="short"`, `timeout=300`). Import the drain target by dotted path string (no import needed).

- [ ] **Step 4: Run test to verify it passes**

Run: same command as Step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add verenigingen/events/delayed_expense_hooks.py verenigingen/tests/events/test_expense_hook_defers.py
git commit -m "fix(expense): defer Expense Claim on_update_after_submit history hook"
```

---

### Task 6: Fix tests broken by deferral (from Task 0)

**Files:**
- Modify: each test file enumerated in `docs/superpowers/plans/2026-07-20-test-breakage-audit.md`.

- [ ] **Step 1: For each affected test, drive the drain explicitly**

Where a test submits a Payment Entry / Expense Claim and asserts history, add after the submit:
```python
from verenigingen.utils.financial_history_batch_processor import FinancialHistoryBatchProcessor
FinancialHistoryBatchProcessor.force_process_all()
```
Or, if the enqueue is patched off, call the relevant drain fn directly
(`drain_member_payment_history(member, customer)` /
`drain_member_expense_history(member, expense, operation)`).

- [ ] **Step 2: Run each affected module and confirm green**

Run each: `bench --site test_site_1 run-tests --app verenigingen --module <module>`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add verenigingen/tests
git commit -m "test: drive financial-history drain explicitly where hooks now defer"
```

---

### Task 7: End-to-end verification + PR

**Files:**
- Test: `verenigingen/tests/payment/test_payment_entry_hook_defers.py` (add an integration case)

- [ ] **Step 1: Add an integration test proving no mid-submit commit + eventual landing**

```python
    def test_drain_fn_lands_history_row(self):
        member = self.create_test_member(
            first_name="Drain", last_name="Lands",
            email="drain.lands@test.invalid",
        )
        # build + submit a EUR Sales Invoice for member.customer (reuse the
        # _build_secured_invoice helper pattern from the security suite), then:
        from verenigingen.utils.background_jobs import drain_member_payment_history
        drain_member_payment_history(member.name, member.customer)
        member.reload()
        self.assertIn(
            invoice.name, [e.invoice for e in member.payment_history],
        )
```
(Fill in the invoice build using the same fields as
`tests/security/test_integrated_security_payment_system.py::_build_secured_invoice`.)

- [ ] **Step 2: Run the new module + the previously-affected suites**

Run:
```bash
bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.payment.test_payment_entry_hook_defers
bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.events.test_expense_hook_defers
bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.test_enhanced_test_factory_drain
```
Expected: all PASS.

- [ ] **Step 3: Commit + open PR 1**

```bash
git add -A && git commit -m "test: e2e financial-history drain-job landing"
git push -u origin design/financial-history-hook-transaction-safety
gh pr create --base develop --title "fix: defer financial-history batch processing out of document submit hooks" --body "<summary + link to spec>"
```

---

## Part 2 — Fix the miscadenced cron (PR 2)

### Task 8: Correct the financial-history cron expression

**Files:**
- Modify: `verenigingen/hooks/scheduler.py:126-130`
- Test: `verenigingen/tests/test_scheduler_cron_validity.py` (new)

- [ ] **Step 1: Write the failing test**

```python
import frappe
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestFinancialHistoryCron(EnhancedTestCase):
    def test_financial_history_cron_is_a_valid_5_field_expression(self):
        from croniter import croniter
        from verenigingen.hooks import scheduler

        crons = scheduler.scheduler_events["cron"]
        key = next(k for k, v in crons.items()
                   if any("financial_history_batch_processor" in fn for fn in v))
        self.assertEqual(len(key.split()), 5, "must be a valid 5-field cron")
        self.assertTrue(croniter.is_valid(key))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.test_scheduler_cron_validity`
Expected: FAIL (current key is the 6-field `"*/30 * * * * *"`).

- [ ] **Step 3: Fix the cron key**

In `scheduler.py`, change the cron key from `"*/30 * * * * *"` to `"*/5 * * * *"` (every 5 minutes — a valid 5-field expression consistent with the ~240s tick; the catch-all is now only a safety net behind Part 1's prompt RQ path). Update the adjacent comment to state the real cadence.

- [ ] **Step 4: Run test to verify it passes + migrate**

Run: same command as Step 2. Expected: PASS. Then sync the scheduler:
`bench --site test_site_1 migrate` (re-registers Scheduled Job Type entries).

- [ ] **Step 5: Commit + PR 2**

```bash
git add verenigingen/hooks/scheduler.py verenigingen/tests/test_scheduler_cron_validity.py
git commit -m "fix(scheduler): correct miscadenced financial-history cron (6-field -> */5)"
```

---

## Part 3 — De-circularize the payment catch-all (PR 3)

### Task 9: Reconcile payment history against source-of-truth (bounded window)

**Files:**
- Modify: `verenigingen/utils/payment_history_validator.py` (`validate_and_repair_payment_history` + helpers)
- Test: `verenigingen/tests/payment/test_payment_history_reconciliation.py` (new)

**Interfaces:**
- Produces: reconciliation reads submitted Sales Invoices in a bounded window, finds those missing from member `payment_history`, and enqueues Part 1's `drain_member_payment_history` per member (or drives it), verifying the row lands — instead of blindly re-enqueuing and counting success.

- [ ] **Step 1: Write the failing test**

```python
import frappe
from unittest.mock import patch
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPaymentHistoryReconciliation(EnhancedTestCase):
    def test_missing_invoice_is_detected_and_enqueued_once(self):
        # Seed a member + submitted EUR Sales Invoice, ensure NO payment_history row.
        # (build via the _build_secured_invoice field set.)
        from verenigingen.utils import payment_history_validator

        calls = []
        with patch(
            "verenigingen.utils.payment_history_validator.frappe.enqueue",
            side_effect=lambda *a, **k: calls.append(k),
        ):
            result = payment_history_validator.validate_and_repair_payment_history()
        self.assertTrue(result["success"])
        job_ids = [k.get("job_id") for k in calls]
        self.assertIn(f"fin_history_payment_{member.name}", job_ids)

    def test_already_reflected_invoice_is_not_reprocessed(self):
        # Seed a member whose payment_history already contains the invoice.
        from verenigingen.utils import payment_history_validator
        calls = []
        with patch(
            "verenigingen.utils.payment_history_validator.frappe.enqueue",
            side_effect=lambda *a, **k: calls.append(k),
        ):
            payment_history_validator.validate_and_repair_payment_history()
        self.assertEqual(calls, [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.payment.test_payment_history_reconciliation`
Expected: FAIL.

- [ ] **Step 3: Rewrite the repair to reconcile source-of-truth**

In `validate_and_repair_payment_history`, keep the existing 7-day `cutoff_date`
window (`WHERE si.creation >= %s`). For each in-window submitted Sales Invoice,
resolve the member by customer and check membership in `payment_history` with a
single batched query (e.g. one `frappe.get_all("Payment Entry Reference"/child
table)` or a `SELECT invoice FROM \`tabMember Payment History\` WHERE parent IN (...)`);
for members with any missing invoice, `frappe.enqueue(
"verenigingen.utils.background_jobs.drain_member_payment_history",
job_id=f"fin_history_payment_{member}", deduplicate=True, queue="short",
member=member, customer=customer)`. Count only members actually enqueued. Do
**not** call `add_invoice_to_payment_history` directly (that is the circular
path).

- [ ] **Step 4: Run test to verify it passes**

Run: same command as Step 2. Expected: PASS.

- [ ] **Step 5: Commit + PR 3**

```bash
git add verenigingen/utils/payment_history_validator.py verenigingen/tests/payment/test_payment_history_reconciliation.py
git commit -m "fix(payment): reconcile payment-history catch-all against source-of-truth"
```

---

## Notes for the implementer

- The batch processor and `MemberFinancialHistoryManager` are intentionally
  untouched; do not "clean up" the in-memory queue or its commit/rollback — they
  are safe once only reached from worker/scheduler jobs.
- `frappe.enqueue` param hygiene (Global Constraints) is the single most common
  way to get this wrong; copy the shape from Task 1, never from the old code.
- When patching `frappe.enqueue` in tests, patch it in the *handler's* module
  namespace (e.g. `verenigingen.utils.background_jobs.frappe.enqueue`), not
  globally.
