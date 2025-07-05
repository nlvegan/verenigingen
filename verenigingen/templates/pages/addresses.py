"""
Redirect page for addresses - redirects to my_addresses
"""

import frappe


def get_context(context):
    """Redirect to my_addresses page"""
    frappe.local.response["type"] = "redirect"
    frappe.local.response["location"] = "/my_addresses"
