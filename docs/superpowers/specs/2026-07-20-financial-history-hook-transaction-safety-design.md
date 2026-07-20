# Financial-history hook transaction-safety redesign

**Date:** 2026-07-20
**Status:** Design approved; revised after SWE review (enqueue-parameter
corrections, bounded Part 3 scan, test-audit prerequisite); pending user review →
implementation plan
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
(`events/invoice_events.py:126`), so its inline drain happens inside a dedicated
worker job rather than the request transaction. (Its enqueue call passes
`delay=2` / `dedupe=True` / `job_name=...`, which — see "enqueue-parameter
correctness" below — are non-functional in this Frappe version; the path works
anyway because the enqueue itself succeeds and the worker is a separate process.)

### Two pre-existing bugs surfaced during review

1. **The catch-all cron does not run every 30s.** `hooks/scheduler.py:128`
   registers `"*/30 * * * * *"` intending every-30-seconds. croniter (with the
   default `second_at_beginning=False`) parses the 6 fields as
   `[minute, hour, day, month, weekday, second]`, so `minute="*/30"` restricts it
   to minutes {0, 30} and the trailing `second="*"` is unconstrained — the job is
   "due" on every second of minute :00 and :30 and **never during the other 58
   minutes**. Combined with the 240s scheduler tick, real behavior is bursty and
   tick-phase-dependent (verified empirically): it can go unfired for ~28-30
   minutes, then fire on every tick landing inside a 1-minute window — not a
   uniform cadence.

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
- **Latency** — scheduler-only draining makes freshness bursty and up to ~30 min
  (bug #1), vs a couple seconds for an RQ worker picking up an
  `enqueue_after_commit` job.
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

Convert each of the five Class-A handlers to defer via `frappe.enqueue`. Each
handler resolves its member(s) cheaply (the lightweight lookups it already does)
and enqueues a per-member drain job:

```python
frappe.enqueue(
    "verenigingen.<...>.<drain_fn>",
    queue="short",
    job_id=f"fin_history_payment_{member}",       # real per-member dedup key
    deduplicate=True,                             # coalesce concurrent submits
    enqueue_after_commit=True,                    # enqueue only after the submit commits
    timeout=300,
    member=member,
    invoice=invoice,                              # or expense / removal args
)
```

**Enqueue-parameter correctness (verified against Frappe v16.19).** The Sales
Invoice path (`events/invoice_events.py:126`) and `events/event_emitter.py:63`
use `delay=2` + `dedupe=True` + `job_name=...`, all of which are **non-functional
in this Frappe version** and must NOT be copied:
- `frappe.enqueue` has no `delay` parameter — it leaks into `**kwargs` and is
  passed to the target function as a literal kwarg (crashing any drain fn without
  a `**kwargs` catch-all). Use `enqueue_after_commit=True` instead: a real
  parameter that enqueues the job only after the current transaction commits —
  the exact "let the submit commit first" guarantee (and stronger than a timing
  race). This also means a rolled-back submit enqueues nothing.
- Deduplication requires `job_id=<str>` + `deduplicate=True` (Frappe throws if
  `deduplicate` is set without `job_id`). `dedupe` is not a parameter (leaks into
  kwargs); `job_name` is deprecated and cosmetic (never a coalescing key). The
  correct pattern already exists in this repo
  (`patches/v2_2/resync_stuck_mollie_amendment_syncs.py:68`,
  `.../contribution_amendment_request.py:433`).

Because the Sales Invoice / event_emitter paths carry the same latent no-op
(they survive only on worker-dequeue timing), the plan should also correct those
two call sites to `job_id`+`deduplicate`+`enqueue_after_commit` (small, same
edit) so the new code isn't modeled on a broken template.

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
  per member** (dedup by `job_id=f"fin_history_payment_{member}"`), not one per
  invoice, to bound job count. The drain job re-derives the invoice list.
- The two Expense Claim `on_cancel` handlers (`expense_handlers.on_expense_claim_cancel`
  and `delayed_expense_hooks.schedule_member_expense_history_removal`) both fire
  on the same event (`hooks/doc_events.py:194-197`) and today collapse to one dict
  key; with real `deduplicate` + `job_id` they coalesce to a single enqueued job.
  The plan should still converge them to a single enqueue per (member, expense,
  operation) rather than rely on dedup.
- Drain functions take explicit named parameters only (member/invoice/expense) —
  no stray kwargs — which is safe now that no non-parameter (`delay`/`dedupe`)
  leaks through the enqueue call.
- Errors resolving the member stay caught-and-logged (never fail the submit),
  as today.

### Part 2 — Fix the miscadenced cron

Replace `hooks/scheduler.py:128` `"*/30 * * * * *"` with a valid expression
consistent with the ~240s tick and the catch-all's role, e.g. `"*/5 * * * *"`
(every 5 minutes). With Part 1 delivering prompt updates via RQ, the cron is a
periodic safety net, so a few-minute cadence is appropriate.

### Part 3 — Make the catch-all reconcile source-of-truth

Give the **scheduled** payment catch-all a real reconciliation:

- The current `validate_and_repair_payment_history` (`utils/payment_history_validator.py:23-42`,
  wired hourly at `hooks/scheduler.py:87`) is circular (it re-enqueues and counts
  that as "repaired" without verifying a row landed — bug #2) — **but it already
  bounds its scan to a 7-day window** (`cutoff_date = add_days(today(), -7)`,
  `WHERE si.creation >= %s`). Preserve that bounded window; the fix is to make it
  **reconcile source-of-truth** (find submitted Sales Invoices in-window whose
  member `payment_history` row is missing, resolved member-by-customer) and drive
  Part 1's per-member drain jobs, verifying the row lands — not to re-enqueue
  blindly.
- **Do NOT mirror the expense template's scan shape.** `_get_pending_expense_claims`
  (`services/volunteer/expense_history_batch_processor.py:88`) does an *unbounded*
  `frappe.get_all("Expense Claim", {"docstatus": 1})` full-table scan + per-row
  N+1. Sales Invoices are far higher-volume in a dues-billing org and this runs
  hourly, so porting the unbounded pattern would be a scalability regression vs.
  today. Keep the existing bounded-window approach.
- Reuse `_is_claim_in_member_history`-style existence checks, but batch the
  "already in history" lookup (single query over the window) rather than per-row.

## Testing

- **Part 1:** for each of the 5 handlers, patch `frappe.enqueue` and assert it is
  called once per affected member with the expected `job_id` / args, and that
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
- **Test-breakage audit is a plan prerequisite (not the two files first named).**
  `frappe.enqueue(is_async=True)` genuinely defers to Redis in tests
  (`call_directly` is only true for `now=True` or `not is_async and in_test`,
  `background_jobs.py:143`), so once Part 1 ships nothing auto-drains in a test
  process. A grep for `.submit()` + `payment_history`/`volunteer_expenses`
  assertions outside the `force_process_all()` callers yields ~20 candidate files
  (e.g. `test_event_driven_payment_history.py`, `test_payment_entry_cleanup.py`,
  `test_member_history_update_service_realdb.py`, `test_financial_workflows.py`,
  `test_member_lifecycle_complete.py`). Many likely use an escape hatch
  (`member.load_payment_history()` → `refresh_member_financial_history_optimized`,
  a synchronous rebuild that bypasses the queue) and are unaffected. Before
  writing the plan, do a real audit — e.g. stub the 5 handlers to no-op and run
  the payment/expense/volunteer test dirs — to enumerate the actual breakers, and
  fix each to drive the drain job or call `force_process_all()`.

## Risks & mitigations

- **Worker availability:** enqueue-per-hook depends on `bench worker` running
  (already true for the Sales Invoice path). If workers are down, updates queue
  and process when workers return; the Part 3 sweep is the backstop. Acceptable,
  and no worse than the existing invoice path.
- **Double-processing across overlapping expense handlers:** addressed by
  per-(member, expense, operation) enqueue + `deduplicate`/`job_id`.
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
- **KNOWN-REMAINING (follow-up): a second, independent synchronous payment-history
  path.** Payment Entry `on_submit` and Sales Invoice `on_submit`
  (`hooks/doc_events.py:138,163`) also fire
  `performance_event_handlers.on_member_payment_update` →
  `OptimizedMemberQueries.bulk_update_payment_history`, whose error path does a
  transaction-wide `frappe.db.commit()` then `frappe.db.rollback()`
  (`utils/optimized_queries.py:510,517`) **inside the submit transaction** — the
  same class of hazard this redesign removes from the batch-processor path, but a
  different mechanism. This redesign does **not** touch it, so the "no
  transaction-wide commit/rollback in submit hooks" objective is achieved only for
  the `FinancialHistoryBatchProcessor` path. Follow-up: wrap that error-path
  commit/rollback in a savepoint (or defer it), and reconcile the two parallel
  payment-history mechanisms.
