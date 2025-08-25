"""
Bulk Retry Processor for Failed Account Creation Requests
=========================================================

This module handles automated retry processing for failed bulk account creation requests.
It processes retry queues from BulkOperationTracker documents and attempts to reprocess
failed requests with exponential backoff.

Author: Verenigingen Development Team
"""

import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import cint, now, now_datetime

from verenigingen.utils.account_creation_manager import process_bulk_account_creation_batch


def process_retry_queues():
    """
    Scheduled function to process retry queues from failed bulk operations.

    This function is called hourly via scheduler to automatically retry failed
    account creation requests with exponential backoff logic.
    """
    try:
        frappe.logger().info("Starting scheduled retry queue processing")

        # Get all bulk operation trackers with retry queues
        trackers_with_retries = frappe.get_all(
            "Bulk Operation Tracker",
            filters={
                "status": ["in", ["Completed", "Failed"]],  # Only completed operations
                "retry_queue": ["!=", ""],  # Have retry items
            },
            fields=["name", "operation_type", "failed_records", "creation"],
            order_by="creation desc",
        )

        if not trackers_with_retries:
            frappe.logger().info("No retry queues found")
            return

        total_processed = 0
        total_succeeded = 0
        total_failed = 0

        for tracker_info in trackers_with_retries:
            try:
                result = process_single_retry_queue(tracker_info["name"])
                total_processed += result.get("processed", 0)
                total_succeeded += result.get("succeeded", 0)
                total_failed += result.get("failed", 0)

            except Exception as e:
                frappe.logger().error(f"Error processing retry queue for {tracker_info['name']}: {str(e)}")
                continue

        if total_processed > 0:
            frappe.logger().info(
                f"Retry processing completed: {total_processed} processed, "
                f"{total_succeeded} succeeded, {total_failed} failed"
            )

    except Exception as e:
        frappe.log_error(f"Error in scheduled retry processing: {str(e)}", "Retry Queue Processing Error")


def process_single_retry_queue(tracker_name: str) -> Dict:
    """
    Process retry queue for a single BulkOperationTracker.

    Args:
        tracker_name: Name of the BulkOperationTracker document

    Returns:
        dict: Processing results with counts
    """
    try:
        tracker = frappe.get_doc("Bulk Operation Tracker", tracker_name)
        retry_requests = tracker.get_retry_requests()

        if not retry_requests:
            return {"processed": 0, "succeeded": 0, "failed": 0}

        # Check if enough time has passed for retry (exponential backoff)
        if not should_retry_now(tracker):
            frappe.logger().info(f"Skipping retry for {tracker_name} - backoff period not elapsed")
            return {"processed": 0, "succeeded": 0, "failed": 0}

        frappe.logger().info(f"Processing {len(retry_requests)} retry requests for {tracker_name}")

        # Process retry requests in smaller batches to avoid overwhelming system
        batch_size = 10  # Smaller batches for retry processing
        succeeded_requests = []
        failed_requests = []

        for i in range(0, len(retry_requests), batch_size):
            batch = retry_requests[i : i + batch_size]

            try:
                # Use existing batch processor for consistency
                batch_results = process_bulk_account_creation_batch(
                    request_names=batch,
                    batch_id=f"retry_batch_{i // batch_size + 1}",
                    batch_number=i // batch_size + 1,
                    tracker_name=tracker_name,
                )

                succeeded_requests.extend(batch_results.get("completed_requests", []))
                failed_requests.extend(batch_results.get("failed_requests", []))

            except Exception as e:
                frappe.logger().error(f"Error processing retry batch {i // batch_size + 1}: {str(e)}")
                failed_requests.extend(batch)
                continue

        # Update tracker retry queue - remove successful requests
        remaining_failed = [req for req in retry_requests if req in failed_requests]

        if len(remaining_failed) < len(retry_requests):
            # Some requests succeeded - update retry queue
            tracker.retry_queue = json.dumps(remaining_failed, indent=2) if remaining_failed else ""
            tracker.save(ignore_permissions=True)  # System operation

            frappe.logger().info(
                f"Updated retry queue for {tracker_name}: {len(succeeded_requests)} succeeded, "
                f"{len(remaining_failed)} remaining failed"
            )

        return {
            "processed": len(retry_requests),
            "succeeded": len(succeeded_requests),
            "failed": len(remaining_failed),
        }

    except Exception as e:
        frappe.logger().error(f"Error processing retry queue for {tracker_name}: {str(e)}")
        return {"processed": 0, "succeeded": 0, "failed": 0}


