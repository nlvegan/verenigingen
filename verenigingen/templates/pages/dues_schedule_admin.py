# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

import frappe
from frappe import _

from verenigingen.utils.dues_schedule_auto_creator import (
    preview_missing_dues_schedules,
    run_auto_creation_manually,
)


def get_context(context):
    """Context for dues schedule admin page"""
    # Check permissions
    if not frappe.has_permission("Membership Dues Schedule", "create"):
        frappe.throw(_("You don't have permission to access this page"), frappe.PermissionError)

    # Get preview of members without schedules
    context.preview_members = preview_missing_dues_schedules()

    # Get statistics
    context.stats = get_dues_schedule_stats()

    # Page settings
    context.no_cache = 1
    context.show_sidebar = False
    context.title = _("Dues Schedule Administration")

    return context


def get_dues_schedule_stats():
    """Get statistics about dues schedules"""
    stats = {}

    # Total members with active memberships
    stats["total_active_members"] = frappe.db.count(
        "Membership", filters={"status": "Active", "docstatus": 1}
    )

    # Members with active dues schedules
    stats["members_with_schedules"] = frappe.db.sql(
        """
        SELECT COUNT(DISTINCT m.member)
        FROM `tabMembership` m
        INNER JOIN `tabMembership Dues Schedule` mds ON m.member = mds.member
        WHERE m.status = 'Active'
        AND m.docstatus = 1
        AND mds.status = 'Active'
    """
    )[0][0]

    # Members without schedules
    stats["members_without_schedules"] = frappe.db.sql(
        """
        SELECT COUNT(DISTINCT m.member)
        FROM `tabMembership` m
        WHERE m.status = 'Active'
        AND m.docstatus = 1
        AND m.membership_type IS NOT NULL
        AND NOT EXISTS (
            SELECT 1
            FROM `tabMembership Dues Schedule` mds
            WHERE mds.member = m.member
            AND mds.status = 'Active'
        )
    """
    )[0][0]

    # Total dues schedules
    stats["total_schedules"] = frappe.db.count("Membership Dues Schedule")

    # Active schedules
    stats["active_schedules"] = frappe.db.count("Membership Dues Schedule", filters={"status": "Active"})

    # Templates
    stats["schedule_templates"] = frappe.db.count("Membership Dues Schedule", filters={"is_template": 1})

    return stats


@frappe.whitelist()
def trigger_auto_creation():
    """Trigger the auto-creation process manually"""
    if not frappe.has_permission("Membership Dues Schedule", "create"):
        frappe.throw(_("You don't have permission to create dues schedules"))

    result = run_auto_creation_manually()

    return {
        "success": True,
        "message": _("Auto-creation completed. Created {0} schedules, {1} errors encountered.").format(
            result.get("created", 0), result.get("errors", 0)
        ),
        "details": result,
    }
