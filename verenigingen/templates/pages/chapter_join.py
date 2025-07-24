"""
Chapter Join Page Context Handler
"""

import frappe
from frappe import _


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
    member = frappe.db.get_value("Member", {"email": frappe.session.user})
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

        # Add to members child table
        chapter_doc.append(
            "members", {"member": member, "chapter_join_date": frappe.utils.today(), "enabled": 1}
        )

        chapter_doc.save(ignore_permissions=True)
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
