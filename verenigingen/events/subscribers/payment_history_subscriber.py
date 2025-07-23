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
    Update member payment history using document locking to prevent conflicts.
    """
    max_retries = 3
    retry_count = 0

    while retry_count < max_retries:
        try:
            # Use Frappe's document locking mechanism
            with frappe.utils.document_lock.lock(
                "Member", member_name, timeout=10  # Wait up to 10 seconds for lock
            ):
                # Now we have exclusive access to the member document
                member = frappe.get_doc("Member", member_name)

                if hasattr(member, "load_payment_history"):
                    member.load_payment_history()
                    member.save(ignore_permissions=True)
                    return True
                else:
                    frappe.log_error(
                        f"Member {member_name} missing load_payment_history method",
                        "Payment History Method Missing",
                    )
                    return False

        except frappe.utils.document_lock.LockTimeoutError:
            # Another process has the lock, skip this member
            frappe.logger("payment_history").info(
                f"Skipped payment history update for {member_name} - document locked by another process"
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
                raise

    return False


def handle_invoice_submitted_immediate(event_name=None, event_data=None):
    """
    Immediate handler that just marks the member for update.

    The actual update happens in the scheduled batch job.
    """
    if not event_data:
        return

    customer = event_data.get("customer")
    invoice = event_data.get("invoice")

    if not customer or not invoice:
        return

    # Just log that this member needs update
    # The batch job will pick it up based on invoice modified time
    frappe.logger("payment_history").info(
        f"Invoice {invoice} submitted for customer {customer}. "
        f"Payment history will be updated in next batch run."
    )


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
