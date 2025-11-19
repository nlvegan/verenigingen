"""
Context for application status page
"""

import frappe
from frappe import _

from verenigingen.utils.member_utils import get_current_user_member_name, get_member_chapters


def get_context(context):
    """Get context for application status page"""

    context.no_cache = 1
    context.show_sidebar = False
    context.title = _("Application Status")

    # Get member from URL parameter or logged in user
    member_id = frappe.form_dict.get("id")

    if not member_id and frappe.session.user != "Guest":
        # Try to find member by email
        member_id = get_current_user_member_name()

    if member_id:
        member = frappe.get_doc("Member", member_id)
        context.member = member
        context.member_chapters = get_member_chapters(member_id)
    else:
        context.member = None
        context.member_chapters = []

    return context
