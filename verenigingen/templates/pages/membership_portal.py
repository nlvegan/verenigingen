import frappe
from frappe import _


def get_context(context):
    """Redirect to modern member portal"""

    # Require login
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to access this page"), frappe.PermissionError)

    # Redirect to the modern, branded member portal
    frappe.local.flags.redirect_location = "/member_portal"
    raise frappe.Redirect