def should_retry_now(tracker) -> bool:
    """
    Determine if enough time has passed for retry based on exponential backoff.

    Args:
        tracker: BulkOperationTracker document

    Returns:
        bool: True if retry should be attempted now
    """
    if not tracker.completed_at:
        return False

    completed_time = frappe.utils.get_datetime(tracker.completed_at)
    current_time = now_datetime()
    elapsed_hours = (current_time - completed_time).total_seconds() / 3600

    # Get retry attempt count from tracker (could be stored in custom field)
    retry_attempts = getattr(tracker, "retry_attempts", 0)

    # Exponential backoff: 1 hour, 4 hours, 12 hours, then daily
    backoff_hours = [1, 4, 12, 24, 48, 72]  # Up to 3 days

    if retry_attempts >= len(backoff_hours):
        # After maximum attempts, only retry weekly
        return elapsed_hours >= 168  # 1 week

    required_hours = backoff_hours[retry_attempts]
    return elapsed_hours >= required_hours


def manual_retry_failed_requests(tracker_name: str) -> Dict:
    """
    Manually trigger retry processing for a specific tracker.

    This is a whitelisted function for admin users to manually trigger retries.

    Args:
        tracker_name: Name of the BulkOperationTracker document

    Returns:
        dict: Processing results
    """
    if not frappe.has_permission("Bulk Operation Tracker", "write"):
        frappe.throw(_("Insufficient permissions to retry bulk operations"))

    try:
        result = process_single_retry_queue(tracker_name)

        if result["processed"] > 0:
            frappe.msgprint(
                _(
                    f"Retry processing completed: {result['succeeded']} succeeded, "
                    f"{result['failed']} failed out of {result['processed']} processed"
                )
            )
        else:
            frappe.msgprint(_("No retry requests to process"))

        return result

    except Exception as e:
        frappe.log_error(f"Manual retry failed for {tracker_name}: {str(e)}", "Manual Retry Error")
        frappe.throw(_("Retry processing failed: {0}").format(str(e)))


@frappe.whitelist()
def get_retry_queue_status():
    """Get status of all retry queues for admin dashboard."""
    if not frappe.has_permission("Bulk Operation Tracker", "read"):
        frappe.throw(_("Insufficient permissions"))

    trackers = frappe.get_all(
        "Bulk Operation Tracker",
        filters={"retry_queue": ["!=", ""]},
        fields=["name", "operation_type", "total_records", "failed_records", "completed_at", "creation"],
        order_by="creation desc",
    )

    retry_status = []
    for tracker_info in trackers:
        try:
            tracker = frappe.get_doc("Bulk Operation Tracker", tracker_info["name"])
            retry_requests = tracker.get_retry_requests()

            retry_status.append(
                {
                    "tracker_name": tracker_info["name"],
                    "operation_type": tracker_info["operation_type"],
                    "total_records": tracker_info["total_records"],
                    "failed_records": tracker_info["failed_records"],
                    "retry_queue_count": len(retry_requests),
                    "completed_at": tracker_info["completed_at"],
                    "should_retry": should_retry_now(tracker),
                    "age_hours": (
                        now_datetime() - frappe.utils.get_datetime(tracker_info["completed_at"])
                    ).total_seconds()
                    / 3600,
                }
            )

        except Exception as e:
            frappe.logger().error(f"Error getting retry status for {tracker_info['name']}: {str(e)}")
            continue

    return retry_status


@frappe.whitelist()
def clear_retry_queue(tracker_name: str):
    """Clear retry queue for a specific tracker (admin function)."""
    if not frappe.has_permission("Bulk Operation Tracker", "write"):
        frappe.throw(_("Insufficient permissions"))

    try:
        tracker = frappe.get_doc("Bulk Operation Tracker", tracker_name)
        retry_count = len(tracker.get_retry_requests())

        tracker.clear_retry_queue()

        frappe.msgprint(_(f"Cleared retry queue with {retry_count} requests for {tracker_name}"))
        return {"success": True, "cleared_count": retry_count}

    except Exception as e:
        frappe.log_error(f"Error clearing retry queue for {tracker_name}: {str(e)}")
        frappe.throw(_("Failed to clear retry queue: {0}").format(str(e)))
