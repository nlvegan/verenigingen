# Bulk Operation Tracker contention fix (#172) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the `Bulk Operation Tracker` hot-row read-modify-write contention that produces `TimestampMismatchError` storms and `(1205, 'Lock wait timeout exceeded')`.

**Architecture:** The tracker row stores only *atomic aggregates* (counters, status, timestamps). Per-batch progress becomes a single atomic SQL `UPDATE ... SET x = x + n` (no ORM `save()`, no version check). Per-request state (retry list, error summary) is *derived at read-time* from the linked `Account Creation Request` (ACR) rows — the ACR is the single source of truth (it already has `status`, `failure_reason`, and a `bulk_operation_tracker` link). Rate/ETA are computed at read-time. The now-moot 32s-sleep retry special-case for the tracker is removed.

**Tech Stack:** Frappe v16 (Python), MariaDB, `frappe.db.sql` parameterised queries, EnhancedTestCase.

## Global Constraints

- Test only on `test_site_1` (never veg11). Run: `cd ~/frappe-bench && bench --site test_site_1 run-tests --app verenigingen --module <mod>`.
- No read-modify-write (`load → mutate → save()`) on the `Bulk Operation Tracker` row in any per-batch path.
- Parameterised SQL only (`%s` / named params) — never f-string interpolation of values.
- ACR failed status literal = `"Failed"`. ACR link field = `bulk_operation_tracker`. ACR error field = `failure_reason`.
- Preserve the public read API shape: `get_operation_progress` keys, `get_active_operations` fields, `get_retry_requests()` returning a `list[str]` of ACR names.
- Frequent commits; TDD (RED → GREEN) per task.

---

### Task 1: Atomic counter increments + atomic completion in `update_progress`

**Files:**
- Modify: `verenigingen/verenigingen/doctype/bulk_operation_tracker/bulk_operation_tracker.py` (`update_progress`, `_complete_operation`)
- Test: `verenigingen/verenigingen/doctype/bulk_operation_tracker/test_bulk_operation_tracker.py`

**Interfaces:**
- Produces: `update_progress(self, batch_number: int, batch_results: dict) -> None` — now writes via atomic SQL, no `save()`. Reloads `self` at the end so the in-memory doc reflects DB.

- [ ] **Step 1: Write the failing test** — two stale in-memory copies both post progress; totals must be correct and no `TimestampMismatchError`.

```python
def test_concurrent_update_progress_is_atomic_no_timestamp_conflict(self):
    tracker = BulkOperationTracker.create_tracker(
        operation_type="Account Creation", total_records=100, batch_size=25
    )
    # Two references loaded at the SAME version (simulates two batch jobs).
    a = frappe.get_doc("Bulk Operation Tracker", tracker.name)
    b = frappe.get_doc("Bulk Operation Tracker", tracker.name)
    a.update_progress(1, {"completed": 25, "failed": 0})
    # b is now stale; old code would raise TimestampMismatchError on save().
    b.update_progress(2, {"completed": 20, "failed": 5})
    fresh = frappe.get_doc("Bulk Operation Tracker", tracker.name)
    self.assertEqual(fresh.successful_records, 45)
    self.assertEqual(fresh.failed_records, 5)
    self.assertEqual(fresh.processed_records, 50)
    self.assertEqual(fresh.current_batch, 2)  # GREATEST(1, 2)

def test_update_progress_marks_complete_once_when_total_reached(self):
    tracker = BulkOperationTracker.create_tracker(
        operation_type="Account Creation", total_records=50, batch_size=25
    )
    tracker.db_set("status", "Processing")
    a = frappe.get_doc("Bulk Operation Tracker", tracker.name)
    b = frappe.get_doc("Bulk Operation Tracker", tracker.name)
    a.update_progress(1, {"completed": 25, "failed": 0})
    b.update_progress(2, {"completed": 25, "failed": 0})
    fresh = frappe.get_doc("Bulk Operation Tracker", tracker.name)
    self.assertEqual(fresh.processed_records, 50)
    self.assertEqual(fresh.status, "Completed")
    self.assertIsNotNone(fresh.completed_at)
```

