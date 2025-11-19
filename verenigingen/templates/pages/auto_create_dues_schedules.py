import frappe
from frappe import _


def get_context(context):
    """Get context for auto-create dues schedules page"""
    # Check permissions
    if not frappe.has_permission("Membership Dues Schedule", "create"):
        frappe.throw(_("You do not have permission to create dues schedules"), frappe.PermissionError)

    # Add page title and breadcrumbs
    context.title = _("Auto-Create Dues Schedules")
    context.parents = [{"title": _("Tools"), "route": "/tools"}]

    # Set flags for template
    context.no_cache = 1
    context.show_sidebar = False

    return context
