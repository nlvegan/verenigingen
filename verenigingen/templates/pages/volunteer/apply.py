"""
Volunteer Application Page
Dedicated form for volunteer applications
"""

import frappe
from frappe import _

from verenigingen.utils.member_utils import get_current_user_member_name


def get_context(context):
    """Get context for volunteer application page"""

    # Set page properties
    context.no_cache = 1
    context.show_sidebar = False
    context.title = _("Volunteer Application")

    # Check if user is already a member
    if frappe.session.user != "Guest":
        existing_member = get_current_user_member_name()
        if existing_member:
            context.already_member = True
            context.member_name = existing_member
            return context

    # Get organization logo from Brand Settings
    from verenigingen.verenigingen.doctype.brand_settings.brand_settings import get_organization_logo

    context.organization_logo = get_organization_logo()
    context.already_member = False

    return context
