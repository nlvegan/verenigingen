"""
Queue-based payment history updater to handle concurrent updates gracefully

This module provides a serialized approach to updating payment history,
preventing concurrent modification conflicts.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint


def process_payment_history_update_queue():
    """
    Process queued payment history updates in a serialized manner.

    This function should be called by a scheduled job to process
    updates one at a time per member, avoiding conflicts.
    """
    start_time = frappe.utils.now()
    processed_count = 0
    failed_count = 0

    try:
        # Get all pending updates grouped by member
        pending_updates = frappe.get_all(
            "Payment History Update Queue",
            filters={"status": "Pending"},
            fields=["name", "member", "invoice", "action", "retry_count"],
            order_by="creation asc",
            limit=100,  # Process in batches
        )

        if not pending_updates:
            frappe.logger("payment_history").info("No pending payment history updates to process")
            return {"success": True, "processed": 0, "failed": 0}

        frappe.logger("payment_history").info(
            f"Processing {len(pending_updates)} pending payment history updates"
        )

        # Group by member to process serially per member
        updates_by_member = {}
        for update in pending_updates:
            if update.member not in updates_by_member:
                updates_by_member[update.member] = []
            updates_by_member[update.member].append(update)

        # Process each member's updates serially
        for member_name, member_updates in updates_by_member.items():
            result = _process_member_updates(member_name, member_updates)
            if result["success"]:
                processed_count += len(member_updates)
            else:
                failed_count += len(member_updates)

        # Clean up old processed entries
        cleanup_count = _cleanup_old_entries()

        end_time = frappe.utils.now()
        duration = frappe.utils.time_diff_in_seconds(end_time, start_time)

        # Log summary
        frappe.logger("payment_history").info(
            f"Payment history queue processing completed. "
            f"Processed: {processed_count}, Failed: {failed_count}, "
            f"Cleaned up: {cleanup_count} old entries, Duration: {duration:.2f}s"
        )

        # Alert if there are many failures (configurable threshold)
        from verenigingen.utils.notification_helpers import get_threshold_setting

        failure_threshold = get_threshold_setting("payment_history_failure_threshold", 10)

        if failed_count > failure_threshold:
            _alert_payment_history_failures(failed_count, processed_count)

        return {
            "success": True,
            "processed": processed_count,
            "failed": failed_count,
            "cleanup_count": cleanup_count,
            "duration": duration,
        }

    except Exception as e:
        error_msg = f"Critical error in payment history queue processing: {str(e)}"
        frappe.log_error(
            message=f"{error_msg}\n\n{frappe.get_traceback()}", title="Payment History Queue Processing Error"
        )

        # Send alert to administrators
        _alert_payment_history_critical_error(str(e))

        return {"success": False, "error": str(e), "processed": processed_count, "failed": failed_count}


def _process_member_updates(member_name, updates):
    """Process all pending updates for a single member"""
    try:
        # Get member document once
        member = frappe.get_doc("Member", member_name)

        # Process all updates for this member
        needs_reload = False
        for update in updates:
            queue_doc = frappe.get_doc("Payment History Update Queue", update.name)
            queue_doc.status = "Processing"
            queue_doc.save(ignore_permissions=True)
            needs_reload = True

        # Reload payment history once for all updates
        if needs_reload and hasattr(member, "load_payment_history"):
            member.load_payment_history()
            member.save(ignore_permissions=True)

        # Mark all updates as completed
        for update in updates:
            queue_doc = frappe.get_doc("Payment History Update Queue", update.name)
            queue_doc.status = "Completed"
            queue_doc.save(ignore_permissions=True)

        frappe.logger("payment_history").info(
            f"Successfully processed {len(updates)} updates for member {member_name}"
        )
        return {"success": True, "processed": len(updates)}

    except Exception as e:
        # Mark updates as failed
        frappe.logger("payment_history").error(
            f"Failed to process updates for member {member_name}: {str(e)}"
        )

        for update in updates:
            try:
                queue_doc = frappe.get_doc("Payment History Update Queue", update.name)
                queue_doc.status = "Failed"
                queue_doc.error_message = str(e)
                queue_doc.retry_count = queue_doc.retry_count + 1

                # Reset to pending if we haven't exceeded retry limit
                if queue_doc.retry_count < 3:
                    queue_doc.status = "Pending"
                    frappe.logger("payment_history").info(
                        f"Retrying payment history update {update.name} (attempt {queue_doc.retry_count + 1})"
                    )
                else:
                    frappe.logger("payment_history").error(
                        f"Payment history update {update.name} exceeded retry limit"
                    )

                queue_doc.save(ignore_permissions=True)
            except frappe.DoesNotExistError:
                frappe.log_error(
                    message=f"Payment History Update Queue entry {update.name} no longer exists while marking as failed",
                    title="Payment History Queue - Missing Entry",
                    reference_doctype="Payment History Update Queue",
                    reference_name=update.name,
                )
            except Exception as queue_save_error:
                frappe.log_error(
                    message=f"Failed to update Payment History Update Queue entry {update.name} status: {str(queue_save_error)}",
                    title="Payment History Queue - Status Update Failed",
                    reference_doctype="Payment History Update Queue",
                    reference_name=update.name,
                )

        return {"success": False, "failed": len(updates), "error": str(e)}


def _cleanup_old_entries():
    """Remove completed entries older than 7 days"""
    from frappe.utils import add_days, nowdate

    cutoff_date = add_days(nowdate(), -7)

    # Count entries to be deleted for monitoring
    count_query = """
        SELECT COUNT(*) as count
        FROM `tabPayment History Update Queue`
        WHERE status = 'Completed'
        AND DATE(creation) < %s
    """

    count_result = frappe.db.sql(count_query, cutoff_date, as_dict=True)
    cleanup_count = count_result[0]["count"] if count_result else 0

    if cleanup_count > 0:
        frappe.db.sql(
            """
            DELETE FROM `tabPayment History Update Queue`
            WHERE status = 'Completed'
            AND DATE(creation) < %s
        """,
            cutoff_date,
        )
        frappe.logger("payment_history").info(
            f"Cleaned up {cleanup_count} old completed payment history queue entries"
        )

    return cleanup_count


def queue_payment_history_update(member_name, invoice_name, action):
    """
    Queue a payment history update instead of processing immediately.

    This prevents concurrent modification errors.
    """
    try:
        # Check if this update is already queued
        existing = frappe.get_all(
            "Payment History Update Queue",
            filters={
                "member": member_name,
                "invoice": invoice_name,
                "action": action,
                "status": ["in", ["Pending", "Processing"]],
            },
        )

        if not existing:
            # Create queue entry
            queue_doc = frappe.new_doc("Payment History Update Queue")
            queue_doc.member = member_name
            queue_doc.invoice = invoice_name
            queue_doc.action = action
            queue_doc.status = "Pending"
            queue_doc.retry_count = 0
            queue_doc.insert(ignore_permissions=True)

            frappe.logger("events").info(
                f"Queued payment history update for member {member_name}, "
                f"invoice {invoice_name}, action {action}"
            )

    except Exception as e:
        frappe.log_error(f"Failed to queue payment history update: {str(e)}", "Payment History Queue Error")


def _alert_payment_history_failures(failed_count, processed_count):
    """Send alert when there are too many payment history failures"""
    try:
        from verenigingen.utils.notification_helpers import get_notification_recipients

        admin_emails = get_notification_recipients("stuck_schedule_notification_emails")

        if admin_emails:
            subject = "[ALERT] High Payment History Update Failure Rate"
            message = f"""
            <h3>⚠️ Payment History Update Alert</h3>
            <p>The payment history queue processing has encountered a high failure rate:</p>
            <ul>
                <li><strong>Failed Updates:</strong> {failed_count}</li>
                <li><strong>Successful Updates:</strong> {processed_count}</li>
                <li><strong>Failure Rate:</strong> {(failed_count / (failed_count + processed_count)) * 100:.1f}%</li>
            </ul>
            <p>This may indicate a system issue that requires investigation.</p>
            <p><strong>Recommended Actions:</strong></p>
            <ul>
                <li>Check Error Log for specific failure causes</li>
                <li>Review Payment History Update Queue for failed entries</li>
                <li>Verify Member documents and Sales Invoice references</li>
            </ul>
            """

            frappe.sendmail(recipients=admin_emails, subject=subject, message=message, now=True)

            frappe.logger("payment_history").info(f"Sent failure alert to {len(admin_emails)} administrators")
    except Exception as e:
        frappe.log_error(
            f"Failed to send payment history failure alert: {str(e)}", "Payment History Alert Error"
        )


def _alert_payment_history_critical_error(error_msg):
    """Send critical error alert for payment history processing"""
    try:
        admin_emails = frappe.get_all(
            "User", filters=[["Has Role", "role", "=", "System Manager"]], pluck="email"
        )

        if admin_emails:
            subject = "[CRITICAL] Payment History Queue Processing Failed"
            message = f"""
            <h3>🚨 Critical Payment History Error</h3>
            <p>The payment history queue processing has failed completely with a critical error:</p>
            <pre>{error_msg}</pre>
            <p><strong>Impact:</strong> Payment history updates are not being processed, which may affect member financial records.</p>
            <p><strong>Required Action:</strong> Immediate investigation and resolution needed.</p>
            """

            frappe.sendmail(recipients=admin_emails, subject=subject, message=message, now=True)

            frappe.logger("payment_history").error(
                f"Sent critical error alert to {len(admin_emails)} administrators"
            )
    except Exception as e:
        frappe.log_error(
            f"Failed to send payment history critical error alert: {str(e)}", "Payment History Alert Error"
        )


@frappe.whitelist()
def get_payment_history_queue_status():
    """Get current status of payment history queue for monitoring dashboard"""
    try:
        # Get counts by status
        status_counts = frappe.db.sql(
            """
            SELECT status, COUNT(*) as count
            FROM `tabPayment History Update Queue`
            GROUP BY status
        """,
            as_dict=True,
        )

        # Get oldest pending entry
        oldest_pending = frappe.db.sql(
            """
            SELECT creation
            FROM `tabPayment History Update Queue`
            WHERE status = 'Pending'
            ORDER BY creation ASC
            LIMIT 1
        """,
            as_dict=True,
        )

        # Get recent failed entries with retry count >= 3
        permanently_failed = frappe.db.sql(
            """
            SELECT COUNT(*) as count
            FROM `tabPayment History Update Queue`
            WHERE status = 'Failed' AND retry_count >= 3
        """,
            as_dict=True,
        )

        return {
            "status_counts": {item["status"]: item["count"] for item in status_counts},
            "oldest_pending": oldest_pending[0]["creation"] if oldest_pending else None,
            "permanently_failed": permanently_failed[0]["count"] if permanently_failed else 0,
            "last_updated": frappe.utils.now(),
        }
    except Exception as e:
        frappe.log_error(
            f"Failed to get payment history queue status: {str(e)}", "Payment History Status Error"
        )
        return {"error": str(e)}
