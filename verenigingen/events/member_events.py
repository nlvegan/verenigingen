"""
Member Event Emission System

This module handles event emission for member status changes and lifecycle events.
It integrates with the background processing system to enable async operations
triggered by member document updates.

Events emitted:
- member_status_changed: Application status changes (Pending -> Approved)
- member_lifecycle_changed: General member status changes (Active -> Suspended -> Terminated)

These events can trigger background operations like:
- Chapter assignment updates
- User account management
- Email notifications
- Cache invalidation
"""

import frappe


def emit_member_status_changed(member_name, status_data):
    """
    Emit event when member application status changes.

    This enables background processing for approval workflow operations.

    Args:
        member_name (str): Member document name
        status_data (dict): Contains old_status, new_status, status_type
    """

    # Skip during bulk operations to prevent event flood
    if getattr(frappe.flags, "bulk_member_operations", False):
        return

    event_data = {"member": member_name, **status_data, "timestamp": frappe.utils.now()}

    frappe.logger("events").info(f"Emitting member_status_changed event for {member_name}")

    try:
        _emit_member_event("member_status_changed", event_data)
    except Exception as e:
        frappe.log_error(
            f"Failed to emit member_status_changed event for {member_name}: {str(e)}",
            "Member Event Emission Error",
        )


def emit_member_lifecycle_changed(member_name, lifecycle_data):
    """
    Emit event when member lifecycle status changes.

    This enables background processing for member status transitions.

    Args:
        member_name (str): Member document name
        lifecycle_data (dict): Contains old_status, new_status, status_type
    """

    # Skip during bulk operations to prevent event flood
    if getattr(frappe.flags, "bulk_member_operations", False):
        return

    event_data = {"member": member_name, **lifecycle_data, "timestamp": frappe.utils.now()}

    frappe.logger("events").info(f"Emitting member_lifecycle_changed event for {member_name}")

    try:
        _emit_member_event("member_lifecycle_changed", event_data)
    except Exception as e:
        frappe.log_error(
            f"Failed to emit member_lifecycle_changed event for {member_name}: {str(e)}",
            "Member Event Emission Error",
        )


def _emit_member_event(event_name, event_data):
    """
    Internal function to emit member events with background job handling.

    Uses the same pattern as approval_events.py for consistency.
    """

    member_name = event_data.get("member")

    # Get subscribers for this event
    subscribers = _get_member_event_subscribers(event_name)

    for subscriber in subscribers:
        frappe.enqueue(
            method=subscriber,
            queue="short",  # Member events are typically quick operations
            job_name=f"member_{event_name}_{member_name}",
            dedupe=True,  # Prevent duplicate events for same member
            timeout=300,
            delay=1,  # Small delay to ensure member save is committed
            **{"event_name": event_name, "event_data": event_data},
        )


def _get_member_event_subscribers(event_name):
    """Get list of background job handlers for member events"""

    event_subscribers = {
        "member_status_changed": [
            "verenigingen.events.subscribers.member_subscribers.handle_status_change_notifications",
            "verenigingen.events.subscribers.member_subscribers.handle_chapter_assignment_updates",
        ],
        "member_lifecycle_changed": [
            "verenigingen.events.subscribers.member_subscribers.handle_lifecycle_notifications",
            "verenigingen.events.subscribers.member_subscribers.handle_user_account_updates",
            "verenigingen.events.subscribers.member_subscribers.handle_cache_invalidation",
        ],
    }

    return event_subscribers.get(event_name, [])
