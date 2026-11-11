"""
Context for payment retry page
"""

from urllib.parse import quote

import frappe
from frappe import _

from verenigingen.utils.member_utils import get_current_user_member_name


def get_context(context):
    """Get context for payment retry page"""

    context.no_cache = 1
    context.show_sidebar = False
    context.title = _("Complete Your Payment")

    # Get member and invoice from URL
    member_id = frappe.form_dict.get("member")
    invoice_id = frappe.form_dict.get("invoice")

    # A reminder mail links here. A logged-out member logs in and comes back to this same URL; the
    # ownership guard below still applies to whoever arrives (#2109). No guest access.
    if frappe.session.user == "Guest":
        back = f"/payment_retry?member={quote(member_id or '', safe='')}&invoice={quote(invoice_id or '', safe='')}"
        frappe.local.flags.redirect_location = f"/login?redirect-to={quote(back, safe='')}"
        raise frappe.Redirect

    # Member.autoname and Sales Invoice's naming_series are both sequential
    # and guessable, and "the invoice belongs to this member" only checks
    # that the two *supplied* parameters are mutually consistent -- it is
    # not an ownership check against the requesting session (#1052). Require
    # the caller's own logged-in member to match before disclosing anything;
    # a Guest (no session to check) or a mismatched id is refused exactly
    # like an unknown id.
    own_member_id = get_current_user_member_name() if frappe.session.user != "Guest" else None

    if member_id and invoice_id and member_id == own_member_id:
        try:
            member = frappe.get_doc("Member", member_id)
            invoice = frappe.get_doc("Sales Invoice", invoice_id)

            # Verify the invoice belongs to this member. Most real invoices leave `member` blank
            # and carry only the member's Customer, which is still the member's own invoice.
            if invoice.member == member_id or (not invoice.member and invoice.customer == member.customer):
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
