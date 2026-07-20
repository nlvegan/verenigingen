# event_emitter.py enqueue-semantics fix — investigation & plan (issue #168)

**Date:** 2026-07-20
**Status:** Investigated; ready to implement as its own small PR
**Issue:** https://github.com/nlvegan/verenigingen/issues/168
**Origin:** follow-up to PR #167 (financial-history hook transaction-safety), where an
out-of-scope change to `event_emitter.py` was reverted.

This doc combines what was learned during the #167 session with an independent
code+runtime investigation (full report was `.superpowers/sdd/issue-168-investigation.md`).

---

## 1. The problem

`verenigingen/events/event_emitter.py::emit_event` (the generic emitter behind
member/chapter/team/approval events) enqueues each subscriber with parameters that are
**non-functional in Frappe v16** (`background_jobs.py:76-209`):

```python
frappe.enqueue(
    method=subscriber, queue="short",
    job_name=f"{job_prefix}_{event_name}_{entity_name}",  # cosmetic, NOT a dedup key
    dedupe=True,                                           # NOT a real param -> leaks to **kwargs
    timeout=300,
    delay=delay,                                           # NOT a real param -> leaks to **kwargs
    ...event_name/event_data...,
)
```

- `delay` / `dedupe` are not real `frappe.enqueue` parameters — they leak into `**kwargs` and
  get forwarded to the subscriber (harmless: every subscriber accepts `**kwargs`).
- `job_name` is deprecated/cosmetic, not a coalescing key.
- Net effect: **no real deduplication, and enqueue happens immediately (before the emitting
  transaction commits)**. Real dedup requires `job_id=<str>` + `deduplicate=True`; "commit
  first" requires `enqueue_after_commit=True`.

This is the same latent bug fixed for the financial-history hooks in #167.

## 2. Why it was reverted in #167 (and the correction)

During #167 the fix was applied to `event_emitter.py` (per-subscriber `job_id` +
`deduplicate=True` + `enqueue_after_commit=True`, commit `9bf6ba38`) and then reverted
(`9c6d3143`) for two stated reasons — one right, one **wrong**:

1. **Right — scope creep.** `event_emitter.py` is a broadly-used generic emitter, not part of
   the financial-history hook path. It should change deliberately, on its own, not bundled.
2. **WRONG (corrected here) — attributed the `test_bulk_account_creation` lock-timeouts to it.**
   A runtime diagnostic **refutes** this: in test mode, creating a member fires **zero**
   `emit_event` calls (member events are hard-gated off when `frappe.flags.in_test` is set —
   `member_event_emission_service.py:41-45` `should_skip_event_emission`; and the factory
   passes `chapter or False` so no chapter events fire — `enhanced_test_factory.py:651,705`).
   A code path that never runs cannot accumulate after-commit callbacks. The CI "revert →
   green" was a single A/B on a suite the session itself repeatedly called flaky; locally the
   revert did **not** fix it (stray `frappe worker` PIDs racing the test-enqueued bulk jobs were
   the real local cause). **The C1 multi-subscriber collapse was already solved by `9bf6ba38`'s
   per-subscriber `job_id` before the revert.**

**Consequence:** re-applying the fix is safe; the revert was correct for *scope* only. The true
cause of the bulk lock-timeouts remains **unidentified** — see §7.

## 3. Event graph (blast radius)

`emit_event` fans out to N subscribers per event. `invoice_events.py` / expense hooks do their
**own** enqueue and are out of scope.

| Event | Fires from | # subs | test-gated? | bulk-flag skip? |
|---|---|---|---|---|
| member_status_changed | Member.on_update → emission service | 2 | **yes** | yes |
| member_lifecycle_changed | Member.on_update | 3 | **yes** | yes |
| chapter_board_changed | Chapter save → ChapterEventService | 3 | no | yes |
| chapter_membership_changed | Chapter save | 3 | no | yes |
| chapter_settings_changed | Chapter save | 3 | no | yes |
| team_membership_changed | Team controller | 2 | no | **NONE** |
| team_settings_changed | Team controller | 3 | no | **NONE** |
| team_leadership_changed | Team controller | 2 | no | **NONE** |
| member_approval_initiated | background_approval_api.py:192 | **4** | no | none |
| member_approval_completed | background_approval_api.py:202 | 2 | no | none |

**Worst multi-subscriber-collapse case = `member_approval_initiated` (4 subscribers →
`handle_customer_creation`, `handle_chapter_assignment`, `handle_iban_history_creation`,
`handle_user_account_creation`).** With a single `job_id` per (event, entity) and real dedup,
3 of 4 are silently dropped — which is why **per-subscriber `job_id` is mandatory**.

Note the **team-events bulk-guard gap**: `team_events.py` has no `in_bulk_import`/`bulk_*` skip,
unlike the member/chapter wrappers. Team events are the most likely real contributor to a large
after-commit flush under production bulk team operations.

## 4. Severity of the current no-op: LOW

- **Duplicate jobs** (no dedup): rapid repeat events enqueue duplicate jobs, but subscribers are
  defensively idempotent (`handle_customer_creation` early-returns if `member.customer` set +
  retries; chapter assignment activates a *pending* membership; IBAN history already de-duped).
  At worst wasted work — no money/data-loss bug.
- **Read-stale race** (enqueue-before-commit, since `delay` is a no-op): a worker could start
  before the emitting txn commits. Real but low-frequency (worker latency usually exceeds commit;
  subscribers re-`get_doc`+retry). `enqueue_after_commit=True` is the targeted fix.
