"""
Context for application status page
"""

import frappe
from frappe import _


def get_context(context):
    """Get context for application status page"""

    context.no_cache = 1
    context.show_sidebar = False
    context.title = _("Application Status")

    # Get member from URL parameter or logged in user
    member_id = frappe.form_dict.get("id")

    if not member_id and frappe.session.user != "Guest":
        # Try to find member by email
        member_id = frappe.db.get_value("Member", {"email": frappe.session.user})

    if member_id:
        member = frappe.get_doc("Member", member_id)
        context.member = member
        context.member_chapters = get_member_chapters(member_id)
    else:
        context.member = None
        context.member_chapters = []

    return context


def get_member_chapters(member_name):
    """Get list of chapters a member belongs to"""
    try:
        chapters = frappe.get_all(
            "Chapter Member",
            filters={"member": member_name, "enabled": 1},
            fields=["parent"],
            order_by="chapter_join_date desc",
        )
        return [ch.parent for ch in chapters]
    except Exception:
        return []
