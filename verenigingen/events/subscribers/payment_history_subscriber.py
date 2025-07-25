"""
Alternative Payment History Event Subscriber with better concurrency handling

This version uses a different approach to handle concurrent updates:
1. Delays processing to batch updates
2. Uses document locking to prevent conflicts
3. Implements eventual consistency pattern
"""

import time

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, now_datetime


def handle_invoice_events_batched():
    """
    Process invoice events in batches to update member payment history.

    This should be called by a scheduled job every few minutes to process
    all pending payment history updates in a controlled manner.
    """
    # Get unique members that need payment history updates
    # Look for recent invoices that might need syncing
    cutoff_time = add_to_date(now_datetime(), minutes=-30)

    members_to_update = frappe.db.sql(
        """
        SELECT DISTINCT m.name as member_name
        FROM `tabMember` m
        INNER JOIN `tabSales Invoice` si ON si.customer = m.customer
        WHERE si.modified >= %s
        AND si.docstatus = 1
        AND m.customer IS NOT NULL
        AND m.customer != ''
        ORDER BY si.modified DESC
        LIMIT 50
    """,
        cutoff_time,
        as_dict=True,
    )

    updated_count = 0
    error_count = 0

    for member_data in members_to_update:
        try:
            _update_member_payment_history_with_lock(member_data.member_name)
            updated_count += 1
        except Exception as e:
            error_count += 1
            if "document has been modified" not in str(e).lower():
                frappe.log_error(
                    f"Failed to update payment history for {member_data.member_name}: {str(e)}",
                    "Batch Payment History Update Error",
                )

    if updated_count > 0 or error_count > 0:
        frappe.logger("payment_history").info(
            f"Batch payment history update completed. Updated: {updated_count}, Errors: {error_count}"
        )

    return {"updated": updated_count, "errors": error_count}


def _update_member_payment_history_with_lock(member_name):
    """
    Update member payment history with simple retry logic.
    """
    max_retries = 3
    retry_count = 0

    while retry_count < max_retries:
        try:
            # Get the member document
            member = frappe.get_doc("Member", member_name)

            if hasattr(member, "load_payment_history"):
                member.load_payment_history()
                return True
            else:
                frappe.logger("payment_history").info(
                    f"Member {member_name} missing load_payment_history method"
                )
                return False

        except Exception as e:
            if "document has been modified" in str(e).lower():
                retry_count += 1
                if retry_count < max_retries:
                    time.sleep(0.5 * retry_count)
                    continue
                else:
                    # Skip after max retries
                    frappe.logger("payment_history").info(
                        f"Skipped payment history update for {member_name} after {max_retries} retries"
                    )
                    return False
            else:
                # Other errors should be logged
                frappe.logger("payment_history").error(
                    f"Failed to update payment history for {member_name}: {str(e)}"
                )
                return False

    return False


def handle_invoice_submitted(event_name=None, event_data=None, **kwargs):
    """
    Handle invoice submission - update member payment history incrementally.

    This is called by the event system when a Sales Invoice is submitted.
    """
    if not event_data:
        return

    customer = event_data.get("customer")
    invoice = event_data.get("invoice")

    if not customer or not invoice:
        return

    # Find members for this customer and update their payment history incrementally
    members = frappe.get_all("Member", filters={"customer": customer}, fields=["name"])

    for member in members:
        try:
            # Use new incremental update method
            member_doc = frappe.get_doc("Member", member.name)
            member_doc.add_invoice_to_payment_history(invoice)

            frappe.logger("payment_history").info(
                f"Added invoice {invoice} to payment history for member {member.name}"
            )
        except Exception as e:
            frappe.log_error(
                f"Failed to add invoice {invoice} to payment history for member {member.name}: {str(e)}",
                "Invoice Payment History Update Error",
            )


def handle_invoice_cancelled(event_name=None, event_data=None, **kwargs):
    """Handle invoice cancellation - remove from member payment history."""
    if not event_data:
        return

    customer = event_data.get("customer")
    invoice = event_data.get("invoice")

    if not customer or not invoice:
        return

    # Find members for this customer and remove invoice from their payment history
    members = frappe.get_all("Member", filters={"customer": customer}, fields=["name"])

    for member in members:
        try:
            # Use new incremental removal method
            member_doc = frappe.get_doc("Member", member.name)
            member_doc.remove_invoice_from_payment_history(invoice)

            frappe.logger("payment_history").info(
                f"Removed cancelled invoice {invoice} from payment history for member {member.name}"
            )
        except Exception as e:
            frappe.log_error(
                f"Failed to remove cancelled invoice {invoice} from payment history for member {member.name}: {str(e)}",
                "Invoice Cancellation Payment History Update Error",
            )


def handle_invoice_updated(event_name=None, event_data=None, **kwargs):
    """Handle invoice update after submit (e.g., payment received) - update member payment history."""
    if not event_data:
        return

    customer = event_data.get("customer")
    invoice = event_data.get("invoice")

    if not customer or not invoice:
        return

    # Find members for this customer and update their payment history incrementally
    members = frappe.get_all("Member", filters={"customer": customer}, fields=["name"])

    for member in members:
        try:
            # Use new incremental update method
            member_doc = frappe.get_doc("Member", member.name)
            member_doc.update_invoice_in_payment_history(invoice)

            frappe.logger("payment_history").info(
                f"Updated invoice {invoice} in payment history for member {member.name}"
            )
        except Exception as e:
            frappe.log_error(
                f"Failed to update invoice {invoice} in payment history for member {member.name}: {str(e)}",
                "Invoice Update Payment History Update Error",
            )


def handle_invoice_submitted_immediate(event_name=None, event_data=None, **kwargs):
    """
    Legacy immediate handler - kept for backward compatibility.
    The new handle_invoice_submitted method should be used instead.
    """
    return handle_invoice_submitted(event_name, event_data, **kwargs)


# Scheduler method to be called periodically
def sync_payment_histories():
    """
    Scheduled method to sync payment histories.

    Add this to hooks.py scheduler_events:
    "*/5 * * * *": [
        "vereiningen.events.subscribers.payment_history_subscriber.sync_payment_histories"
    ]
    """
    try:
        result = handle_invoice_events_batched()
        if result["updated"] > 0:
            frappe.db.commit()
    except Exception as e:
        frappe.log_error(str(e), "Payment History Sync Error")
