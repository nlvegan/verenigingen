# Financial-history hook transaction-safety redesign

**Date:** 2026-07-20
**Status:** Design approved; pending SWE review + implementation plan
**Related:** PR #166 (test-isolation fix for the same subsystem), issue #162 follow-up

## Problem

`FinancialHistoryBatchProcessor` (`verenigingen/utils/financial_history_batch_processor.py`)
keeps payment/expense-history updates in **class-level in-memory dicts**
(`_payment_queue` / `_expense_queue`). Enqueuing (`queue_payment_update`, etc.)
calls `_maybe_process_batches()`, which — the first time in a process, or ≥30s
after the last drain — **synchronously drains the queue inline in the caller**,
and `_process_member_payment_batch` / `_process_member_expense_batch` issue a
**transaction-wide `frappe.db.commit()`** on success and **`frappe.db.rollback()`**
on error.

Five call sites invoke this **inside document-controller submit/cancel hooks**
(Class A), so the inline commit/rollback runs inside the document's own
transaction:

| Handler | Hook | File |
|---|---|---|
| `queue_member_payment_history_update_handler` | Payment Entry `on_submit` / `on_cancel` / `on_trash` | `utils/background_jobs.py:794` |
| `update_member_expense_history` | Expense Claim `on_submit` | `services/volunteer/expense_handlers.py:27` |
| `on_expense_claim_cancel` | Expense Claim `on_cancel` | `services/volunteer/expense_handlers.py:67` |
| `schedule_member_expense_history_update` | Expense Claim `on_update_after_submit` | `events/delayed_expense_hooks.py:25` |
| `schedule_member_expense_history_removal` | Expense Claim `on_cancel` | `events/delayed_expense_hooks.py:150` |

Consequence: submitting a Payment Entry (or Expense Claim) can, on the
first-in-process / post-lull tick, **prematurely commit its own submit
transaction** before the other `on_submit` handlers run (so a later handler's
failure can no longer roll the submit back → inconsistent state), or a batch
error's **`rollback()` can discard the submit itself**. Every one of these
handlers already intends deferral ("will be processed by the scheduled job",
"don't fail the submission") — the authors believed `queue_*` was async and did
not realize it drains inline.

The Sales Invoice path (`events/subscribers/payment_history_subscriber.py`) is
**not** affected because it is already dispatched via `frappe.enqueue`
(`events/invoice_events.py:126`, `delay=2`, `dedupe=True`, per-member
`job_name`), so its inline drain happens inside a dedicated worker job.

### Two pre-existing bugs surfaced during review

1. **The catch-all cron does not run every 30s.** `hooks/scheduler.py:128`
   registers `"*/30 * * * * *"` intending every-30-seconds. It is a 6-field
   expression parsed as minute ∈ {0,30} (not sub-minute), and Frappe's scheduler
   tick is 240s (`frappe/utils/scheduler.py` `DEFAULT_SCHEDULER_TICK`), which
   floors any cadence at ~4 minutes. Real drain cadence ≈ 4 minutes.

2. **The "repair" / "self-heal" jobs are circular.** `validate_and_repair_payment_history`
   (`utils/payment_history_validator.py:102`) and
   `refresh_all_member_financial_histories` do not write history directly — they
   **re-enqueue** through the same batch processor (`add_invoice_to_payment_history`
   → `queue_payment_update`). They report `success_count += 1` / `"repaired"`
   without verifying a row landed. So they cannot recover a genuinely-lost
   update; the "self-heal" is illusory. (The expense side already has a correct
   source-of-truth reconciliation — `ExpenseHistoryBatchProcessor._get_pending_expense_claims`,
   `services/volunteer/expense_history_batch_processor.py:74` — the payment side
   has no equivalent.)

## Approach considered and rejected: Redis-backed queue + scheduler drain

Moving the queue to a site-namespaced Redis hash drained only by the scheduler
was considered and **rejected** after review:

