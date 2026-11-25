"""
Chapter Join Page Context Handler
"""

import frappe
from frappe import _

from verenigingen.templates.pages.chapter_join import handle_join_chapter_request as file_join_request
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


def handle_join_chapter_request(context, chapter, member):
    """Same as /chapter_join, plus this form's required website, kept with the introduction.

    The Chapter Join Request has no website column, so the website travels in the introduction
    the board reads (it used to be a Comment on the chapter).
    """
    website_url = (frappe.form_dict.get("website_url") or "").strip()
    introduction = (frappe.form_dict.get("introduction") or "").strip()

    if member and not website_url:
        context.join_error = _("Website URL is required")
        frappe.msgprint(_("Error joining chapter: {0}").format(context.join_error), indicator="red")
        return
    if member and introduction:
        introduction = _("{0}\n\nWebsite: {1}").format(introduction, website_url)

    file_join_request(context, chapter, member, introduction)
