"""Whitelisted endpoints for the Mollie Bulk Run workflow.

All endpoints gated to the same roles that already access the Mollie
payment processing page (Administrator / Verenigingen Administrator /
Verenigingen Staff / System Manager / Treasurer).
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import getdate

from verenigingen.utils.security.api_security_framework import OperationType, high_security_api
from verenigingen.verenigingen_payments.doctype.mollie_bulk_run.mollie_bulk_run import (
    TERMINAL_STATUSES,
)
from verenigingen.verenigingen_payments.services.mollie_bulk_run_service import enqueue_run


def _check_access() -> None:
    from verenigingen.templates.pages.mollie_payment_processing import (
        has_payment_processing_access,
    )

    if not has_payment_processing_access():
        frappe.throw(_("You don't have permission to manage Mollie bulk runs"), frappe.PermissionError)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def start_bulk_run(date_from: str, date_to: str, batch_strategy: str = "Month") -> dict:
    """Create a new Mollie Bulk Run and enqueue its worker."""
    _check_access()

    date_from_d = getdate(date_from)
    date_to_d = getdate(date_to)
    if date_from_d > date_to_d:
        frappe.throw(_("From Date must be on or before To Date"))

    if batch_strategy not in ("Month", "Week", "Day"):
        frappe.throw(_("Invalid batch_strategy"))

    run = frappe.get_doc(
        {
            "doctype": "Mollie Bulk Run",
            "date_from": date_from_d,
            "date_to": date_to_d,
            "batch_strategy": batch_strategy,
            "status": "Queued",
            "triggered_by": frappe.session.user,
        }
    )
    # Security: Access gate enforced by _check_access above (Admin / Staff / Treasurer roles).
    # Insert bypass needed because Mollie Bulk Run has no explicit Create perm for Staff role,
    # but the action is authorized by the role-based API gate.
    run.insert(ignore_permissions=True)
    frappe.db.commit()

    job_id = enqueue_run(run.name)

    return {"run_name": run.name, "job_id": job_id}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.REPORTING)
def get_bulk_run_status(run_name: str) -> dict:
    """Return progress counters for a run. Called by the UI polling loop."""
    _check_access()

    row = frappe.db.get_value(
        "Mollie Bulk Run",
        run_name,
        [
            "name",
            "status",
            "date_from",
            "date_to",
            "batch_strategy",
            "total_payments",
            "total_succeeded",
            "total_skipped",
            "total_failed",
            "last_processed_index",
            "cancel_requested",
            "started_at",
            "completed_at",
            "last_error",
        ],
        as_dict=True,
    )
    if not row:
        frappe.throw(_("Run {0} not found").format(run_name), frappe.DoesNotExistError)

    total = row["total_payments"] or 0
    processed = row["last_processed_index"] or 0
    row["percentage"] = int(100 * processed / total) if total else 0
    return row


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def request_cancel(run_name: str) -> dict:
    """Signal the worker to stop at the next checkpoint."""
    _check_access()
    run = frappe.get_doc("Mollie Bulk Run", run_name)
    run.mark_cancel_requested()
    return {"run_name": run.name, "cancel_requested": True}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def resume_bulk_run(run_name: str) -> dict:
    """Re-enqueue a Failed/Timed Out/Cancelled run from its last checkpoint."""
    _check_access()

    run = frappe.get_doc("Mollie Bulk Run", run_name)
    if run.status not in ("Failed", "Timed Out", "Cancelled"):
        frappe.throw(
            _(
                "Cannot resume a run in status {0} — only Failed, Timed Out, or Cancelled are resumable"
            ).format(run.status)
        )

    run.db_set("cancel_requested", 0, update_modified=False)
    run.db_set("last_error", None, update_modified=False)
    run.db_set("status", "Queued", update_modified=False)
    frappe.db.commit()

    job_id = enqueue_run(run.name)
    return {"run_name": run.name, "job_id": job_id}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.REPORTING)
def list_recent_bulk_runs(limit: int = 20) -> list[dict]:
    """Return recent runs for the UI history panel."""
    _check_access()

    limit = max(1, min(int(limit or 20), 100))
    runs = frappe.get_all(
        "Mollie Bulk Run",
        fields=[
            "name",
            "date_from",
            "date_to",
            "batch_strategy",
            "status",
            "total_payments",
            "total_succeeded",
            "total_skipped",
            "total_failed",
            "last_processed_index",
            "started_at",
            "completed_at",
            "triggered_by",
        ],
        order_by="creation desc",
        limit=limit,
    )
    for r in runs:
        total = r["total_payments"] or 0
        processed = r["last_processed_index"] or 0
        r["percentage"] = int(100 * processed / total) if total else 0
        r["resumable"] = r["status"] in ("Failed", "Timed Out", "Cancelled")
        r["active"] = r["status"] not in TERMINAL_STATUSES
    return runs
