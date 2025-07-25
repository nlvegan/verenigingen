"""
Schedule Maintenance Admin Page
Web interface for verenigingen administrators to manage dues schedules
"""

import frappe
from frappe import _


def get_context(context):
    """Setup context for schedule maintenance page"""

    # Check if user has required permissions
    if not frappe.has_permission("Membership Dues Schedule", "read"):
        frappe.throw(_("You don't have permission to access schedule maintenance"), frappe.PermissionError)

    context.title = _("Schedule Maintenance")
    context.page_title = _("Dues Schedule Maintenance Tool")

    # Check if user can perform cleanup actions
    context.can_cleanup = frappe.has_permission(
        "Membership Dues Schedule", "write"
    ) and frappe.has_permission("Membership Dues Schedule", "delete")

    return context
