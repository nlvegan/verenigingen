"""
Chapter Join API.

This module provides API endpoints for handling chapter membership requests
and providing context for chapter join pages.

Key Features:
    - Chapter membership status checking
    - Guest and authenticated user support
    - Chapter join request processing
    - Integration with ChapterMembershipManager for proper tracking
    - Security validation and authentication

Security:
    - Standard API security for context retrieval
    - High security API for membership operations
    - Authentication requirement for join operations
    - Member record validation

Author: Verenigingen Development Team
Last Updated: 2025-08-02
"""

import frappe
from frappe import _

# Import security decorators
from verenigingen.utils.security.api_security_framework import critical_api, high_security_api, standard_api


@frappe.whitelist()
@standard_api  # Chapter join context - read-only
def get_chapter_join_context(chapter_name):
    """Get context for chapter join page.

    Retrieves information needed for the chapter join page, including
    chapter details and user membership status.

    Args:
        chapter_name (str): Name/ID of the chapter

    Returns:
        dict: Context information with structure:
            - success (bool): Operation status
            - chapter (dict): Chapter information (name, route, title)
            - already_member (bool): Whether user is already a member
            - user_logged_in (bool): Whether user is authenticated
            - member (str, optional): Member ID (for authenticated users)
            - error (str, optional): Error message (on failure)

    Business Logic:
        - Supports both guest and authenticated access
        - Checks existing chapter membership for authenticated users
        - Returns appropriate context based on authentication status
        - Handles non-existent chapters gracefully

    Examples:
        >>> # Guest user response
        {
            "success": True,
            "chapter": {"name": "amsterdam", "route": "/chapter/amsterdam", "title": "Amsterdam"},
            "already_member": False,
            "user_logged_in": False
        }

        >>> # Authenticated user, not a member
        {
            "success": True,
            "chapter": {"name": "amsterdam", "route": "/chapter/amsterdam", "title": "Amsterdam"},
            "already_member": False,
            "user_logged_in": True,
            "member": "MEM-2025-001"
        }
    """
    try:
        # Get chapter document
        chapter = frappe.get_doc("Chapter", chapter_name)

        # Handle guest users - provide public chapter information only
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

        # For authenticated users, check existing chapter membership
        member = frappe.db.get_value("Member", {"email": frappe.session.user})
        already_member = False

        if member:
            # Check if member is already in this chapter to prevent duplicate requests
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
        # Handle non-existent chapters gracefully
        return {"success": False, "error": _("Chapter {0} not found").format(chapter_name)}
    except Exception as e:
        # Log unexpected errors while returning user-friendly message
        frappe.log_error(f"Error getting chapter join context: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@high_security_api  # Chapter membership operations
def join_chapter(chapter_name, introduction):
    """Handle chapter join request.

    Processes a member's request to join a specific chapter, including
    validation, permission checking, and proper history tracking.

    Args:
        chapter_name (str): Name/ID of the chapter to join
        introduction (str): Member's introduction message (required)

    Returns:
        dict: Join request result with structure:
            - success (bool): Operation status
            - message (str): Success message with chapter name
            - error (str, optional): Error description (on failure)

    Security Requirements:
        - User must be authenticated (not Guest)
        - Valid Member record must exist for user's email
        - Introduction message is required and non-empty

    Business Logic:
        - Uses ChapterMembershipManager for proper workflow handling
        - Tracks membership history and audit trail
        - Prevents duplicate membership requests
        - Handles chapter approval workflows

    Side Effects:
        - Creates Chapter Member record with appropriate status
        - Logs membership request for audit purposes
        - May trigger notification workflows

    Raises:
        frappe.PermissionError: For guest users
        frappe.DoesNotExistError: For users without member records
        frappe.ValidationError: For missing/invalid introduction

    Examples:
        >>> # Successful join request
        {
            "success": True,
            "message": "Successfully joined chapter Amsterdam!"
        }

        >>> # Authentication error
        {
            "success": False,
            "error": "Please login to join a chapter"
        }
    """
    try:
        # Ensure user is authenticated before allowing join operations
        if frappe.session.user == "Guest":
            frappe.throw(_("Please login to join a chapter"), frappe.PermissionError)

        # Verify that user has a valid member record
        member = frappe.db.get_value("Member", {"email": frappe.session.user})
        if not member:
            frappe.throw(_("No member record found for your account"), frappe.DoesNotExistError)

        # Validate required introduction message
        if not introduction or not introduction.strip():
            frappe.throw(_("Introduction is required"))

        # Use centralized chapter membership manager for proper history tracking
        # This ensures consistent workflow handling and audit trail creation
        from verenigingen.utils.chapter_membership_manager import ChapterMembershipManager

        result = ChapterMembershipManager.join_chapter(
            member_id=member,
            chapter_name=chapter_name,
            introduction=introduction,
            user_email=frappe.session.user,
        )

        # Enhance success message with proper chapter display name
        if result.get("success"):
            chapter_doc = frappe.get_doc("Chapter", chapter_name)
            result["message"] = _("Successfully joined chapter {0}!").format(chapter_doc.name)

        return result

    except Exception as e:
        # Log join request errors for debugging
        frappe.log_error(f"Error in chapter join request: {str(e)}")
        return {"success": False, "error": str(e)}
