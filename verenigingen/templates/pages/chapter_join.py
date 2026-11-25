"""
Chapter Join Page Context Handler
"""

import frappe
from frappe import _

from verenigingen.utils.member_utils import get_current_user_linked_member_name


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
    # Member.user link only, no email fallback (#1853)
    member = get_current_user_linked_member_name()
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


def handle_join_chapter_request(context, chapter, member, introduction=None):
    """File a Pending Chapter Join Request for the session member (#3273).

    The portal never adds the Chapter Member row itself: it calls the same whitelisted
    `api.chapter_join.join_chapter` the chapter page button uses, so the board's approval and
    every refusal rule (non-Active member, inactive chapter, existing pending request, already a
    member) live in one place. `join_chapter` runs as the caller, so no elevation is needed.
    `introduction` defaults to the form value; join-chapter passes its own (with the website).
    """
    try:
        if not member:
            frappe.throw(
                _("Your account is not linked to a member record, so you cannot join a chapter."),
                frappe.DoesNotExistError,
            )

        if introduction is None:
            introduction = (frappe.form_dict.get("introduction") or "").strip()
        if not introduction:
            frappe.throw(_("Introduction is required"))

        from verenigingen.api.chapter_join import join_chapter

        result = join_chapter(chapter.name, introduction)
        if not result.get("success"):
            frappe.throw((result.get("error") or {}).get("message") or _("Unable to join chapter"))

        context.join_success = True
        frappe.msgprint((result.get("data") or {}).get("message"), indicator="green")

    except Exception as e:
        frappe.log_error(f"Error in chapter join request: {str(e)}")
        context.join_error = str(e)
        frappe.msgprint(_("Error joining chapter: {0}").format(str(e)), indicator="red")
