"""Execution engine for Mollie Bulk Run.

Flow per run:
1. ``execute_bulk_run(run_name)`` is called by the background worker.
2. If the child table is empty, fetch Mollie payments for the run's date range,
   sort ASC by ``paid_at``, insert one child row per payment (Pending).
3. Iterate child rows from ``last_processed_index``. For each:
   - check ``cancel_requested``; if set, mark Cancelled and exit.
   - call ``MolliePaymentOrchestrator.process_payment(payment_id)``.
   - write the outcome back to the child row.
   - every 10 rows, commit, persist ``last_processed_index``, and publish
     progress via ``frappe.publish_realtime``.
4. On normal completion, set status=Completed.
5. Exceptions per payment are caught and recorded as row failures; the run
   continues. An uncaught exception at the run level sets status=Failed.

Resume: re-enqueueing a Failed/Timed Out/Cancelled run picks up from
``last_processed_index``. Rows already Pending or Failed (with attempts <
MAX_ATTEMPTS_PER_PAYMENT) get retried; rows at the attempt cap are marked
Blocked and skipped.
"""

from __future__ import annotations

from datetime import datetime, timezone

import frappe
from frappe import _
from frappe.utils import now_datetime

from verenigingen.verenigingen_payments.doctype.mollie_bulk_run.mollie_bulk_run import (
    ACTIVE_STATUSES,
    MAX_ATTEMPTS_PER_PAYMENT,
)

PROGRESS_EVENT = "mollie_bulk_run_progress"
PROGRESS_CHECKPOINT_INTERVAL = 10
JOB_TIMEOUT_SECONDS = 14400  # 4 hours


# ---------------------------------------------------------------------------
# Entry points (called by whitelisted API / resume flow)
# ---------------------------------------------------------------------------


def enqueue_run(run_name: str) -> str:
    """Queue ``execute_bulk_run`` on the long-running worker and stamp the job id."""
    job = frappe.enqueue(
        "verenigingen.verenigingen_payments.services.mollie_bulk_run_service.execute_bulk_run",
        queue="long",
        timeout=JOB_TIMEOUT_SECONDS,
        job_name=f"mollie_bulk_run::{run_name}",
        run_name=run_name,
    )
    job_id = getattr(job, "id", None) or str(job)
    frappe.db.set_value("Mollie Bulk Run", run_name, "job_id", job_id, update_modified=False)
    return job_id


def execute_bulk_run(run_name: str) -> None:
    """Worker entry point — executes a run start-to-finish."""
    run = frappe.get_doc("Mollie Bulk Run", run_name)

    try:
        if not run.payments:
            _fetch_and_populate_payments(run)

        _process_rows(run)

        if run.cancel_requested:
            _finalize(run, status="Cancelled")
        else:
            _finalize(run, status="Completed")

    except Exception as exc:
        frappe.log_error(
            frappe.get_traceback(),
            f"Mollie Bulk Run failed: {run_name}",
        )
        _finalize(run, status="Failed", error=str(exc))


# ---------------------------------------------------------------------------
# Fetch phase
# ---------------------------------------------------------------------------


def _fetch_and_populate_payments(run) -> None:
    """Pull all Mollie payments in the run's date range, sort by paid_at ASC,
    and populate the child table."""
    run.db_set("status", "Fetching", update_modified=False)
    run.db_set("started_at", now_datetime(), update_modified=False)
    frappe.db.commit()

    payments = _list_mollie_payments(run.date_from, run.date_to)
    payments.sort(key=lambda p: p.get("paid_at") or p.get("created_at") or "")

    for p in payments:
        run.append(
            "payments",
            {
                "payment_id": p["id"],
                "paid_at": _parse_datetime(p.get("paid_at") or p.get("created_at")),
                "amount": p.get("amount_value") or 0,
                "currency": p.get("currency"),
                "member": p.get("member"),
                "row_status": "Pending",
                "attempts": 0,
            },
        )

    run.db_set("total_payments", len(payments), update_modified=False)
    # Security: Background worker context, no session user. Access gate is at the
    # whitelisted entry points (start_bulk_run, resume_bulk_run).
    run.save(ignore_permissions=True)
    frappe.db.commit()


