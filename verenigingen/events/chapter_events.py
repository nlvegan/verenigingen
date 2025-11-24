"""
Chapter Event Emission System

This module handles event emission for chapter status changes and lifecycle events.
It integrates with the background processing system to enable async operations
triggered by chapter document updates.

Events emitted:
- chapter_board_changed: Board member additions, removals, role changes
- chapter_membership_changed: Member joins/leaves chapter
- chapter_settings_changed: Configuration and settings updates

These events can trigger background operations like:
- User role assignment and removal
- Notification sending
- Cache invalidation
- Audit logging
- Integration with volunteer system
"""

import frappe


def emit_chapter_board_changed(chapter_name, board_data):
    """
    Emit event when chapter board composition changes.

    This enables background processing for board member operations.

    Args:
        chapter_name (str): Chapter document name
        board_data (dict): Contains volunteer, action, role, old_role, etc.
    """

    # Skip during bulk operations to prevent event flood
    if getattr(frappe.flags, "bulk_chapter_operations", False) or getattr(
        frappe.flags, "in_bulk_import", False
    ):
        return

    event_data = {"chapter": chapter_name, **board_data, "timestamp": frappe.utils.now()}

    frappe.logger("events").info(f"Emitting chapter_board_changed event for {chapter_name}")

    try:
        _emit_chapter_event("chapter_board_changed", event_data)
    except Exception as e:
        frappe.log_error(
            f"Failed to emit chapter_board_changed event for {chapter_name}: {str(e)}",
            "Chapter Event Emission Error",
        )


def emit_chapter_membership_changed(chapter_name, membership_data):
    """
    Emit event when chapter membership changes.

    This enables background processing for member join/leave operations.

    Args:
        chapter_name (str): Chapter document name
        membership_data (dict): Contains member, action, reason, etc.
    """

    # Skip during bulk operations to prevent event flood
    if getattr(frappe.flags, "bulk_chapter_operations", False) or getattr(
        frappe.flags, "in_bulk_import", False
    ):
        return

    event_data = {"chapter": chapter_name, **membership_data, "timestamp": frappe.utils.now()}

    frappe.logger("events").info(f"Emitting chapter_membership_changed event for {chapter_name}")

    try:
        _emit_chapter_event("chapter_membership_changed", event_data)
    except Exception as e:
        frappe.log_error(
            f"Failed to emit chapter_membership_changed event for {chapter_name}: {str(e)}",
            "Chapter Event Emission Error",
        )


def emit_chapter_settings_changed(chapter_name, settings_data):
    """
    Emit event when chapter settings/configuration changes.

    This enables background processing for configuration updates.

    Args:
        chapter_name (str): Chapter document name
        settings_data (dict): Contains changed fields and their values
    """

    # Skip during bulk operations to prevent event flood
    if getattr(frappe.flags, "bulk_chapter_operations", False) or getattr(
        frappe.flags, "in_bulk_import", False
    ):
        return

    event_data = {"chapter": chapter_name, **settings_data, "timestamp": frappe.utils.now()}

    frappe.logger("events").info(f"Emitting chapter_settings_changed event for {chapter_name}")

    try:
        _emit_chapter_event("chapter_settings_changed", event_data)
    except Exception as e:
        frappe.log_error(
            f"Failed to emit chapter_settings_changed event for {chapter_name}: {str(e)}",
            "Chapter Event Emission Error",
        )


def _emit_chapter_event(event_name, event_data):
    """
    Internal function to emit chapter events with background job handling.

    Uses the same pattern as approval_events.py and member_events.py for consistency.
    """

    chapter_name = event_data.get("chapter")

    # Get subscribers for this event
    subscribers = _get_chapter_event_subscribers(event_name)

    # CRITICAL: Pass bulk import flag as job parameter to handle cross-process coordination
    # Process-local frappe.flags don't propagate to background worker processes
    is_bulk_import = getattr(frappe.flags, "in_bulk_import", False) or getattr(
        frappe.flags, "bulk_member_operations", False
    )

    for subscriber in subscribers:
        frappe.enqueue(
            method=subscriber,
            queue="short",  # Chapter events are typically quick operations
            job_name=f"chapter_{event_name}_{chapter_name}",
            dedupe=True,  # Prevent duplicate events for same chapter
            timeout=300,
            delay=1,  # Skip checks in subscribers handle bulk imports
            is_bulk_import=is_bulk_import,  # Pass bulk mode to worker process
            **{"event_name": event_name, "event_data": event_data},
        )


def _get_chapter_event_subscribers(event_name):
    """Get list of background job handlers for chapter events"""

    event_subscribers = {
        "chapter_board_changed": [
            "verenigingen.events.subscribers.chapter_subscribers.handle_board_role_assignments",
            "verenigingen.events.subscribers.chapter_subscribers.handle_board_notifications",
            "verenigingen.events.subscribers.chapter_subscribers.handle_volunteer_sync",
        ],
        "chapter_membership_changed": [
            "verenigingen.events.subscribers.chapter_subscribers.handle_membership_notifications",
            "verenigingen.events.subscribers.chapter_subscribers.handle_member_role_updates",
            "verenigingen.events.subscribers.chapter_subscribers.handle_cache_invalidation",
        ],
        "chapter_settings_changed": [
            "verenigingen.events.subscribers.chapter_subscribers.handle_settings_notifications",
            "verenigingen.events.subscribers.chapter_subscribers.handle_permissions_updates",
            "verenigingen.events.subscribers.chapter_subscribers.handle_website_updates",
        ],
    }

    return event_subscribers.get(event_name, [])
