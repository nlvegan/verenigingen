"""Mollie Bulk Run — orchestrates chronological, resumable, observable bulk payment import.

A single run covers a date range. On start, the worker fetches all Mollie
payments in that range, sorts them ascending by paid_at, and writes one
child row per payment with status=Pending. The worker then iterates rows
from ``last_processed_index``, calling the payment orchestrator for each,
updating the row, and publishing progress every 10 rows.

Resume, cancel, and stale-run cleanup are handled via the module-level
functions in ``bulk_run_service`` — this controller only owns state
transitions and validation.
"""

import frappe
from frappe import _
from frappe.model.document import Document

TERMINAL_STATUSES = {"Completed", "Failed", "Timed Out", "Cancelled"}
ACTIVE_STATUSES = {"Queued", "Fetching", "Processing"}
MAX_ATTEMPTS_PER_PAYMENT = 3


class MollieBulkRun(Document):
    def validate(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            frappe.throw(_("From Date must be on or before To Date"))

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def mark_cancel_requested(self) -> None:
        if self.is_terminal:
            frappe.throw(_("Cannot cancel a run in status {0}").format(self.status))
        self.db_set("cancel_requested", 1, update_modified=False)

    def after_insert(self):
        """Auto-enqueue newly-created Queued runs so desk-saved runs actually run.

        The whitelisted API also creates runs this way but needs to control when
        the enqueue happens (it reports the job_id back to the caller). It sets
        ``self.flags.skip_auto_enqueue`` to suppress this hook and enqueues
        explicitly. Anyone creating a run via the desk gets auto-enqueue.
        """
        if self.flags.get("skip_auto_enqueue"):
            return
        if self.status != "Queued":
            return
        from verenigingen.verenigingen_payments.services.mollie_bulk_run_service import (
            enqueue_run,
        )

        enqueue_run(self.name)
