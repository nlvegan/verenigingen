"""
SEPA Reconciliation Dashboard Page Controller
"""

import frappe
from frappe import _


def get_context(context):
    """Get context for SEPA reconciliation dashboard"""

    # Require login and appropriate permissions
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to access this page"), frappe.PermissionError)

    # Check user permissions for banking functions
    if not frappe.has_permission("Bank Transaction", "read"):
        frappe.throw(_("You don't have permission to access banking functions"), frappe.PermissionError)

    context.no_cache = 1
    context.title = _("SEPA Reconciliation Dashboard")
    context.show_sidebar = False

    return context


def has_website_permission(doc, ptype, user, verbose=False):
    """Check website permission for SEPA reconciliation dashboard"""
    # Only logged-in users with banking permissions can access
    if user == "Guest":
        return False

    # Check if user has banking or accounting role
    user_roles = frappe.get_roles(user)
    banking_roles = ["Accounts Manager", "Accounts User", "System Manager", "Administrator"]

    return any(role in user_roles for role in banking_roles)
