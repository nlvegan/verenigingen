"""
Context for chapters page
"""

import frappe
from frappe import _


def get_context(context):
    """Get context for chapters page"""

    # Page configuration
    context.no_cache = 1
    context.show_sidebar = True
    context.title = _("Chapters")

    # Check if user is logged in
    if frappe.session.user == "Guest":
        # Allow guest users to view the page, the JavaScript will handle the display
        context.logged_in = False
    else:
        context.logged_in = True

        # Get member record for logged in user
        member = frappe.db.get_value("Member", {"email": frappe.session.user}, "name")
        context.member = member

    return context
