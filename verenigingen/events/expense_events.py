"""
Expense Claim related event emitters

This module handles emitting events for expense claim lifecycle changes,
allowing systems to react to expense approvals and payments.
"""

import frappe
from frappe import _


def emit_expense_claim_approved(doc, method=None):
    """
    Emit event when an expense claim approval status changes.

    This should be called on_update_after_submit to catch approval status changes.
    """
    if doc.doctype != "Expense Claim":
        return

    # Only process submitted expense claims
    if doc.docstatus != 1:
        return

    # Check if approval_status has changed to Approved
    if not doc.has_value_changed("approval_status"):
        return

    if doc.approval_status == "Approved":
        # Emit approval event
        _emit_expense_approval_event(doc, "approved")
    elif doc.approval_status in ["Rejected", "Cancelled"]:
        # Emit rejection event
        _emit_expense_approval_event(doc, "rejected")


def _emit_expense_approval_event(doc, action):
    """Helper to emit expense approval events"""

    # Check if this is a volunteer expense by looking at employee link
    volunteer = None
    member = None

    if doc.employee:
        # Check if employee is linked to a volunteer
        volunteer_name = frappe.db.get_value("Volunteer", {"employee": doc.employee}, "name")
        if volunteer_name:
            volunteer = volunteer_name
            # Get member from volunteer
            member = frappe.db.get_value("Volunteer", volunteer_name, "member")

    event_data = {
        "expense_claim": doc.name,
        "employee": doc.employee,
        "volunteer": volunteer,
        "member": member,
        "posting_date": str(doc.posting_date),
        "total_claimed_amount": doc.total_claimed_amount,
        "total_sanctioned_amount": doc.total_sanctioned_amount,
        "approval_status": doc.approval_status,
        "status": doc.status,
        "docstatus": doc.docstatus,
        "action": action,  # "approved" or "rejected"
        "expense_type": "Volunteer Expense" if volunteer else "Regular Expense",
    }

    # Determine event name based on action
    event_name = f"expense_claim_{action}"

    # Log the event emission
    frappe.logger("events").info(f"Emitting {event_name} event for {doc.name}")

    try:
        _emit_expense_event(event_name, event_data)
    except Exception as e:
        # Log but don't fail - event emission should never block expense claim updates
        frappe.log_error(
            f"Failed to emit {event_name} event for {doc.name}: {str(e)}", "Expense Event Emission Error"
        )


def emit_expense_claim_cancelled(doc, method=None):
    """Emit event when an expense claim is cancelled"""
    if doc.doctype != "Expense Claim" or doc.docstatus != 2:
        return

    # Check volunteer link
    volunteer = None
    member = None
    if doc.employee:
        volunteer_name = frappe.db.get_value("Volunteer", {"employee": doc.employee}, "name")
        if volunteer_name:
            volunteer = volunteer_name
            member = frappe.db.get_value("Volunteer", volunteer_name, "member")

    event_data = {
        "expense_claim": doc.name,
        "employee": doc.employee,
        "volunteer": volunteer,
        "member": member,
        "cancelled_on": frappe.utils.now(),
        "expense_type": "Volunteer Expense" if volunteer else "Regular Expense",
    }

    try:
        _emit_expense_event("expense_claim_cancelled", event_data)
    except Exception as e:
        frappe.log_error(
            f"Failed to emit expense_claim_cancelled event for {doc.name}: {str(e)}",
            "Expense Event Emission Error",
        )


def emit_expense_payment_made(doc, method=None):
    """
    Emit event when a payment is made against an expense claim.

    This is triggered when a Payment Entry references an Expense Claim.
    """
    if doc.doctype != "Payment Entry" or doc.docstatus != 1:
        return

    # Check if this payment is for expense claims
    expense_claims = []
    for ref in doc.references:
        if ref.reference_doctype == "Expense Claim":
            expense_claims.append(ref.reference_name)

    if not expense_claims:
        return

    # Process each expense claim
    for expense_claim in expense_claims:
        try:
            # Get expense claim details
            expense_doc = frappe.get_doc("Expense Claim", expense_claim)

            # Check volunteer link
            volunteer = None
            member = None
            if expense_doc.employee:
                volunteer_name = frappe.db.get_value("Volunteer", {"employee": expense_doc.employee}, "name")
                if volunteer_name:
                    volunteer = volunteer_name
                    member = frappe.db.get_value("Volunteer", volunteer_name, "member")

            event_data = {
                "payment_entry": doc.name,
                "expense_claim": expense_claim,
                "employee": expense_doc.employee,
                "volunteer": volunteer,
                "member": member,
                "payment_date": str(doc.posting_date),
                "paid_amount": doc.paid_amount,
                "payment_method": doc.mode_of_payment,
                "expense_type": "Volunteer Expense" if volunteer else "Regular Expense",
            }

            _emit_expense_event("expense_payment_made", event_data)

        except Exception as e:
            frappe.log_error(
                f"Failed to emit expense_payment_made event for {expense_claim}: {str(e)}",
                "Expense Payment Event Error",
            )


def _emit_expense_event(event_name, event_data):
    """
    Internal function to emit expense events to all subscribers.

    Uses Frappe's background job queue to ensure event processing
    doesn't block the main transaction.
    """
    # Get all registered subscribers for this event
    subscribers = _get_expense_event_subscribers(event_name)

    for subscriber in subscribers:
        # Special handling for member-specific updates
        if event_data.get("member") and "payment_history" in subscriber:
            # Use member-specific job name to serialize updates
            frappe.enqueue(
                method=subscriber,
                queue="short",
                job_name=f"expense_history_update_{event_data['member']}",
                timeout=300,
                **{
                    "event_name": event_name,
                    "event_data": event_data,
                },
            )
        else:
            # For other subscribers, use standard approach
            frappe.enqueue(
                method=subscriber,
                queue="short",
                job_name=f"{event_name}_{event_data.get('expense_claim')}_{subscriber}",
                **{
                    "event_name": event_name,
                    "event_data": event_data,
                },
            )


def _get_expense_event_subscribers(event_name):
    """
    Get all registered subscribers for a specific expense event.
    """
    # Mapping of events to their subscribers
    event_subscribers = {
        "expense_claim_approved": [
            "verenigingen.events.subscribers.expense_history_subscriber.handle_expense_claim_approved"
        ],
        "expense_claim_rejected": [
            "verenigingen.events.subscribers.expense_history_subscriber.handle_expense_claim_rejected"
        ],
        "expense_claim_cancelled": [
            "verenigingen.events.subscribers.expense_history_subscriber.handle_expense_claim_cancelled"
        ],
        "expense_payment_made": [
            "verenigingen.events.subscribers.expense_history_subscriber.handle_expense_payment_made"
        ],
    }

    return event_subscribers.get(event_name, [])
