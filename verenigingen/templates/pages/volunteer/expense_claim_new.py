import frappe
from frappe import _

from verenigingen.utils.member_utils import get_current_user_member_name, require_login


def get_context(context):
    """Get context for multi-item expense claim page"""

    require_login()

    context.no_cache = 1
    context.show_sidebar = True
    context.title = _("Submit Expense Claim")

    # Set theme settings to avoid template errors
    try:
        # owl_theme is an optional theme app; the except below supplies the
        # documented defaults when it is not installed.
        # doctype-ok: optional app, handled by the fallback below
        theme_settings = frappe.get_single("Owl Theme Settings")
        context.theme_settings = theme_settings
    except:
        context.theme_settings = frappe._dict(
            {
                "background_image": "",
                "background_color": "#ffffff",
                "navbar_color": "#ffffff",
                "primary_buttons_background_color": "#0066cc",
                "secondary_buttons_background_color": "#6c757d",
            }
        )

    # Always set expense_stats to prevent template errors
    context.expense_stats = frappe._dict(
        {
            "total_submitted": 0.0,
            "total_approved": 0.0,
            "pending_count": 0,
            "approved_count": 0,
        }
    )

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

    # expense_stats already set to empty values above - keeping it simple for now

    return context
