"""
Invoice-related event emitters

This module handles emitting events for invoice lifecycle changes,
decoupling invoice operations from dependent systems like payment history.
"""

import frappe
from frappe import _


def emit_invoice_submitted(doc, method=None):
    """
    Emit event when a sales invoice is submitted.

    This replaces the direct call to update_member_payment_history_from_invoice,
    allowing multiple systems to react to invoice submission without tight coupling.
    """
    if doc.doctype != "Sales Invoice":
        return

    # Only emit for invoices with customers
    if not doc.customer:
        return

    event_data = {
        "invoice": doc.name,
        "customer": doc.customer,
        "posting_date": str(doc.posting_date),
        "due_date": str(doc.due_date) if doc.due_date else None,
        "grand_total": doc.grand_total,
        "outstanding_amount": doc.outstanding_amount,
        "status": doc.status,
        "docstatus": doc.docstatus,
    }

    # Log the event emission for debugging
    frappe.logger("events").info(f"Emitting invoice_submitted event for {doc.name}")

    # Emit to all registered subscribers
    try:
        _emit_invoice_event("invoice_submitted", event_data)
    except Exception as e:
        # Log but don't fail - event emission should never block invoice submission
        frappe.log_error(
            f"Failed to emit invoice_submitted event for {doc.name}: {str(e)}", "Invoice Event Emission Error"
        )


def emit_invoice_cancelled(doc, method=None):
    """Emit event when a sales invoice is cancelled"""
    if doc.doctype != "Sales Invoice" or not doc.customer:
        return

    event_data = {"invoice": doc.name, "customer": doc.customer, "cancelled_on": frappe.utils.now()}

    try:
        _emit_invoice_event("invoice_cancelled", event_data)
    except Exception as e:
        frappe.log_error(
            f"Failed to emit invoice_cancelled event for {doc.name}: {str(e)}", "Invoice Event Emission Error"
        )


def emit_invoice_updated_after_submit(doc, method=None):
    """Emit event when a submitted invoice is updated (e.g., payment received)"""
    if doc.doctype != "Sales Invoice" or not doc.customer or doc.docstatus != 1:
        return

    event_data = {
        "invoice": doc.name,
        "customer": doc.customer,
        "outstanding_amount": doc.outstanding_amount,
        "status": doc.status,
        "modified": str(doc.modified),
    }

    try:
        _emit_invoice_event("invoice_updated_after_submit", event_data)
    except Exception as e:
        frappe.log_error(
            f"Failed to emit invoice_updated_after_submit event for {doc.name}: {str(e)}",
            "Invoice Event Emission Error",
        )


def _emit_invoice_event(event_name, event_data):
    """
    Internal function to emit invoice events to all subscribers.

    Uses Frappe's background job queue to ensure event processing
    doesn't block the main transaction.
    """
    # Get all registered subscribers for this event
    subscribers = _get_event_subscribers(event_name)

    for subscriber in subscribers:
        # For payment history updates, we need special handling to prevent
        # concurrent updates to the same member
        if "payment_history_subscriber" in subscriber:
            # Get the customer from event data
            customer = event_data.get("customer")
            if customer:
                # Find all members for this customer
                members = frappe.get_all("Member", filters={"customer": customer}, fields=["name"])

                for member in members:
                    # Use member-specific job name to serialize updates
                    # The dedupe key ensures only one job per member runs at a time
                    frappe.enqueue(
                        method=subscriber,
                        queue="short",
                        job_name=f"payment_history_update_{member.name}",
                        dedupe=True,  # This prevents multiple jobs for same member
                        timeout=300,  # 5 minutes timeout
                        event_name=event_name,
                        event_data=event_data,
                    )
            else:
                # Fallback to original behavior if no customer
                frappe.enqueue(
                    method=subscriber,
                    queue="short",
                    job_name=f"{event_name}_{event_data.get('invoice')}_{subscriber}",
                    event_name=event_name,
                    event_data=event_data,
                )
        else:
            # For other subscribers, use the original approach
            frappe.enqueue(
                method=subscriber,
                queue="short",
                job_name=f"{event_name}_{event_data.get('invoice')}_{subscriber}",
                event_name=event_name,
                event_data=event_data,
            )


def _get_event_subscribers(event_name):
    """
    Get all registered subscribers for a specific event.

    This is a simple implementation - could be enhanced with:
    - Database-stored subscriptions
    - Priority ordering
    - Conditional subscriptions
    """
    # For now, using a simple mapping
    # In future, this could read from database or configuration
    event_subscribers = {
        "invoice_submitted": [
            "verenigingen.events.subscribers.payment_history_subscriber.handle_invoice_submitted"
        ],
        "invoice_cancelled": [
            "verenigingen.events.subscribers.payment_history_subscriber.handle_invoice_cancelled"
        ],
        "invoice_updated_after_submit": [
            "verenigingen.events.subscribers.payment_history_subscriber.handle_invoice_updated"
        ],
    }

    return event_subscribers.get(event_name, [])