- [ ] **Step 2: Run to verify RED**

Run: `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.verenigingen.doctype.bulk_operation_tracker.test_bulk_operation_tracker`
Expected: FAIL — `TimestampMismatchError` on the second `update_progress` (current read-modify-write path).

- [ ] **Step 3: Implement atomic `update_progress`** — replace the body with atomic SQL. Full replacement:

```python
def update_progress(self, batch_number: int, batch_results: dict):
    """Atomically fold one batch's results into the tracker counters.

    Uses a single UPDATE ... SET x = x + n rather than a load->mutate->save()
    so overlapping batch completions cannot raise TimestampMismatchError or
    hold row locks across a retry-sleep (see issue #172).
    """
    inc_success = cint(batch_results.get("completed", 0))
    inc_failed = cint(batch_results.get("failed", 0))
    inc_processed = inc_success + inc_failed

    frappe.db.sql(
        """
        UPDATE `tabBulk Operation Tracker`
        SET successful_records = successful_records + %(s)s,
            failed_records     = failed_records + %(f)s,
            processed_records  = processed_records + %(p)s,
            current_batch      = GREATEST(current_batch, %(batch)s),
            modified           = %(now)s,
            modified_by        = %(user)s
        WHERE name = %(name)s
        """,
        {
            "s": inc_success, "f": inc_failed, "p": inc_processed,
            "batch": cint(batch_number), "now": now(),
            "user": frappe.session.user, "name": self.name,
        },
    )
    # Single-winner completion: only the batch that pushes processed >= total,
    # while still Processing, flips the status.
    self._complete_operation_if_done()
    self.reload()  # keep the in-memory doc consistent for callers
    frappe.logger().info(
        f"Bulk operation {self.name} progress: batch {batch_number}, "
        f"processed {self.processed_records}/{self.total_records}"
    )
```

Add the helper and delete the old `_complete_operation`, `_update_batch_details`, `_update_retry_queue`, `_update_error_summary` calls from this path:

```python
def _complete_operation_if_done(self):
    """Atomically mark the operation complete exactly once."""
    frappe.db.sql(
        """
        UPDATE `tabBulk Operation Tracker`
        SET status = CASE
                WHEN failed_records > 0 AND successful_records = 0 THEN 'Failed'
                ELSE 'Completed' END,
            completed_at = %(now)s,
            current_batch = total_batches,
            modified = %(now)s, modified_by = %(user)s
        WHERE name = %(name)s
          AND processed_records >= total_records
          AND status = 'Processing'
        """,
        {"now": now(), "user": frappe.session.user, "name": self.name},
    )
```

- [ ] **Step 4: Run to verify GREEN**

Run: same module command.
Expected: PASS (both new tests + existing tracker tests).

- [ ] **Step 5: Commit**

```bash
git add verenigingen/verenigingen/doctype/bulk_operation_tracker/
git commit -m "fix(#172): atomic counter/completion updates in BulkOperationTracker.update_progress"
```

---

### Task 2: Derive retry list + error summary from linked ACRs

**Files:**
- Modify: `verenigingen/verenigingen/doctype/bulk_operation_tracker/bulk_operation_tracker.py` (`get_retry_requests`, add `get_error_summary`, drop `clear_retry_queue` write, remove `_update_retry_queue`/`_update_error_summary`)
- Modify: `verenigingen/verenigingen/doctype/bulk_operation_tracker/bulk_operation_tracker.py` (`get_operation_progress` returns derived `error_summary`)
- Test: `test_bulk_operation_tracker.py`

**Interfaces:**
- Produces: `get_retry_requests(self) -> list[str]` (failed ACR names, derived). `get_error_summary(self, limit=100) -> list[str]` (ACR failure_reasons, derived).

- [ ] **Step 1: Write the failing test**

