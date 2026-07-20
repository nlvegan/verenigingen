"""
Team Event Emission System

This module handles event emission for team status changes and lifecycle events.
It integrates with the background processing system to enable async operations
triggered by team document updates.

Events emitted:
- team_membership_changed: Team member additions, removals, role changes
- team_settings_changed: Team configuration and settings updates
- team_leadership_changed: Team lead changes

These events can trigger background operations like:
- Assignment history updates
- Role profile management
- Volunteer integration
- Notification sending
- Cache invalidation
"""

import frappe


def emit_team_membership_changed(team_name, membership_data):
    """
    Emit event when team membership changes.

    This enables background processing for team member operations.

    Args:
        team_name (str): Team document name
        membership_data (dict): Contains volunteer, action, role, old_role, etc.
    """

    # Skip during bulk operations to prevent event flood (parity with member/chapter)
    if getattr(frappe.flags, "bulk_team_operations", False) or getattr(frappe.flags, "in_bulk_import", False):
        return

    event_data = {"team": team_name, **membership_data, "timestamp": frappe.utils.now()}

    frappe.logger("events").info(f"Emitting team_membership_changed event for {team_name}")

    try:
        _emit_team_event("team_membership_changed", event_data)
    except Exception as e:
        frappe.log_error(
            f"Failed to emit team_membership_changed event for {team_name}: {str(e)}",
            "Team Event Emission Error",
        )


def emit_team_settings_changed(team_name, settings_data):
    """
    Emit event when team settings/configuration changes.

    This enables background processing for configuration updates.

    Args:
        team_name (str): Team document name
        settings_data (dict): Contains changed fields and their values
    """

    # Skip during bulk operations to prevent event flood (parity with member/chapter)
    if getattr(frappe.flags, "bulk_team_operations", False) or getattr(frappe.flags, "in_bulk_import", False):
        return

    event_data = {"team": team_name, **settings_data, "timestamp": frappe.utils.now()}

    frappe.logger("events").info(f"Emitting team_settings_changed event for {team_name}")

    try:
        _emit_team_event("team_settings_changed", event_data)
    except Exception as e:
        frappe.log_error(
            f"Failed to emit team_settings_changed event for {team_name}: {str(e)}",
            "Team Event Emission Error",
        )


def emit_team_leadership_changed(team_name, leadership_data):
    """
    Emit event when team leadership changes.

    This enables background processing for team lead transitions.

    Args:
        team_name (str): Team document name
        leadership_data (dict): Contains old_lead, new_lead, reason, etc.
    """

    # Skip during bulk operations to prevent event flood (parity with member/chapter)
    if getattr(frappe.flags, "bulk_team_operations", False) or getattr(frappe.flags, "in_bulk_import", False):
        return

    event_data = {"team": team_name, **leadership_data, "timestamp": frappe.utils.now()}

    frappe.logger("events").info(f"Emitting team_leadership_changed event for {team_name}")

    try:
        _emit_team_event("team_leadership_changed", event_data)
    except Exception as e:
        frappe.log_error(
            f"Failed to emit team_leadership_changed event for {team_name}: {str(e)}",
            "Team Event Emission Error",
        )


def _emit_team_event(event_name, event_data):
    """Internal function to emit team events with background job handling."""
    from verenigingen.events.event_emitter import emit_event

    emit_event(
        event_name,
        event_data,
        _get_team_event_subscribers(event_name),
        entity_key="team",
        job_prefix="team",
        bulk_flag="bulk_team_operations",
    )


def _get_team_event_subscribers(event_name):
    """Get list of background job handlers for team events"""

    # NOTE: Role profile sync and Team Lead role assignment are handled synchronously
    # by doc_event hooks in team_role_profile_hooks.py (on_team_lead_change,
    # on_team_members_change). Do NOT add duplicate async handlers here.
    # Volunteer integration (handle_volunteer_integration) was removed — it referenced
    # a nonexistent `current_teams` field on Volunteer.
    event_subscribers = {
        "team_membership_changed": [
            "verenigingen.events.subscribers.team_subscribers.handle_assignment_history_updates",
            "verenigingen.events.subscribers.team_subscribers.handle_membership_notifications",
        ],
        "team_settings_changed": [
            "verenigingen.events.subscribers.team_subscribers.handle_settings_notifications",
            "verenigingen.events.subscribers.team_subscribers.handle_permissions_updates",
            "verenigingen.events.subscribers.team_subscribers.handle_cache_invalidation",
        ],
        "team_leadership_changed": [
            "verenigingen.events.subscribers.team_subscribers.handle_leadership_notifications",
            "verenigingen.events.subscribers.team_subscribers.handle_team_lead_permissions",
        ],
    }

    return event_subscribers.get(event_name, [])
