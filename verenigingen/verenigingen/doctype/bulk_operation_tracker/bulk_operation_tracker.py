# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, now, now_datetime


class BulkOperationTracker(Document):
    """DocType for tracking the progress of large bulk operations like account creation."""

    def validate(self):
        """Validate the document before saving."""
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
        self.save(ignore_permissions=True)  # System operation

        frappe.logger().info(f"Bulk operation {self.name} started: {self.operation_type}")

    def update_progress(self, batch_number: int, batch_results: Dict):
        """
        Update progress based on batch completion results.

        Args:
            batch_number: The batch number that completed (1-indexed)
            batch_results: Dictionary with batch results containing:
                - completed: number of successful records
                - failed: number of failed records
                - errors: list of error messages
        """
        # Update batch progress
        self.current_batch = batch_number

        # Update record counts
        batch_successful = batch_results.get("completed", 0)
        batch_failed = batch_results.get("failed", 0)

        self.successful_records += batch_successful
        self.failed_records += batch_failed
        self.processed_records = self.successful_records + self.failed_records

        # Store batch details
        self._update_batch_details(batch_number, batch_results)

        # Update retry queue if there are failures
        if batch_failed > 0 and batch_results.get("failed_requests"):
            self._update_retry_queue(batch_results["failed_requests"])

        # Update error summary
        if batch_results.get("errors"):
            self._update_error_summary(batch_results["errors"])

        # Check if operation is complete
        if self.processed_records >= self.total_records:
            self._complete_operation()
        else:
            # Recalculate estimates
            self.validate()

        self.save(ignore_permissions=True)  # System operation

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

    def _update_retry_queue(self, failed_requests: List[str]):
        """Update the retry queue with failed request names."""
        try:
            # Parse existing retry queue or create new
            retry_queue = json.loads(self.retry_queue) if self.retry_queue else []

            # Add failed requests to retry queue
            retry_queue.extend(failed_requests)

            # Remove duplicates while preserving order
            seen = set()
            unique_retry_queue = []
            for request in retry_queue:
                if request not in seen:
                    seen.add(request)
                    unique_retry_queue.append(request)

            self.retry_queue = json.dumps(unique_retry_queue, indent=2)

        except json.JSONDecodeError:
            # Initialize if JSON is corrupted
            self.retry_queue = json.dumps(failed_requests, indent=2)

    def _update_error_summary(self, new_errors: List[str]):
        """Update error summary with new errors, maintaining a reasonable size."""
        current_errors = self.error_summary.split("\n") if self.error_summary else []

        # Add new errors
        current_errors.extend(new_errors)

        # Limit to last 100 errors to prevent overwhelming storage
        if len(current_errors) > 100:
            current_errors = current_errors[-100:]
            current_errors.insert(0, f"[Showing last 100 errors - total errors: {self.failed_records}]")

        self.error_summary = "\n".join(current_errors)

    def _complete_operation(self):
        """Mark operation as completed and record completion time."""
        if self.failed_records > 0:
            self.status = "Completed" if self.successful_records > 0 else "Failed"
        else:
            self.status = "Completed"

        self.completed_at = now()
        self.current_batch = self.total_batches

        frappe.logger().info(
            f"Bulk operation {self.name} completed: {self.successful_records} successful, "
            f"{self.failed_records} failed out of {self.total_records} total"
        )

    def mark_failed(self, error_message: str):
        """Mark operation as failed with error message."""
        self.status = "Failed"
        self.completed_at = now()

        if error_message:
            current_summary = self.error_summary or ""
            self.error_summary = f"Operation failed: {error_message}\n{current_summary}"

        self.save(ignore_permissions=True)  # System operation

        frappe.logger().error(f"Bulk operation {self.name} failed: {error_message}")

    def get_progress_percentage(self) -> float:
        """Get operation progress as percentage (0-100)."""
        if not self.total_records or self.total_records <= 0:
            return 0.0
        return flt((self.processed_records / self.total_records) * 100, 2)

    def get_retry_requests(self) -> List[str]:
        """Get list of request names that need retry processing."""
        try:
            return json.loads(self.retry_queue) if self.retry_queue else []
        except json.JSONDecodeError:
            return []

    def clear_retry_queue(self):
        """Clear the retry queue after successful retry processing."""
        self.retry_queue = ""
        self.save(ignore_permissions=True)  # System operation

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

        tracker.insert(ignore_permissions=True)  # System operation

        frappe.logger().info(
            f"Created bulk operation tracker {tracker.name}: "
            f"{total_records} records in {total_batches} batches"
        )

        return tracker


# Utility functions for monitoring and administration


@frappe.whitelist()
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
    }