def _list_mollie_payments(date_from, date_to) -> list[dict]:
    """Fetch all Mollie payments with ``paid_at`` in [date_from, date_to].

    Uses the Mollie client's pagination API. ``paid_at`` is what we care about
    for historical imports (created_at can precede paid_at by days for bank
    transfers). We still apply an early-termination heuristic on created_at
    to bound the pagination walk.
    """
    from verenigingen.verenigingen_payments.mollie.core.client import MollieClient
    from verenigingen.verenigingen_payments.mollie.utils.member_payment_matcher import (
        get_member_payment_matcher,
    )

    client = MollieClient().sdk_client
    matcher = get_member_payment_matcher()

    date_from_str = str(date_from)
    date_to_str = str(date_to)

    params = {"limit": 250}
    collected: list[dict] = []
    seen: set[str] = set()
    consecutive_older = 0

    while True:
        page = client.payments.list(**params)
        batch = list(page)
        if not batch:
            break

        for payment in batch:
            if payment.id in seen:
                continue
            seen.add(payment.id)

            created_at = getattr(payment, "created_at", "") or ""
            created_date = created_at[:10]
            paid_at = getattr(payment, "paid_at", None)
            paid_date = str(paid_at)[:10] if paid_at else created_date

            if created_date and created_date < date_from_str:
                consecutive_older += 1
                if consecutive_older >= 100:
                    return collected
                continue
            consecutive_older = 0

            if paid_date < date_from_str or paid_date > date_to_str:
                continue

            amount = payment.amount or {}
            member_info = matcher.find_member_for_payment(payment)
            collected.append(
                {
                    "id": payment.id,
                    "paid_at": paid_at,
                    "created_at": created_at,
                    "amount_value": float(amount.get("value") or 0),
                    "currency": amount.get("currency"),
                    "status": payment.status,
                    "member": member_info["name"] if member_info else None,
                }
            )

        if page.has_next() and batch:
            params["from"] = batch[-1].id
        else:
            break

    return collected


def _parse_datetime(value):
    """Parse Mollie's ISO-8601 datetime string into a MariaDB-friendly naive datetime.

    Mollie returns tz-aware values like '2022-11-02T17:55:20+00:00'; MariaDB's
    DATETIME column rejects the tz suffix. Convert to UTC and strip tzinfo so
    the value persists cleanly.
    """
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


# ---------------------------------------------------------------------------
# Processing phase
# ---------------------------------------------------------------------------


def _process_rows(run) -> None:
    """Iterate child rows from ``last_processed_index`` and call the orchestrator.

    To avoid TimestampMismatchError from parallel set_value + save writes, we
    save the whole run doc once per checkpoint and reload afterwards. The
    cancel flag is polled via a cheap single-column DB lookup on every iteration.
    """
    from verenigingen.verenigingen_payments.services.mollie_payment_orchestrator import (
        get_payment_orchestrator,
    )

    orchestrator = get_payment_orchestrator()

    if run.status != "Processing":
        run.db_set("status", "Processing", update_modified=False)
        run.reload()

    total = len(run.payments)
    start_idx = run.last_processed_index or 0
    succeeded = run.total_succeeded or 0
    skipped = run.total_skipped or 0
    failed = run.total_failed or 0

    idx = start_idx
    while idx < total:
        # Cheap per-iteration cancel check (single-column read, no full reload)
        if _cancel_requested(run.name):
            run.cancel_requested = 1
            break

        row = run.payments[idx]

        if row.row_status == "Success":
            idx += 1
            continue

        if (row.attempts or 0) >= MAX_ATTEMPTS_PER_PAYMENT and row.row_status != "Success":
            row.row_status = "Blocked"
            idx += 1
            continue

        row.attempts = (row.attempts or 0) + 1

        # Idempotency shortcut: if a Bank Transaction already exists for this
        # payment, the import side of the pipeline is done — skip entirely.
        # This avoids the orchestrator's "try to retrofit PE/SI" path which
        # can report Failed when member resolution or invoice matching
        # stumbles on an already-imported orphan.
        existing_bt = frappe.db.get_value(
            "Bank Transaction",
            {"reference_number": row.payment_id, "docstatus": ["!=", 2]},
            "name",
        )
        if existing_bt:
            row.bank_transaction = existing_bt
            row.row_status = "Skipped"
            row.message = f"Bank Transaction {existing_bt} already exists for {row.payment_id}"
            row.processed_at = now_datetime()
            skipped += 1
            idx += 1
            if idx % PROGRESS_CHECKPOINT_INTERVAL == 0 or idx == total:
                _checkpoint(run, idx, succeeded, skipped, failed, total)
                run.reload()
            continue

        try:
            result = orchestrator.process_payment(row.payment_id)
            _apply_result_to_row(row, result)
            if row.row_status == "Success":
                succeeded += 1
            elif row.row_status == "Skipped":
                skipped += 1
            elif row.row_status == "Failed":
                failed += 1
        except Exception as exc:
            row.row_status = "Failed"
            row.message = f"Unhandled exception: {exc}"[:1000]
            row.processed_at = now_datetime()
            failed += 1
            frappe.log_error(
                frappe.get_traceback(),
                f"Mollie Bulk Run {run.name} row {row.payment_id}",
            )

        idx += 1

        if idx % PROGRESS_CHECKPOINT_INTERVAL == 0 or idx == total:
            _checkpoint(run, idx, succeeded, skipped, failed, total)
            run.reload()

    # Final flush for any partial batch (cancel mid-chunk, or < CHECKPOINT_INTERVAL rows)
    if idx % PROGRESS_CHECKPOINT_INTERVAL != 0:
        _checkpoint(run, idx, succeeded, skipped, failed, total)
        run.reload()


