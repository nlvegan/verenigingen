"""
Chapter Join Page Context Handler
"""

import frappe
from frappe import _

from verenigingen.utils.member_utils import get_current_user_member_name
from verenigingen.utils.secure_operations import (
    get_system_user_for_operation,
    secure_user_context,
)


def get_context(context):
    """Get context for chapter join page"""

    # Get chapter name from URL parameters with explicit fallback
    chapter_name = frappe.form_dict.get("chapter")
    if not chapter_name:
        chapter_name = frappe.form_dict.get("name")

    if not chapter_name:
        frappe.throw(_("Chapter not specified"), frappe.DoesNotExistError)

    # Get chapter document
    try:
        chapter = frappe.get_doc("Chapter", chapter_name)
        context.chapter = chapter
    except frappe.DoesNotExistError:
        frappe.throw(_("Chapter {0} not found").format(chapter_name), frappe.DoesNotExistError)

    # Check if user is logged in
    if frappe.session.user == "Guest":
        context.title = _("Join Chapter - {0}").format(chapter.name)
        return context

    # Check if user is already a member of this chapter
    member = get_current_user_member_name()
    context.already_member = False

    if member:
        # Check if member is already in this chapter
        chapter_membership = frappe.db.exists("Chapter Member", {"member": member, "parent": chapter_name})

        if chapter_membership:
            context.already_member = True

    # Handle POST request (joining chapter)
    if frappe.request.method == "POST":
        handle_join_chapter_request(context, chapter, member)

    context.title = _("Join Chapter - {0}").format(chapter.name)
    context.no_cache = 1

    return context


def handle_join_chapter_request(context, chapter, member):
    """Handle the chapter join request"""
    try:
        if not member:
            frappe.throw(_("No member record found for your account"), frappe.DoesNotExistError)

        # Get form data
        introduction = frappe.form_dict.get("introduction", "").strip()

        # Validate required fields
        if not introduction:
            frappe.throw(_("Introduction is required"))

        # Check if already a member
        existing_membership = frappe.db.exists("Chapter Member", {"member": member, "parent": chapter.name})

        if existing_membership:
            frappe.throw(_("You are already a member of this chapter"))

        # Add member to chapter by creating Chapter Member record directly
        chapter_doc = frappe.get_doc("Chapter", chapter.name)

        # Add to members child table. Mirror ChapterMemberManager.add_member: a
        # member who is not Active (Terminated / Deceased / Suspended) joins
        # disabled/Inactive, so a terminated member who still has a login cannot
        # self-re-enable through this portal.
        is_active_member = frappe.db.get_value("Member", member, "status") == "Active"
        chapter_doc.append(
            "members",
            {
                "member": member,
                "chapter_join_date": frappe.utils.today(),
                "enabled": 1 if is_active_member else 0,
                "status": "Active" if is_active_member else "Inactive",
            },
        )

        # SELF-SERVICE PORTAL FLOW: the caller is a plain Verenigingen Member who
        # does not hold "Chapter:write" and is not in ESCALATION_ALLOWED_ROLES, so
        # secure_document_operation(required_permissions=["Chapter:write"]) used to
        # raise "You do not have permission to request elevated system operations"
        # for EVERY portal user — making this page unusable. Mirror the public
        # donation flow (donate.py): perform the privileged save under the
        # configured system user via secure_user_context(). Ownership is already
        # established above — `member` is the caller's own session-derived record
        # and a duplicate-membership guard ran just before this.
        system_user = get_system_user_for_operation("chapter_join_portal")
        with secure_user_context(
            system_user, f"Add member {member} to chapter {chapter_doc.name} via chapter join portal"
        ):
            chapter_doc.save()
            frappe.db.commit()

        # Set success context
        context.join_success = True
        frappe.msgprint(_("Successfully joined chapter {0}!").format(chapter.name), indicator="green")

    except Exception as e:
        frappe.log_error(f"Error in chapter join request: {str(e)}")
        context.join_error = str(e)
        frappe.msgprint(_("Error joining chapter: {0}").format(str(e)), indicator="red")


def has_website_permission(doc, ptype, user, verbose=False):
    """Check website permission for chapter join page"""
    # Allow all logged-in users to access chapter join pages
    return user != "Guest"
