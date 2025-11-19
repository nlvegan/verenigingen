"""
Bank Details Success Page
Shows confirmation after successful bank details update
"""

import frappe
from frappe import _


def get_context(context):
    """Get context for bank details success page"""

    # Require login
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to access this page"), frappe.PermissionError)

    context.no_cache = 1
    context.show_sidebar = True
    context.title = _("Bank Details Updated")

    # Get success messages from session
    success_messages = frappe.session.get("bank_details_success", [])
    if not success_messages:
        # If no success message, redirect to bank details form
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = "/bank_details"
        return

    context.success_messages = success_messages

    # Check if SEPA was enabled based on success messages
    sepa_messages = [
        "A new SEPA Direct Debit mandate has been created",
        "Your SEPA mandate has been updated",
        "Your existing SEPA Direct Debit mandate remains active",
    ]

    context.sepa_enabled = any(any(sepa_msg in msg for sepa_msg in sepa_messages) for msg in success_messages)

    # Clear success messages from session after displaying
    if "bank_details_success" in frappe.session:
        del frappe.session["bank_details_success"]

    return context


def has_website_permission(doc, ptype, user, verbose=False):
    """Check website permission for bank details success page"""
    # Only logged-in users can access
    if user == "Guest":
        return False

    # Check if user has a member record
    member = frappe.db.get_value("Member", {"email": user})
    return bool(member)
