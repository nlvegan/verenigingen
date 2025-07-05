"""
Chapter Join API
"""

import frappe
from frappe import _


@frappe.whitelist()
def get_chapter_join_context(chapter_name):
    """Get context for chapter join page"""
    try:
        # Get chapter document
        chapter = frappe.get_doc("Chapter", chapter_name)

        # Check if user is logged in
        if frappe.session.user == "Guest":
            return {
                "success": True,
                "chapter": {
                    "name": chapter.name,
                    "route": chapter.route,
                    "title": chapter.chapter_name or chapter.name,
                },
                "already_member": False,
                "user_logged_in": False,
            }

        # Check if user is already a member of this chapter
        member = frappe.db.get_value("Member", {"email": frappe.session.user})
        already_member = False

        if member:
            # Check if member is already in this chapter
            chapter_membership = frappe.db.exists(
                "Chapter Member", {"member": member, "parent": chapter_name}
            )

            if chapter_membership:
                already_member = True

        return {
            "success": True,
            "chapter": {"name": chapter.name, "route": chapter.route, "title": chapter.name},
            "already_member": already_member,
            "user_logged_in": True,
            "member": member,
        }

    except frappe.DoesNotExistError:
        return {"success": False, "error": _("Chapter {0} not found").format(chapter_name)}
    except Exception as e:
        frappe.log_error(f"Error getting chapter join context: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def join_chapter(chapter_name, introduction):
    """Handle chapter join request"""
    try:
        # Check if user is logged in
        if frappe.session.user == "Guest":
            frappe.throw(_("Please login to join a chapter"), frappe.PermissionError)

        # Get member record
        member = frappe.db.get_value("Member", {"email": frappe.session.user})
        if not member:
            frappe.throw(_("No member record found for your account"), frappe.DoesNotExistError)

        # Validate inputs
        if not introduction or not introduction.strip():
            frappe.throw(_("Introduction is required"))

        # Use centralized chapter membership manager for proper history tracking
        from verenigingen.utils.chapter_membership_manager import ChapterMembershipManager

        result = ChapterMembershipManager.join_chapter(
            member_id=member,
            chapter_name=chapter_name,
            introduction=introduction,
            user_email=frappe.session.user,
        )

        # Enhanced success message with chapter display name
        if result.get("success"):
            chapter_doc = frappe.get_doc("Chapter", chapter_name)
            result["message"] = _("Successfully joined chapter {0}!").format(chapter_doc.name)

        return result

    except Exception as e:
        frappe.log_error(f"Error in chapter join request: {str(e)}")
        return {"success": False, "error": str(e)}