```python
def test_get_retry_requests_derives_from_failed_acrs(self):
    tracker = BulkOperationTracker.create_tracker(
        operation_type="Account Creation", total_records=2, batch_size=25
    )
    m1 = self.create_test_member(first_name="Rq1", last_name="X", birth_date="1990-01-01")
    m2 = self.create_test_member(first_name="Rq2", last_name="Y", birth_date="1990-01-01")
    failed = self._make_acr(m1, tracker.name, status="Failed", failure_reason="boom-1")
    self._make_acr(m2, tracker.name, status="Completed")
    self.assertEqual(tracker.get_retry_requests(), [failed])
    self.assertIn("boom-1", tracker.get_error_summary())
```

Add an `_make_acr` helper in the test class that inserts a minimal Account Creation Request linked to the tracker with the given status/failure_reason.

- [ ] **Step 2: Run to verify RED** — FAIL (`get_error_summary` missing; `get_retry_requests` reads the empty JSON field).

- [ ] **Step 3: Implement derive**

```python
def get_retry_requests(self) -> List[str]:
    """Failed ACRs linked to this tracker (ACR status is the source of truth)."""
    return frappe.get_all(
        "Account Creation Request",
        filters={"bulk_operation_tracker": self.name, "status": "Failed"},
        pluck="name",
        order_by="creation",
    )

def get_error_summary(self, limit: int = 100) -> List[str]:
    rows = frappe.get_all(
        "Account Creation Request",
        filters={"bulk_operation_tracker": self.name, "status": "Failed"},
        fields=["name", "failure_reason"],
        order_by="creation",
        limit=limit,
    )
    return [f"{r.name}: {r.failure_reason or 'Unknown error'}" for r in rows]
```

Remove `_update_retry_queue` and `_update_error_summary` (no longer called). In `get_operation_progress`, add `"error_summary": "\n".join(tracker.get_error_summary())` and keep `"retry_queue_count": len(tracker.get_retry_requests())`. Make `clear_retry_queue()` a no-op that logs (retry list is derived; kept for API compatibility).

- [ ] **Step 4: Run to verify GREEN.**

- [ ] **Step 5: Commit** — `fix(#172): derive retry list + error summary from linked ACRs`

---

### Task 3: Point `bulk_retry_processor` at the derived source of truth

**Files:**
- Modify: `verenigingen/utils/bulk_retry_processor.py` (`process_retry_queues` filter, `get_retry_queue_status` filter, drop the manual `tracker.retry_queue = ...` rewrite at ~line 128)
- Test: `verenigingen/tests/.../test_bulk_retry_processor*.py` (locate existing; else add a focused test)

**Interfaces:**
- Consumes: `tracker.get_retry_requests()` from Task 2.

- [ ] **Step 1: Write the failing test** — a tracker with a Failed ACR is discovered by `get_retry_queue_status`; a tracker with only Completed ACRs is not.

```python
def test_retry_status_finds_trackers_with_failed_acrs(self):
    from verenigingen.utils.bulk_retry_processor import get_retry_queue_status
    tracker = BulkOperationTracker.create_tracker(
        operation_type="Account Creation", total_records=1, batch_size=25
    )
    tracker.db_set("failed_records", 1)
    m = self.create_test_member(first_name="Rp", last_name="X", birth_date="1990-01-01")
    self._make_acr(m, tracker.name, status="Failed", failure_reason="x")
    names = [q["tracker_name"] for q in get_retry_queue_status().get("queues", [])]
    self.assertIn(tracker.name, names)
```

(Adjust the result-shape access to match the real `get_retry_queue_status` return.)

- [ ] **Step 2: Run to verify RED** — FAIL (current filter is `retry_queue != ""`, which is now always empty).

- [ ] **Step 3: Implement** — change both filters from `{"retry_queue": ["!=", ""]}` to `{"failed_records": [">", 0]}`; delete the `tracker.retry_queue = json.dumps(...)` line (ACR status now drives it — a retried-and-fixed ACR flips out of `status='Failed'` automatically).

- [ ] **Step 4: Run to verify GREEN.**

- [ ] **Step 5: Commit** — `fix(#172): bulk_retry_processor uses failed_records + derived retry list`

---

### Task 4: Read-time rate/ETA; stop per-batch `batch_details` write

**Files:**
- Modify: `bulk_operation_tracker.py` (`get_operation_progress`, `get_active_operations`, remove `_update_batch_details`; keep `_calculate_processing_rate`/`_calculate_estimated_completion` but call them only from `validate()` at create/start)
- Test: `test_bulk_operation_tracker.py`

