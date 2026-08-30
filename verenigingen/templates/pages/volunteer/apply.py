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

    # The form's own age hint and its client-side birth-date check must not carry
    # their own literal: raising minimum_volunteer_age in Settings has to move the
    # form and the endpoint together, or the page contradicts the API that rejects
    # the submission (#659). Read directly rather than through
    # AgeValidator._get_configurable_min_age, which THROWS on a missing/zero
    # setting -- a page must not 500 over that. A falsy value renders no hint and
    # skips the browser-side check; the server refuses either way, and the browser
    # is never the authority here.
    context.minimum_volunteer_age = frappe.db.get_single_value(
        "Verenigingen Settings", "minimum_volunteer_age"
    )

    return context
