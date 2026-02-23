"""
Volunteer Portal - Multi-Item Expense Claim Page

Alternative expense portal with Vue-based multi-item expense form.
Uses centralized utilities from volunteer_expense_portal_utils.py.

URL: /volunteer-portal/expense_claim_new
"""

import frappe
from frappe import _

from verenigingen.utils.member_utils import get_current_user_member_name, require_login

# Import centralized utilities
from verenigingen.utils.volunteer_expense_portal_utils import (
    build_base_expense_context,
    get_empty_statistics,
    get_theme_settings,
    get_volunteer_expense_statistics,
)


def get_context(context):
    """Get context for multi-item expense claim page."""
    require_login()

    context.no_cache = 1
    context.show_sidebar = True
    context.title = _("Submit Expense Claim")

    # Get theme settings
    context.theme_settings = get_theme_settings()

    # Always set expense_stats to prevent template errors
    context.expense_stats = get_empty_statistics()

    # Get current user's volunteer record
    member = get_current_user_member_name()

    if member:
        volunteer = frappe.db.get_value("Volunteer", {"member": member}, "name")
    else:
        volunteer = None

    if not volunteer:
        context.error_message = _(
            "No volunteer record found for your account. Please contact your chapter administrator."
        )
        context.show_form = False
        return context

    context.show_form = True
    context.volunteer = frappe.get_doc("Volunteer", volunteer)

    # Get expense statistics (optional, for dashboard display)
    try:
        stats, debug_msg = get_volunteer_expense_statistics(volunteer)
        context.expense_stats = stats
        context.stats_debug = debug_msg
    except Exception:
        # Keep default empty stats on error
        pass

    return context