**Design note:** `batch_details` has **no readers** (not in `get_operation_progress`, no UI). Per the issue's chosen scope ("append-only child rows or read-time computation"), and because per-batch timing has no ACR source, we **drop the per-batch write** (the contention source) and retain per-batch timing in the existing `frappe.logger().info` line. The `batch_details` column is kept (no migration) but left unwritten/deprecated. *(If dedicated per-batch observability is wanted, a follow-up can add an append-only `Bulk Operation Batch Detail` child DocType — out of scope here.)*

- [ ] **Step 1: Write the failing test** — `update_progress` does not touch `batch_details`; `get_operation_progress` still returns a numeric `processing_rate`.

```python
def test_update_progress_does_not_write_batch_details_blob(self):
    tracker = BulkOperationTracker.create_tracker(
        operation_type="Account Creation", total_records=25, batch_size=25
    )
    tracker.db_set("status", "Processing")
    tracker.update_progress(1, {"completed": 25, "failed": 0})
    self.assertFalse(frappe.db.get_value("Bulk Operation Tracker", tracker.name, "batch_details"))
```

- [ ] **Step 2: Run to verify RED** (current code appends to `batch_details`).

- [ ] **Step 3: Implement** — ensure `update_progress` (Task 1) never touches `batch_details`; delete `_update_batch_details`. Confirm `get_operation_progress` computes `processing_rate` at read-time (compute from `started_at` + `processed_records` if the stored field is empty).

- [ ] **Step 4: Run to verify GREEN.**

- [ ] **Step 5: Commit** — `fix(#172): drop contended batch_details write; read-time rate/ETA`

---

### Task 5: Remove the 32s-sleep retry special-case for Bulk Operation Tracker

**Files:**
- Modify: `verenigingen/utils/secure_operations.py:384-448` (`_execute_document_operation` save path)
- Test: `verenigingen/tests/.../test_*secure_operations*.py` (locate; else assert behaviourally)

**Design note:** With progress off `save()`, the tracker no longer hits this retry path in the hot loop. `start_operation` still uses `save()` once (low contention). Remove the Bulk-Operation-Tracker-specific `max_retries=10` + 32s backoff; keep the generic `TimestampMismatchError` retry for other doctypes (e.g. `API Audit Log`) unchanged, and its sleep bounded/short.

- [ ] **Step 1: Write/adjust the failing test** — assert the tracker no longer receives the 10-retry/32s special-case (e.g. patch `time.sleep` and assert it is not called with values > a small bound for a tracker save conflict), OR assert the special-case branch is gone via a focused unit on `_execute_document_operation`.

- [ ] **Step 2: Run to verify RED.**

- [ ] **Step 3: Implement** — collapse the `doc.doctype == "Bulk Operation Tracker"` special-casing; use one modest retry policy for the remaining monitoring doctypes with a short capped sleep (e.g. ≤ 2s).

- [ ] **Step 4: Run to verify GREEN** — plus re-run any `secure_operations` tests.

- [ ] **Step 5: Commit** — `fix(#172): drop 32s-sleep tracker retry amplifier in secure_operations`

---

### Task 6: Full verification

- [ ] **Step 1:** `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.verenigingen.doctype.bulk_operation_tracker.test_bulk_operation_tracker` → PASS
- [ ] **Step 2:** `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.member.test_bulk_account_creation` → PASS (0 lock-timeouts)
- [ ] **Step 3:** Re-run the two scratchpad repro scripts; confirm the atomic path no longer raises `TimestampMismatchError` (the 2-connection FOR-UPDATE lock repro is expected to still show a lock — that is inherent to any concurrent same-row write; the fix removes the *read-modify-write conflicts* and the *lock-holding sleep*, not row locks per se).
- [ ] **Step 4:** `bench --site test_site_1 migrate` (no schema changes expected; confirms clean).
- [ ] **Step 5:** ruff + black on changed files; then push + open PR (Closes #172). Note the deliberate `batch_details`-drop decision and the optional child-table follow-up.