- **Collapse** does NOT exist today (no dedup → all subscribers run); it becomes a risk only if
  the fix adds `deduplicate=True` without a per-subscriber `job_id`.

→ Worth fixing (correctness), but **not urgent**; do it as its own small, attributable PR.

## 5. Implementation plan

### Task 1 — Fix the enqueue call (`event_emitter.py:59-68`)

Re-apply the `9bf6ba38` shape (identical to the in-repo references `invoice_events.py:128-152`,
`contribution_amendment_request.py:433`):

```python
frappe.enqueue(
    method=subscriber,
    queue="short",
    job_id=f"{job_prefix}_{event_name}_{entity_name}_{subscriber}",  # per-subscriber -> no collapse
    deduplicate=True,
    enqueue_after_commit=True,
    timeout=300,
    **extra_kwargs,  # is_bulk_import, only when the bulk flag is set
    **{"event_name": event_name, "event_data": event_data},
)
```

- **Drop** `job_name` / `dedupe` / `delay` from the enqueue call. Leave the `delay` **parameter**
  on `emit_event`'s signature (approval_events.py passes `delay=2`) marked unused, to avoid
  touching callers — or clean up that one caller. Either is fine.
- Keep the `run_events_synchronously` test affordance unchanged.

**TDD:** watch `test_emit_event_enqueues_when_not_sync` (rewritten, Task 3) go RED→GREEN.

### Task 2 — Close the team-events bulk-guard gap (`team_events.py`)

Add the same `in_bulk_import`/`bulk_*` skip guard the member (`member_events.py:34-37`) and
chapter (`chapter_events.py:36-39`) wrappers use, so bulk team operations don't flush a large
after-commit closure set. Cheap, strictly-safer, and removes the one place `enqueue_after_commit`
could plausibly cause a production throughput spike.

### Task 3 — Tests

- **Rewrite** `tests/events/test_approval_events_coverage.py::test_emit_event_enqueues_when_not_sync`
  (lines 189-211): assert `job_id == f"{prefix}_{event}_{entity}_{subscriber}"`, `deduplicate is
  True`, `enqueue_after_commit is True`, and `job_name`/`delay` absent. Patch
  `verenigingen.events.event_emitter.frappe.enqueue`.
- **Restore** `test_emit_event_enqueues_one_job_per_subscriber` (deleted by the revert): emit an
  event with ≥2 subscribers, assert one enqueue per subscriber with **distinct** `job_id`s (the
  C1 guard).
- **Add a bulk-with-commits test that actually exercises `emit_event`** — the existing
  `test_bulk_account_creation` does NOT (events are gated off in test mode, which is exactly why
  the earlier "regression" could only be guessed at). Drive N events + a real `frappe.db.commit()`
  (e.g. via a chapter/team save loop, or with `run_events_synchronously` off and the in-test gate
  bypassed) and assert (a) all subscriber `job_id`s are distinct/present and (b) no MariaDB
  lock/timeout. This is the missing guard for the thing the prior session only hypothesized.

### Task 4 — Verify + land

1. Kill any stray `frappe worker` before benchmarking locally (they were the confirmed local
   cause of bulk lock-timeout noise). Run `test_bulk_account_creation` before/after on
   `test_site_1` and confirm **timing parity** — since the test emits zero events, timing must be
   identical; if it isn't, the regression is elsewhere and this confirms the revert was a red
   herring.
2. Land as its own small PR (independent of financial-history work) so CI bulk-suite behavior is
   attributable.

## 6. Test surface (robust — no change needed)

`test_member_events_coverage.py`, `test_team_events_coverage.py`, `test_chapter_subscribers.py`
use the `run_events_synchronously` inline affordance / import subscribers directly, so they don't
assert enqueue kwargs and won't break.

## 7. Open questions / follow-ups (do NOT block #168 on these)

- **The `test_bulk_account_creation` lock-timeout root cause is still unidentified.** Proven: it
  is NOT `emit_event`. Strong suspicion: real row-lock contention in the bulk ACR/tracker flow
  (`account_creation_api.py:472-480` does a bulk `UPDATE ... WHERE name IN (...)` + `commit`)
  racing test-enqueued jobs when a worker is present. **If the timeout recurs in CI, investigate
  the bulk flow's own locking separately** — it is a pre-existing flake, not caused by this work.
- **Two parallel payment-history mechanisms** (`OptimizedMemberQueries` vs
  `FinancialHistoryBatchProcessor`) remain unreconciled — larger, separate debt (noted in the
  #167 spec).
- `expense_events.py::_emit_expense_event` (lines 217-251) still uses cosmetic `job_name` with no
  dedup — adjacent tech-debt on a different (unwired-through-`emit_event`) path; not #168.

## 8. Session learnings folded in (for future readers)

- **Frappe v16 enqueue:** `delay`/`dedupe`/`job_name` are no-ops for scheduling/dedup; use
  `job_id` + `deduplicate=True` + `enqueue_after_commit=True` (memory `frappe-enqueue-delay-dedupe-noop`).
- **Per-subscriber `job_id`** is mandatory whenever an emitter fans out to multiple subscribers
  and you add real dedup — otherwise they collapse to one job.
- **Local test repro is unreliable when `bench` workers run** — they steal test-enqueued jobs and
  produce their own lock-timeout noise. CI (worker-free) is the clean judge; but a single CI A/B
  on a flaky suite is not proof of causation — verify with a runtime diagnostic (does the code
  path even execute?) before attributing.
- **A genuine MariaDB deadlock destroys savepoints** (memory `deadlock-destroys-savepoints`) —
  relevant if this or the reconciliation work adds savepoints.
