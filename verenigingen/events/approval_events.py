"""
Member Approval Event System

Event-driven architecture for member application approval to prevent timestamp
conflicts and improve performance. Based on the successful invoice_events.py pattern.

This module emits events during member approval that trigger background processing
of non-critical operations, keeping the main approval transaction lightweight.
"""

import frappe
from frappe import _


def emit_member_approval_initiated(member_name, approval_data):
    """
    Emit event when member approval process begins.

    This triggers background processing of heavy operations while keeping
    the main approval transaction fast and conflict-free.

    Args:
        member_name: Member document name
        approval_data: Dict containing approval parameters
    """
    if not member_name:
        return

    # Skip event emission during bulk processing
    if getattr(frappe.flags, "bulk_member_approval", False):
        frappe.logger("events").info(
            f"Skipping approval event emission during bulk processing - member: {member_name}"
        )
        return

    event_data = {
        "member": member_name,
        "membership_type": approval_data.get("membership_type"),
        "chapter": approval_data.get("chapter"),
        "notes": approval_data.get("notes"),
        "create_invoice": approval_data.get("create_invoice", True),
        "approved_by": frappe.session.user,
        "approval_timestamp": frappe.utils.now(),
    }

    # Log the event emission for debugging
    frappe.logger("events").info(f"Emitting member_approval_initiated event for {member_name}")

    try:
        _emit_approval_event("member_approval_initiated", event_data)
    except Exception as e:
        # Log but don't fail - event emission should never block approval
        frappe.log_error(
            f"Failed to emit member_approval_initiated event for {member_name}: {str(e)}",
            "Approval Event Emission Error",
        )


def emit_member_approval_completed(member_name, completion_data):
    """
    Emit event when core member approval is complete.

    This triggers final background operations like notifications.
    """
    if not member_name:
        return

    # Skip event emission during bulk processing
    if getattr(frappe.flags, "bulk_member_approval", False):
        return

    event_data = {
        "member": member_name,
        "invoice": completion_data.get("invoice"),
        "user_account_status": completion_data.get("user_account_status"),
        "completion_timestamp": frappe.utils.now(),
    }

    frappe.logger("events").info(f"Emitting member_approval_completed event for {member_name}")

    try:
        _emit_approval_event("member_approval_completed", event_data)
    except Exception as e:
        frappe.log_error(
            f"Failed to emit member_approval_completed event for {member_name}: {str(e)}",
            "Approval Event Emission Error",
        )


def _emit_approval_event(event_name, event_data):
    """
    Internal function to emit approval events with member-specific job handling.

    Uses the same pattern as invoice_events.py to prevent concurrent updates
    to the same member by using member-specific job names with deduplication.
    """
    # Get all registered subscribers for this event
    subscribers = _get_approval_event_subscribers(event_name)

    member_name = event_data.get("member")

    for subscriber in subscribers:
        # Use member-specific job name to serialize updates per member
        # This prevents multiple background jobs from conflicting on the same member
        frappe.enqueue(
            method=subscriber,
            queue="short",
            job_name=f"approval_{event_name}_{member_name}",
            dedupe=True,  # Prevents multiple jobs for same member+event
            timeout=300,  # 5 minutes timeout
            delay=2,  # Allow main transaction to commit first
            **{  # Separate method arguments from enqueue parameters
                "event_name": event_name,
                "event_data": event_data,
            },
        )


def _get_approval_event_subscribers(event_name):
    """
    Get all registered subscribers for a specific approval event.

    This could be enhanced with database-stored subscriptions in the future.
    """
    event_subscribers = {
        "member_approval_initiated": [
            "verenigingen.events.subscribers.approval_subscribers.handle_customer_creation",
            "verenigingen.events.subscribers.approval_subscribers.handle_chapter_assignment",
            "verenigingen.events.subscribers.approval_subscribers.handle_iban_history_creation",
            "verenigingen.events.subscribers.approval_subscribers.handle_user_account_creation",
        ],
        "member_approval_completed": [
            "verenigingen.events.subscribers.approval_subscribers.handle_approval_notification",
            "verenigingen.events.subscribers.approval_subscribers.handle_volunteer_activation",
        ],
    }

    return event_subscribers.get(event_name, [])