- **Self-heal remains false** — the repair jobs still re-enqueue, so a Redis-down
  drop is unrecovered while reporting success (bug #2 above).
- **Latency** — scheduler-only draining floors freshness at ~4 minutes (bug #1),
  vs ~2s for RQ `delay=2`.
- **Worse test isolation** — a shared Redis hash keyed only by `{db_name}`
  (`frappe/utils/redis_wrapper.py:52`) has no worker axis. Tests call
  `force_process_all()` explicitly (`tests/payment/test_payment_history_race_condition.py`,
  6 sites); with a shared hash, one test process would drain and `hdel` another
  process's entries — a **cross-worker** version of the exact rollback-wipe bug
  PR #166 fixed, which no per-process reset can undo. The current per-process
  in-memory dict cannot have this hazard.
- **New surface to get right** — `hgetall` has no `ConnectionError` guard
  (`redis_wrapper.py:229`), retain-on-failure semantics are unspecified, and a
  drain lock would have to be added (`utils/db_advisory_lock.py` exists but is
  extra wiring).

## Chosen design

Three independent parts, shipped as separate commits/PRs.

### Part 1 — Enqueue-per-hook (the fix)

Convert each of the five Class-A handlers to defer via `frappe.enqueue`, exactly
mirroring the proven Sales Invoice path. Each handler resolves its member(s)
cheaply (the lightweight lookups it already does) and enqueues a per-member drain
job:

```python
frappe.enqueue(
    "verenigingen.<...>.<drain_fn>",
    queue="short",
    job_name=f"fin_history_payment_{member}",   # per-member coalescing
    dedupe=True,
    timeout=300,
    delay=2,                                      # let the submit commit first
    member=member,
    invoice=invoice,                              # or expense / removal args
)
```

The enqueued drain function's body is the **current handler body minus the
enqueue** — it re-derives what to queue from the member/doc it was passed (the
Payment Entry handler re-derives the customer's submitted invoices exactly as it
does today; the expense handlers queue the single expense op), calls the existing
`queue_*` path, then explicitly drains. The batch processor's inline
commit/rollback now executes **only inside the dedicated worker job**, where it
is safe (a dedicated transaction with no unrelated caller work). To avoid the
`_maybe_process_batches` 30s-throttle uncertainty, the drain function calls
`FinancialHistoryBatchProcessor.force_process_all()` after queuing. Note
`force_process_all()` drains the whole worker-local queue (not just this
member's entries); that is safe and idempotent — the queue is process-local to
the worker, jobs run serially per worker, and `add_or_update_entry` no-ops on
unchanged data.

**Unchanged:** `FinancialHistoryBatchProcessor` internals, `MemberFinancialHistoryManager`
(commit / FOR UPDATE / retry), and all other call sites. Public API of `queue_*`
is untouched. The in-memory-queue architecture is intentionally retained — it is
harmless once confined to worker jobs, and replacing it is separable debt.

**Handler notes:**
- Payment Entry handler loops a customer's submitted invoices; enqueue **one job
  per member** (dedup by `job_name`), not one per invoice, to bound job count.
  The drain job re-derives the invoice list.
- The two Expense Claim `on_cancel` handlers (`expense_handlers.on_expense_claim_cancel`
  and `delayed_expense_hooks.schedule_member_expense_history_removal`) overlap;
  the plan must avoid double-processing — prefer a single enqueue per (member,
  expense, operation).
- Errors resolving the member stay caught-and-logged (never fail the submit),
  as today.

### Part 2 — Fix the miscadenced cron

Replace `hooks/scheduler.py:128` `"*/30 * * * * *"` with a valid expression
consistent with the ~240s tick and the catch-all's role, e.g. `"*/5 * * * *"`
(every 5 minutes). With Part 1 delivering prompt updates via RQ, the cron is a
periodic safety net, so a few-minute cadence is appropriate.

### Part 3 — Make the catch-all reconcile source-of-truth

Give the **scheduled** payment catch-all a real reconciliation, mirroring the
existing expense one:

- Add a payment-side `_get_pending_invoices()` analogue: submitted Sales Invoices
  (docstatus 1) for members whose `payment_history` row for that invoice is
  missing, resolved member-by-customer.
- The scheduled sweep enqueues per-member drain jobs (Part 1's mechanism) for the
  pending set, instead of the current re-enqueue-everything behavior.
- Whitelisted repair endpoints (`validate_and_repair_payment_history`) route
  through the same reconciliation so their reported counts reflect real work.

The expense catch-all (`_get_pending_expense_claims`) already reconciles
source-of-truth and is the template; Part 3 brings the payment side to parity.

## Testing

- **Part 1:** for each of the 5 handlers, patch `frappe.enqueue` and assert it is
  called once per affected member with the expected `job_name` / args, and that
  the handler performs **no** inline processing/commit (assert the batch
  processor's per-member processing is not invoked and no history row is written
  synchronously within the hook). Mirror the existing invoice-path handler tests.
- **Drain function:** an integration test that runs the enqueued drain (directly)
  and asserts the history row lands.
- **Part 2:** assert the registered cron expression is valid and fires at the
  intended cadence (parse-level check).
- **Part 3:** seed a submitted Sales Invoice / Payment Entry with no history row,
  run the reconciliation, assert a per-member job is enqueued and the row lands
  after draining; assert an already-reflected invoice is **not** re-processed.
- **Regression:** PR #166's `TestFinancialBatchQueueIsolation` and the
  `_reset_financial_history_batch_queue()` hook remain valid unchanged — the
  in-memory queue + inline drain still exist, now triggered from worker jobs.
- Existing tests that rely on inline draining without `force_process_all()`
  (`tests/payment/test_invoice_generation_and_payment_history_sync.py`,
  `tests/payment/test_regression_payment_history_draft_status.py`) must be
  re-checked; if any drove a Class-A hook synchronously and asserted immediate
  history, update them to drive the drain job (or call `force_process_all()`).

## Risks & mitigations

- **Worker availability:** enqueue-per-hook depends on `bench worker` running
  (already true for the Sales Invoice path). If workers are down, updates queue
  and process when workers return; the Part 3 sweep is the backstop. Acceptable,
  and no worse than the existing invoice path.
- **Double-processing across overlapping expense handlers:** addressed by
  per-(member, expense, operation) enqueue + `dedupe`/`job_name`.
- **Test-mode enqueue:** in tests, `frappe.enqueue` may run inline or be a no-op
  depending on config; tests assert on the enqueue call, and the drain is
  exercised directly, so behavior is deterministic regardless.

## Out of scope

- Replacing the in-memory-queue architecture (retained, confined to workers).
- The Mollie direct-write path (`verenigingen_payments/mollie/services/payment_processors.py`
  appends to `payment_history` + saves directly, bypassing the queue) — a
  pre-existing parallel write path this redesign does not touch.
- Converting `_process_member_*`'s commit/rollback to savepoints (unnecessary
  once these run only in dedicated worker/scheduler jobs).
