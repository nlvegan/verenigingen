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

import traceback
from typing import Any, Dict

import frappe
from frappe import _

from verenigingen.utils.constants import Roles
from verenigingen.utils.member_utils import get_current_user_member_name
from verenigingen.utils.operation_result import OperationResult

# Import security decorators
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    self_service_api,
    standard_api,
)


@frappe.whitelist()
@self_service_api(operation_type=OperationType.MEMBER_DATA, implicit_allowed=True)
def get_chapter_join_context(chapter_name: str) -> OperationResult[Dict[str, Any]]:
    """Get context for chapter join page.

    Retrieves information needed for the chapter join page, including
    chapter details and user membership status.

    Args:
        chapter_name (str): Name/ID of the chapter

    Returns:
        OperationResult[Dict[str, Any]]: Context information with structure:
            - chapter (dict): Chapter information (name, route, title)
            - already_member (bool): Whether user is already a member
            - user_logged_in (bool): Whether user is authenticated
            - member (str, optional): Member ID (for authenticated users)

    Business Logic:
        - Supports both guest and authenticated access
        - Checks existing chapter membership for authenticated users
        - Returns appropriate context based on authentication status
        - Handles non-existent chapters gracefully

    Examples:
        >>> # Guest user response
        {
            "chapter": {"name": "amsterdam", "route": "/chapter/amsterdam", "title": "Amsterdam"},
            "already_member": False,
            "user_logged_in": False
        }

        >>> # Authenticated user, not a member
        {
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
            data = {
                "chapter": {
                    "name": chapter.name,
                    "route": chapter.route,
                    "title": chapter.name,
                },
                "already_member": False,
                "user_logged_in": False,
            }
            return OperationResult.ok(data, message=_("Chapter information retrieved"))

        # For authenticated users, check existing chapter membership
        member = get_current_user_member_name()
        already_member = False

        if member:
            # Check if member is already in this chapter to prevent duplicate requests
            chapter_membership = frappe.db.exists(
                "Chapter Member", {"member": member, "parent": chapter_name}
            )

            if chapter_membership:
                already_member = True

        data = {
            "chapter": {"name": chapter.name, "route": chapter.route, "title": chapter.name},
            "already_member": already_member,
            "user_logged_in": True,
            "member": member,
        }
        return OperationResult.ok(data, message=_("Chapter join context retrieved"))

    except frappe.DoesNotExistError as e:
        # Handle non-existent chapters gracefully
        frappe.log_error(
            f"Chapter not found: {chapter_name}\n{traceback.format_exc()}",
            "Chapter Join Context - Chapter Not Found",
        )
        return OperationResult.fail(
            _("Chapter {0} not found").format(chapter_name),
            errors=[str(e)],
            context={"operation": "get_chapter_join_context", "chapter_name": chapter_name},
        )
    except Exception as e:
        # Log unexpected errors while returning user-friendly message
        frappe.log_error(
            f"Error getting chapter join context: {str(e)}\n{traceback.format_exc()}",
            "Chapter Join Context Error",
        )
        return OperationResult.fail(
            _("Unable to retrieve chapter information. Please try again later."),
            errors=[str(e)],
            context={"operation": "get_chapter_join_context", "chapter_name": chapter_name},
        )


@frappe.whitelist(allow_guest=False)
@self_service_api(operation_type=OperationType.MEMBER_DATA, implicit_allowed=True)
def join_chapter(chapter_name: str, introduction) -> OperationResult[Dict[str, Any]]:
    """Create a chapter join request.

    Creates a new Chapter Join Request document that will be reviewed and
    approved/rejected by chapter board members.

    Args:
        chapter_name (str): Name of the chapter to join
        introduction (str): Member's introduction message

    Returns:
        OperationResult[Dict[str, Any]]: Success status with data:
            - message (str): Success message
            - request_id (str): ID of created request

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
        member = get_current_user_member_name()
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

        # Save and submit the request.
        # reload() guards against #609 (whole-second creation/modified timestamp
        # -> TimestampMismatchError / CannotChangeConstantError on submit()):
        # frappe#38219 precedent. Belt-and-braces alongside the doc_events["*"]
        # after_insert normaliser (verenigingen/utils/timestamp_normalization.py)
        # -- that already fixes the in-memory string, so this reload() re-reads
        # the same, already-consistent row and is a deliberate no-op most of
        # the time, kept here as a second, independent guard on a money-moving
        # path per #609's scope decision.
        join_request.insert()
        join_request.reload()
        join_request.submit()

        data = {
            "message": _(
                "Your request to join {0} has been submitted for approval. You will be notified once reviewed."
            ).format(chapter_name),
            "request_id": join_request.name,
        }
        return OperationResult.ok(data, message=_("Chapter join request submitted successfully"))

    except Exception as e:
        # Log join request errors for debugging
        frappe.log_error(
            f"Error creating chapter join request: {str(e)}\n{traceback.format_exc()}",
            "Chapter Join Request Error",
        )
        return OperationResult.fail(
            _("Unable to submit chapter join request. Please try again later."),
            errors=[str(e)],
            context={
                "operation": "join_chapter",
                "chapter_name": chapter_name,
                "member": frappe.session.user,
            },
        )


@frappe.whitelist()
@standard_api(operation_type=OperationType.MEMBER_DATA)
def get_user_chapter_requests() -> OperationResult[Dict[str, Any]]:
    """Get chapter join requests for chapters where the current user is a board member.

    Retrieves a list of chapters where the current user has permissions to
    view and manage chapter join requests. This includes:
    - Chapters where the user is an active board member
    - All chapters if the user is an administrator or staff member

    Returns:
        OperationResult[Dict[str, Any]]: Result with data:
            - chapters (list): List of chapter names
    """
    try:
        user = frappe.session.user

        # Get member record for current user
        member = get_current_user_member_name()
        if not member:
            data = {"chapters": []}
            return OperationResult.ok(data, message=_("No member record found"))

        # Get chapters where user is a board member
        # First get volunteer record for the member
        volunteer_records = frappe.get_all("Volunteer", filters={"member": member}, fields=["name"])

        board_memberships = []
        if volunteer_records:
            volunteer_name = volunteer_records[0].name
            board_memberships = frappe.get_all(
                "Chapter Board Member",
                filters={"volunteer": volunteer_name, "is_active": 1},
                fields=["parent"],
            )

        chapter_names = [bm.parent for bm in board_memberships]

        # For administrators and managers, include all chapters
        user_roles = frappe.get_roles(user)
        if Roles.VERENIGINGEN_ADMIN in user_roles or Roles.VERENIGINGEN_STAFF in user_roles:
            all_chapters = frappe.get_all("Chapter", fields=["name"])
            chapter_names.extend([ch.name for ch in all_chapters])
            chapter_names = list(set(chapter_names))  # Remove duplicates

        data = {"chapters": chapter_names}
        return OperationResult.ok(data, message=_("Chapter requests retrieved successfully"))

    except Exception as e:
        frappe.log_error(
            f"Error getting user chapter requests: {str(e)}\n{traceback.format_exc()}",
            "Get User Chapter Requests Error",
        )
        return OperationResult.fail(
            _("Unable to retrieve chapter requests. Please try again later."),
            errors=[str(e)],
            context={"operation": "get_user_chapter_requests", "user": frappe.session.user},
        )
