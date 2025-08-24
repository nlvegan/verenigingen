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
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)


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
                    "title": chapter.name,
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


@frappe.whitelist(allow_guest=False)
@standard_api(operation_type=OperationType.MEMBER_DATA)  # Chapter membership operations
def join_chapter(chapter_name, introduction):
    """Create a chapter join request.

    Creates a new Chapter Join Request document that will be reviewed and
    approved/rejected by chapter board members.

    Args:
        chapter_name (str): Name of the chapter to join
        introduction (str): Member's introduction message

    Returns:
        dict: Success status and message or error details
            - success (bool): Operation status
            - message (str): Success/error message
            - request_id (str): ID of created request (on success)
            - error (str, optional): Error description (on failure)

    Security:
        - Requires authenticated user session
        - Validates member record exists
        - Creates Chapter Join Request document
        - Uses standard Frappe permissions
    """
    try:
        # Ensure user is authenticated
        if frappe.session.user == "Guest":
            frappe.throw(_("Please login to join a chapter"), frappe.PermissionError)

        # Verify that user has a valid member record
        member = frappe.db.get_value("Member", {"email": frappe.session.user})
        if not member:
            frappe.throw(_("No member record found for your account"), frappe.DoesNotExistError)

        # Validate required introduction message
        if not introduction or not introduction.strip():
            frappe.throw(_("Introduction is required"))

        # Create Chapter Join Request document
        join_request = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": member,
                "chapter": chapter_name,
                "introduction": introduction.strip(),
                "status": "Pending",
            }
        )

        # Save and submit the request
        join_request.insert()
        join_request.submit()

        return {
            "success": True,
            "message": _(
                "Your request to join {0} has been submitted for approval. You will be notified once reviewed."
            ).format(chapter_name),
            "request_id": join_request.name,
        }

    except Exception as e:
        # Log join request errors for debugging
        frappe.log_error(f"Error creating chapter join request: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def get_user_chapter_requests():
    """Get chapter join requests for chapters where the current user is a board member"""
    user = frappe.session.user

    # Get member record for current user
    member = frappe.db.get_value("Member", {"email": user})
    if not member:
        return {"chapters": []}

    # Get chapters where user is a board member
    # First get volunteer record for the member
    volunteer_records = frappe.get_all("Volunteer", filters={"member": member}, fields=["name"])

    board_memberships = []
    if volunteer_records:
        volunteer_name = volunteer_records[0].name
        board_memberships = frappe.get_all(
            "Chapter Board Member", filters={"volunteer": volunteer_name, "enabled": 1}, fields=["parent"]
        )

    chapter_names = [bm.parent for bm in board_memberships]

    # For administrators and managers, include all chapters
    user_roles = frappe.get_roles(user)
    if "Verenigingen Administrator" in user_roles or "Verenigingen Manager" in user_roles:
        all_chapters = frappe.get_all("Chapter", fields=["name"])
        chapter_names.extend([ch.name for ch in all_chapters])
        chapter_names = list(set(chapter_names))  # Remove duplicates

    return {"chapters": chapter_names}
