# Copyright (c) 2025, Verenigingen
# License: MIT

"""
Ponto Payment Link Page

Customer-facing page where users can view and authorize Ponto payment requests.
This page displays payment details and redirects users to their bank for authorization.
"""

import frappe
from frappe import _


def get_context(context):
    """Get context for Ponto payment page."""
    context.no_cache = 1

    # Get payment link ID from URL
    payment_link_id = frappe.form_dict.get("id")

    if not payment_link_id:
        context.error = _("No payment link specified")
        context.payment_link = None
        return context

    try:
        # Get the payment link document
        payment_link = frappe.get_doc("Ponto Payment Link", payment_link_id)

        # Build context
        context.payment_link = {
            "name": payment_link.name,
            "amount": payment_link.amount,
            "currency": payment_link.currency,
            "description": payment_link.description,
            "creditor_name": payment_link.creditor_name,
            "status": payment_link.status,
            "redirect_link": payment_link.redirect_link,
            "reference_doctype": payment_link.reference_doctype,
            "reference_name": payment_link.reference_name,
        }

        # Add member info if linked
        if payment_link.member:
            member = frappe.get_doc("Member", payment_link.member)
            context.payment_link["member_name"] = member.full_name

        # Add invoice info if linked
        if payment_link.sales_invoice:
            invoice = frappe.get_doc("Sales Invoice", payment_link.sales_invoice)
            context.payment_link["invoice_name"] = invoice.name
            context.payment_link["invoice_date"] = invoice.posting_date

        # Check status and provide appropriate messaging
        if payment_link.status == "Executed":
            context.payment_complete = True
            context.success_message = _("Payment has been completed successfully. Thank you!")
        elif payment_link.status in ("Rejected", "Cancelled", "Failed"):
            context.payment_failed = True
            context.error = _("This payment request is no longer valid: {0}").format(payment_link.status)
        elif payment_link.status == "Expired":
            context.payment_expired = True
            context.error = _("This payment request has expired.")
        elif not payment_link.redirect_link:
            context.error = _("Payment link is not yet ready. Please try again later.")

    except frappe.DoesNotExistError:
        context.error = _("Payment link not found")
        context.payment_link = None
    except Exception as e:
        frappe.log_error(f"Ponto payment page error: {e}", "Ponto Payment Page Error")
        context.error = _("An error occurred loading the payment details")
        context.payment_link = None

    return context
