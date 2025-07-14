import frappe
from frappe import _

from verenigingen.templates.pages.volunteer.expenses import get_expense_statistics, get_user_volunteer_record


def get_context(context):
    """Get context for expense claim page"""

    # Require login
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to access the expense claim form"), frappe.PermissionError)

    context.no_cache = 1
    context.show_sidebar = True
    context.title = _("Submit Expense Claim")

    # Get current user's volunteer record
    volunteer = get_user_volunteer_record()
    if not volunteer:
        context.error_message = _(
            "No volunteer record found for your account. Please contact your chapter administrator to create a volunteer profile before submitting expenses."
        )
        context.show_form = False
        return context

    context.volunteer = volunteer
    context.show_form = True

    # Get expense statistics
    context.expense_stats = get_expense_statistics(volunteer.name)

    return context
