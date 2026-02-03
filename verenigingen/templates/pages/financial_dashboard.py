import frappe


def get_context(context):
    """Redirect to unified payment dashboard"""
    frappe.local.flags.redirect_location = "/payment_dashboard"
    raise frappe.Redirect
