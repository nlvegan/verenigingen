import frappe
from frappe import _


def get_context(context):
    """Get context for expense claim page"""

    # Require login
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to access the expense claim form"), frappe.PermissionError)

    context.no_cache = 1
    context.show_sidebar = True
    context.title = _("Submit Expense Claim")

    # Check if user has volunteer record
    user_email = frappe.session.user
    member = frappe.db.get_value("Member", {"email": user_email}, "name")

    if member:
        volunteer = frappe.db.get_value("Volunteer", {"member": member}, "name")
        if not volunteer:
            # Try direct email lookup
            volunteer = frappe.db.get_value("Volunteer", {"email": user_email}, "name")
    else:
        # Try direct email lookup
        volunteer = frappe.db.get_value("Volunteer", {"email": user_email}, "name")

    if not volunteer:
        context.error_message = _(
            "No volunteer record found for your account. Please contact your chapter administrator to create a volunteer profile before submitting expenses."
        )
        context.show_form = False
    else:
        context.show_form = True
        context.volunteer = volunteer

    return context
