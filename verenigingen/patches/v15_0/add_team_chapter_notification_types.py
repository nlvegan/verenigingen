"""
Add new notification types for team member and chapter member notifications.

This patch adds notification keys that were introduced for:
- Team member added/removed notifications
- Chapter member joined/left notifications
"""

import frappe


def execute():
    """Add new notification types to Email Configuration if they don't exist."""
    # Check if Email Configuration exists
    if not frappe.db.exists("DocType", "Email Configuration"):
        return

    if not frappe.db.exists("Email Configuration", "Email Configuration"):
        return

    config = frappe.get_single("Email Configuration")

    new_types = [
        {
            "notification_key": "team_member_added",
            "label": "Team Member Added",
            "category": "Volunteer",
            "enabled": 1,
            "priority": "Low",
            "cooldown_minutes": 60,
            "email_template": "team_role_notification",
            "recipient_policy": "Document-Field",
            "recipient_field": "volunteer.email",
            "description": "Email sent when volunteer is added to a team",
        },
        {
            "notification_key": "team_member_removed",
            "label": "Team Member Removed",
            "category": "Volunteer",
            "enabled": 1,
            "priority": "Low",
            "cooldown_minutes": 60,
            "email_template": "team_role_notification",
            "recipient_policy": "Document-Field",
            "recipient_field": "volunteer.email",
            "description": "Email sent when volunteer is removed from a team",
        },
        {
            "notification_key": "chapter_member_joined",
            "label": "Member Joined Chapter",
            "category": "Chapter",
            "enabled": 1,
            "priority": "Low",
            "cooldown_minutes": 60,
            "email_template": "chapter_board_notification",
            "recipient_policy": "Document-Field",
            "recipient_field": "member.email",
            "description": "Welcome email sent when member joins a chapter",
        },
        {
            "notification_key": "chapter_member_left",
            "label": "Member Left Chapter",
            "category": "Chapter",
            "enabled": 1,
            "priority": "Low",
            "cooldown_minutes": 60,
            "email_template": "chapter_board_notification",
            "recipient_policy": "Document-Field",
            "recipient_field": "member.email",
            "description": "Farewell email sent when member leaves a chapter",
        },
        # Member Status Notifications
        {
            "notification_key": "member_activated",
            "label": "Membership Activated",
            "category": "Member",
            "enabled": 1,
            "priority": "Medium",
            "cooldown_minutes": 60,
            "email_template": "member_lifecycle_notification",
            "recipient_policy": "Document-Field",
            "recipient_field": "email",
            "description": "Email sent when member status changes to Active",
        },
        {
            "notification_key": "member_suspended",
            "label": "Membership Suspended",
            "category": "Member",
            "enabled": 1,
            "priority": "High",
            "cooldown_minutes": 60,
            "email_template": "member_lifecycle_notification",
            "recipient_policy": "Document-Field",
            "recipient_field": "email",
            "description": "Email sent when member status changes to Suspended",
        },
        {
            "notification_key": "member_terminated",
            "label": "Membership Terminated",
            "category": "Member",
            "enabled": 1,
            "priority": "High",
            "cooldown_minutes": 60,
            "email_template": "member_lifecycle_notification",
            "recipient_policy": "Document-Field",
            "recipient_field": "email",
            "description": "Email sent when membership is terminated",
        },
        {
            "notification_key": "member_status_change",
            "label": "Member Status Change",
            "category": "Member",
            "enabled": 1,
            "priority": "Low",
            "cooldown_minutes": 60,
            "email_template": "member_lifecycle_notification",
            "recipient_policy": "Document-Field",
            "recipient_field": "email",
            "description": "Generic notification for other member status changes",
        },
    ]

    existing_keys = {nt.notification_key for nt in config.notification_types}
    added = 0

    for nt in new_types:
        if nt["notification_key"] not in existing_keys:
            config.append("notification_types", nt)
            added += 1

    if added > 0:
        config.flags.ignore_permissions = True
        config.save()
        frappe.db.commit()

    frappe.logger().info(f"Added {added} new notification types to Email Configuration")
