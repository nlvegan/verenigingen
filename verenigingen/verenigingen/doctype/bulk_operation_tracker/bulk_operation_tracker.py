# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, now, now_datetime

from verenigingen.utils.security.api_security_framework import OperationType, high_security_api


class BulkOperationTracker(Document):
    """DocType for tracking the progress of large bulk operations like account creation."""

    def validate(self):
        """Validate the document before saving."""
        # Ensure numeric fields are initialized (may be None after insert)
        self.processed_records = cint(self.processed_records)
        self.successful_records = cint(self.successful_records)
        self.failed_records = cint(self.failed_records)

        # Ensure total_batches is calculated correctly
        if self.total_records and self.batch_size:
            calculated_batches = (self.total_records + self.batch_size - 1) // self.batch_size
            if not self.total_batches:
                self.total_batches = calculated_batches
            elif self.total_batches != calculated_batches:
                frappe.msgprint(
                    _(
                        "Total batches ({0}) doesn't match calculated value ({1}) for {2} records with batch size {3}"
                    ).format(self.total_batches, calculated_batches, self.total_records, self.batch_size)
                )

        # Calculate processing rate if we have timing data
        self._calculate_processing_rate()

        # Calculate estimated completion if operation is in progress
        self._calculate_estimated_completion()

    def _calculate_processing_rate(self):
        """Calculate the processing rate per minute based on current progress."""
        if not self.started_at or self.processed_records <= 0:
            return

        start_time = frappe.utils.get_datetime(self.started_at)
        current_time = now_datetime()

        elapsed_minutes = (current_time - start_time).total_seconds() / 60

        if elapsed_minutes > 0:
            self.processing_rate_per_minute = flt(self.processed_records / elapsed_minutes, 2)

    def _calculate_estimated_completion(self):
        """Calculate estimated completion time based on current processing rate."""
        if (
            self.status == "Processing"
            and self.processing_rate_per_minute
            and self.processing_rate_per_minute > 0
            and self.processed_records < self.total_records
        ):
            remaining_records = self.total_records - self.processed_records
            estimated_minutes = remaining_records / self.processing_rate_per_minute

            current_time = now_datetime()
            estimated_completion = current_time + timedelta(minutes=estimated_minutes)
            self.estimated_completion = estimated_completion

    def start_operation(self):
        """Mark operation as started and record start time."""
        self.status = "Processing"
        self.started_at = now()
        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        from verenigingen.utils.secure_operations import secure_document_operation

        start_result = secure_document_operation(
            operation="save",
            doc=self,
            justification=f"Mark bulk operation {self.operation_type} as started",
            required_permissions=["Bulk Operation Tracker:write"],
        )

        if not start_result.success:
            frappe.logger().error(
                f"Failed to mark bulk operation as started: {'; '.join(start_result.errors)}"
            )
            frappe.throw(
                _("Failed to mark bulk operation as started: {0}").format("; ".join(start_result.errors))
            )

        frappe.logger().info(f"Bulk operation {self.name} started: {self.operation_type}")

    def update_progress(self, batch_number: int, batch_results: Dict):
        """Atomically fold one batch's results into the tracker counters.

        Uses a single ``UPDATE ... SET x = x + n`` rather than a
        load -> mutate -> save() round-trip so overlapping batch completions
        cannot raise ``TimestampMismatchError``, lose increments, or hold a row
        lock across a retry-sleep. See issue #172.

        Per-request detail (retry list, error summary) is NOT stored here — it is
        derived at read-time from the linked Account Creation Request rows, which
        are the single source of truth (see get_retry_requests/get_error_summary).

        Args:
            batch_number: The batch number that completed (1-indexed).
            batch_results: dict with ``completed`` and ``failed`` counts.
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
                "s": inc_success,
                "f": inc_failed,
                "p": inc_processed,
                "batch": cint(batch_number),
                "now": now(),
                "user": frappe.session.user,
                "name": self.name,
            },
        )

        # Single-winner completion: only the batch that pushes processed >= total
        # while the operation is still Processing flips the status.
        self._complete_operation_if_done()

        # Keep the in-memory doc consistent for callers that read counters after.
        self.reload()

        frappe.logger().info(
            f"Bulk operation {self.name} progress: batch {batch_number}/{self.total_batches}, "
            f"processed {self.processed_records}/{self.total_records}"
        )

    def _update_batch_details(self, batch_number: int, batch_results: Dict):
        """Update the batch details JSON with results from completed batch."""
        try:
            # Parse existing batch details or create new
            batch_details = json.loads(self.batch_details) if self.batch_details else []

            # Add this batch's results
            batch_info = {
                "batch_number": batch_number,
                "completed_at": now(),
                "successful": batch_results.get("completed", 0),
                "failed": batch_results.get("failed", 0),
                "total": batch_results.get("total_requests", 0),
                "errors_count": len(batch_results.get("errors", [])),
            }

            batch_details.append(batch_info)
            self.batch_details = json.dumps(batch_details, indent=2)

        except json.JSONDecodeError:
            # Initialize if JSON is corrupted
            self.batch_details = json.dumps([batch_info], indent=2)

    def _complete_operation_if_done(self):
        """Atomically mark the operation complete exactly once.

        The conditional WHERE (``processed_records >= total_records AND status =
        'Processing'``) means only the batch that crosses the finish line writes
        the terminal status — concurrent batches match zero rows. Status logic
        lives in the SQL CASE so it stays a single atomic statement.
        """
        frappe.db.sql(
            """
            UPDATE `tabBulk Operation Tracker`
            SET status = CASE
                    WHEN failed_records > 0 AND successful_records = 0 THEN 'Failed'
                    ELSE 'Completed' END,
                completed_at  = %(now)s,
                current_batch = total_batches,
                modified      = %(now)s,
                modified_by   = %(user)s
            WHERE name = %(name)s
              AND processed_records >= total_records
              AND status = 'Processing'
            """,
            {"now": now(), "user": frappe.session.user, "name": self.name},
        )

    def mark_failed(self, error_message: str):
        """Mark operation as failed with error message."""
        self.status = "Failed"
        self.completed_at = now()

        if error_message:
            current_summary = self.error_summary or ""
            self.error_summary = f"Operation failed: {error_message}\n{current_summary}"

        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        from verenigingen.utils.secure_operations import secure_document_operation

        failure_result = secure_document_operation(
            operation="save",
            doc=self,
            justification=f"Mark bulk operation as failed - {self.operation_type}",
            required_permissions=["Bulk Operation Tracker:write"],
        )

        if not failure_result.success:
            frappe.logger().error(
                f"Failed to mark bulk operation as failed: {'; '.join(failure_result.errors)}"
            )
            # Don't throw here as this is already error handling

        frappe.logger().error(f"Bulk operation {self.name} failed: {error_message}")

    def get_progress_percentage(self) -> float:
        """Get operation progress as percentage (0-100)."""
        if not self.total_records or self.total_records <= 0:
            return 0.0
        return flt((self.processed_records / self.total_records) * 100, 2)

    def get_retry_requests(self) -> List[str]:
        """Request names needing retry, derived from the linked Account Creation
        Requests (their ``status`` is the single source of truth — #172).

        A retried-and-fixed request flips out of ``status='Failed'`` on its own,
        so nothing has to mutate a stored queue.
        """
        return frappe.get_all(
            "Account Creation Request",
            filters={"bulk_operation_tracker": self.name, "status": "Failed"},
            pluck="name",
            order_by="creation",
        )

    def get_error_summary(self, limit: int = 100) -> List[str]:
        """Human-readable failure lines, derived from the failed linked ACRs."""
        rows = frappe.get_all(
            "Account Creation Request",
            filters={"bulk_operation_tracker": self.name, "status": "Failed"},
            fields=["name", "failure_reason"],
            order_by="creation",
            limit=limit,
        )
        return [f"{r.name}: {r.failure_reason or 'Unknown error'}" for r in rows]

    def clear_retry_queue(self):
        """No-op kept for API compatibility.

        The retry list is derived from ACR status (#172); there is no stored queue
        to clear. Requests leave the retry set by being re-processed successfully.
        """
        frappe.logger().info(
            f"clear_retry_queue() is a no-op for {self.name}: retry list derives from ACR status"
        )

    @staticmethod
    def create_tracker(
        operation_type: str,
        total_records: int,
        batch_size: int = 50,
        source_import: Optional[str] = None,
        priority: str = "Normal",
    ) -> "BulkOperationTracker":
        """
        Create a new bulk operation tracker.

        Args:
            operation_type: Type of operation (e.g., "Account Creation")
            total_records: Total number of records to process
            batch_size: Number of records per batch
            source_import: Optional link to source import document
            priority: Operation priority

        Returns:
            BulkOperationTracker: New tracker document
        """
        total_batches = (total_records + batch_size - 1) // batch_size

        tracker = frappe.get_doc(
            {
                "doctype": "Bulk Operation Tracker",
                "operation_type": operation_type,
                "total_records": total_records,
                "batch_size": batch_size,
                "total_batches": total_batches,
                "source_import": source_import,
                "priority": priority,
                "status": "Queued",
            }
        )

        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        from verenigingen.utils.secure_operations import secure_document_operation

        tracker_result = secure_document_operation(
            operation="insert",
            doc=tracker,
            justification=f"Create bulk operation tracker for {operation_type}",
            required_permissions=["Bulk Operation Tracker:create"],
        )

        if not tracker_result.success:
            frappe.logger().error(
                f"Failed to create bulk operation tracker: {'; '.join(tracker_result.errors)}"
            )
            frappe.throw(
                _("Failed to create bulk operation tracker: {0}").format("; ".join(tracker_result.errors))
            )

        frappe.logger().info(
            f"Created bulk operation tracker {tracker.name}: "
            f"{total_records} records in {total_batches} batches"
        )

        return tracker


# Utility functions for monitoring and administration


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def get_active_operations():
    """Get list of currently active bulk operations."""
    if not frappe.has_permission("Bulk Operation Tracker", "read"):
        frappe.throw(_("Insufficient permissions"))

    return frappe.get_all(
        "Bulk Operation Tracker",
        filters={"status": ["in", ["Queued", "Processing"]]},
        fields=[
            "name",
            "operation_type",
            "status",
            "total_records",
            "processed_records",
            "failed_records",
            "current_batch",
            "total_batches",
            "started_at",
            "estimated_completion",
        ],
        order_by="creation desc",
    )


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def get_operation_progress(tracker_name: str) -> Dict:
    """Get detailed progress information for a bulk operation."""
    if not frappe.has_permission("Bulk Operation Tracker", "read"):
        frappe.throw(_("Insufficient permissions"))

    tracker = frappe.get_doc("Bulk Operation Tracker", tracker_name)

    return {
        "name": tracker.name,
        "operation_type": tracker.operation_type,
        "status": tracker.status,
        "progress_percentage": tracker.get_progress_percentage(),
        "total_records": tracker.total_records,
        "processed_records": tracker.processed_records,
        "successful_records": tracker.successful_records,
        "failed_records": tracker.failed_records,
        "current_batch": tracker.current_batch,
        "total_batches": tracker.total_batches,
        "processing_rate": tracker.processing_rate_per_minute,
        "estimated_completion": tracker.estimated_completion,
        "started_at": tracker.started_at,
        "completed_at": tracker.completed_at,
        "retry_queue_count": len(tracker.get_retry_requests()),
        "error_summary": "\n".join(tracker.get_error_summary()),
    }
