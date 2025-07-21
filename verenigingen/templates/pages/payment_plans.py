"""
Context for the payment plans page
"""

import frappe
from frappe import _


def get_context(context):
    """Get context for payment plans page"""

    # Set page properties
    context.no_cache = 1
    context.show_sidebar = False
    context.title = _("Payment Plans")

    # Check if user is logged in
    if frappe.session.user == "Guest":
        frappe.local.flags.redirect_location = "/login"
        raise frappe.Redirect

    # Check if user is a member
    member = frappe.db.get_value("Member", {"email": frappe.session.user}, "name")
    if not member:
        context.no_member = True
        context.message = _("You must be a registered member to access payment plans.")
        return context

    context.member = member

    # Get member details
    member_doc = frappe.get_doc("Member", member)
    context.member_name = member_doc.full_name

    # Check if member has any dues schedules that could benefit from payment plans
    dues_schedules = frappe.get_all(
        "Membership Dues Schedule",
        filters={"member": member, "status": ["in", ["Active", "Grace Period"]]},
        fields=["name", "dues_rate", "billing_frequency"],
    )

    context.has_dues_schedules = len(dues_schedules) > 0
    context.dues_schedules = dues_schedules

    return context


# Add route configuration
no_cache = 1
sitemap = 0  # Don't include in sitemap
