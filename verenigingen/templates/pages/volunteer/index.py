import frappe


def get_context(context):
    """Redirect to volunteer dashboard"""
    # Redirect to dashboard
    frappe.local.flags.redirect_location = "/volunteer/dashboard"
    raise frappe.Redirect
