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
        website_url = frappe.form_dict.get("website_url", "").strip()
        introduction = frappe.form_dict.get("introduction", "").strip()

        # Validate required fields
        if not website_url:
            frappe.throw(_("Website URL is required"))
        if not introduction:
            frappe.throw(_("Introduction is required"))

        # Guard against duplicate chapter membership before mutating the doc.
        if frappe.db.exists("Chapter Member", {"member": member, "parent": chapter.name}):
            frappe.throw(_("You are already a member of this chapter"))

        # Add member to chapter.
        chapter_doc = frappe.get_doc("Chapter", chapter.name)

        try:
            # SELF-SERVICE PORTAL FLOW: the caller is a plain Verenigingen Member.
            # member_manager.add_member() routes through
            # secure_document_operation(required_permissions=["Chapter:write"]),
            # which raises "You do not have permission to request elevated system
            # operations" for any user outside ESCALATION_ALLOWED_ROLES — i.e. every
            # real portal user — making this page unusable. Mirror the public
            # donation flow (donate.py) and the /chapter_join page: append the row
            # and persist under the configured system user via secure_user_context().
            # `member` is the caller's own session-derived record and the duplicate
            # guard above already ran, so ownership is established.
            # NOTE: the Chapter Member child table only has member/chapter_join_date/
            # enabled/status/leave_reason — it has no introduction/website_url columns,
            # so those form fields are recorded as a comment for the board to review.
            # Mirror ChapterMemberManager.add_member: a non-Active member
            # (Terminated / Deceased / Suspended) joins disabled/Inactive so a
            # terminated member with a login cannot self-re-enable here.
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

            system_user = get_system_user_for_operation("chapter_join_portal")
            with secure_user_context(
                system_user,
                f"Add member {member} to chapter {chapter_doc.name} via join-chapter portal",
            ):
                chapter_doc.save()
                # Preserve the applicant's introduction / website for board review;
                # the child table has no columns for these.
                chapter_doc.add_comment(
                    "Comment",
                    _("Join request from {0}: {1} (website: {2})").format(member, introduction, website_url),
                )
                frappe.db.commit()

            # Set success context
            context.join_success = True
            frappe.msgprint(_("Successfully joined chapter {0}!").format(chapter.name), indicator="green")

        except Exception as e:
            frappe.log_error(f"Error adding member {member} to chapter {chapter.name}: {str(e)}")
            frappe.throw(_("Error joining chapter. Please try again or contact support."))

    except Exception as e:
        frappe.log_error(f"Error in chapter join request: {str(e)}")
        context.join_error = str(e)
        frappe.msgprint(_("Error joining chapter: {0}").format(str(e)), indicator="red")
