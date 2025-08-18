"""
Mollie Dashboard Web Page
"""

import frappe
from frappe import _


def get_context(context):
    """
    Build context for Mollie Dashboard page
    """
    # Check if user is logged in
    if frappe.session.user == "Guest":
        frappe.throw(_("You need to be logged in to access this page"), frappe.PermissionError)

    # Check permissions - user should have access to Mollie Settings or be System Manager
    if not (
        "System Manager" in frappe.get_roles()
        or "Verenigingen Administrator" in frappe.get_roles()
        or frappe.has_permission("Mollie Settings", "read")
    ):
        frappe.throw(_("You don't have permission to access this page"), frappe.PermissionError)

    context.title = "Mollie Financial Dashboard"
    context.no_cache = 1

    return context
