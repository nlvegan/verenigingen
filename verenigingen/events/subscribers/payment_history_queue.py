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
    # Get all pending updates grouped by member
    pending_updates = frappe.get_all(
        "Payment History Update Queue",
        filters={"status": "Pending"},
        fields=["name", "member", "invoice", "action", "retry_count"],
        order_by="creation asc",
        limit=100,  # Process in batches
    )

    # Group by member to process serially per member
    updates_by_member = {}
    for update in pending_updates:
        if update.member not in updates_by_member:
            updates_by_member[update.member] = []
        updates_by_member[update.member].append(update)

    # Process each member's updates serially
    for member_name, member_updates in updates_by_member.items():
        _process_member_updates(member_name, member_updates)

    # Clean up old processed entries
    _cleanup_old_entries()


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

    except Exception as e:
        # Mark updates as failed
        for update in updates:
            try:
                queue_doc = frappe.get_doc("Payment History Update Queue", update.name)
                queue_doc.status = "Failed"
                queue_doc.error_message = str(e)
                queue_doc.retry_count = queue_doc.retry_count + 1

                # Reset to pending if we haven't exceeded retry limit
                if queue_doc.retry_count < 3:
                    queue_doc.status = "Pending"

                queue_doc.save(ignore_permissions=True)
            except:
                pass


def _cleanup_old_entries():
    """Remove completed entries older than 7 days"""
    from frappe.utils import add_days, nowdate

    cutoff_date = add_days(nowdate(), -7)

    frappe.db.sql(
        """
        DELETE FROM `tabPayment History Update Queue`
        WHERE status = 'Completed'
        AND DATE(creation) < %s
    """,
        cutoff_date,
    )


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