def _cancel_requested(run_name: str) -> bool:
    return bool(frappe.db.get_value("Mollie Bulk Run", run_name, "cancel_requested"))


def _apply_result_to_row(row, result) -> None:
    """Translate PaymentProcessingResult into the child row."""
    row.bank_transaction = result.bank_transaction
    row.payment_entry = result.payment_entry
    row.sales_invoice = result.sales_invoice
    row.processed_at = now_datetime()
    if result.member:
        row.member = result.member

    # Orchestrator statuses: success, already_processed, skipped, needs_review,
    # partial (BT xor PE present but not both), error (no docs, or unresolvable).
    # "partial" with a BT means the import side is done — treat as Skipped, not Failed.
    if result.status in ("success", "already_processed"):
        row.row_status = "Success"
    elif result.status in ("skipped", "needs_review"):
        row.row_status = "Skipped"
    elif result.status == "partial":
        row.row_status = "Skipped" if result.bank_transaction else "Failed"
    elif result.status == "error":
        row.row_status = "Skipped" if result.bank_transaction else "Failed"
    else:
        row.row_status = "Failed"

    if result.error:
        row.message = result.error[:1000]
    elif result.skipped_reason:
        row.message = result.skipped_reason[:1000]
    elif result.actions_taken:
        row.message = "; ".join(result.actions_taken)[:1000]
    else:
        row.message = result.status


def _checkpoint(run, processed_index: int, succeeded: int, skipped: int, failed: int, total: int) -> None:
    """Persist progress and notify subscribers."""
    # Security: Background worker context, no session user. Access gate at whitelisted entry points.
    run.save(ignore_permissions=True)
    frappe.db.set_value(
        "Mollie Bulk Run",
        run.name,
        {
            "last_processed_index": processed_index,
            "total_succeeded": succeeded,
            "total_skipped": skipped,
            "total_failed": failed,
        },
        update_modified=False,
    )
    frappe.db.commit()

    percentage = int(100 * processed_index / total) if total else 0
    frappe.publish_realtime(
        PROGRESS_EVENT,
        {
            "run_name": run.name,
            "current": processed_index,
            "total": total,
            "percentage": percentage,
            "succeeded": succeeded,
            "skipped": skipped,
            "failed": failed,
        },
        user=run.triggered_by or frappe.session.user,
    )


# ---------------------------------------------------------------------------
# Finalization
# ---------------------------------------------------------------------------


def _finalize(run, status: str, error: str | None = None) -> None:
    updates = {
        "status": status,
        "completed_at": now_datetime(),
    }
    if error:
        updates["last_error"] = error
    frappe.db.set_value("Mollie Bulk Run", run.name, updates, update_modified=False)
    frappe.db.commit()

    frappe.publish_realtime(
        PROGRESS_EVENT,
        {
            "run_name": run.name,
            "status": status,
            "final": True,
        },
        user=run.triggered_by or frappe.session.user,
    )


# ---------------------------------------------------------------------------
# Stale run cleanup (nightly scheduler)
# ---------------------------------------------------------------------------


def mark_stale_runs_timed_out() -> None:
    """Nightly task: any run stuck in an active status for >5h gets marked Timed Out.

    This lets the user re-enqueue it via ``resume_bulk_run``. Registered in
    hooks under scheduler_events.daily.
    """
    cutoff = frappe.utils.add_to_date(now_datetime(), hours=-5)
    stale = frappe.get_all(
        "Mollie Bulk Run",
        filters=[
            ["status", "in", list(ACTIVE_STATUSES)],
            ["modified", "<", cutoff],
        ],
        pluck="name",
    )
    for name in stale:
        frappe.db.set_value(
            "Mollie Bulk Run",
            name,
            {
                "status": "Timed Out",
                "last_error": "Marked Timed Out by scheduler (no activity for >5h)",
            },
            update_modified=False,
        )
    if stale:
        frappe.db.commit()
