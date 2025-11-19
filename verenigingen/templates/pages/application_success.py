"""
Context for application success page
"""

import frappe
from frappe import _


def get_context(context):
    """Get context for application success page"""

    context.no_cache = 1
    context.show_sidebar = False
    context.title = _("Application Submitted Successfully")

    # Get member ID from URL parameter
    member_id = frappe.form_dict.get("id")
    payment_url = frappe.form_dict.get("payment_url")

    context.member_id = member_id
    context.payment_url = payment_url

    return context
