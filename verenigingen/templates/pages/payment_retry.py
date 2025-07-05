"""
Context for payment retry page
"""

import frappe
from frappe import _


def get_context(context):
    """Get context for payment retry page"""

    context.no_cache = 1
    context.show_sidebar = False
    context.title = _("Complete Your Payment")

    # Get member and invoice from URL
    member_id = frappe.form_dict.get("member")
    invoice_id = frappe.form_dict.get("invoice")

    if member_id and invoice_id:
        try:
            member = frappe.get_doc("Member", member_id)
            invoice = frappe.get_doc("Sales Invoice", invoice_id)

            # Verify the invoice belongs to this member
            if invoice.member == member_id:
                context.member = member
                context.invoice = invoice

                # Get available payment methods
                context.payment_methods = frappe.get_all(
                    "Mode of Payment", filters={"enabled": 1}, fields=["name", "type"]
                )
            else:
                context.member = None
                context.invoice = None
        except Exception:
            context.member = None
            context.invoice = None
    else:
        context.member = None
        context.invoice = None

    return context
