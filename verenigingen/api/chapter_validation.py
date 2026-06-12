"""
Chapter Validation API

Backend validation methods for Chapter DocType operations.
These methods provide server-side validation that complements
the frontend controller handlers.
"""

import traceback
from typing import Any, Dict

import frappe
from frappe import _

from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.security.api_security_framework import OperationType, standard_api


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def validate_chapter_head(chapter_name: str, chapter_head: str) -> OperationResult[Dict[str, Any]]:
    """
    Validate chapter head assignment

    Args:
        chapter_name: Name of the chapter
        chapter_head: Member ID being assigned as chapter head

    Returns:
        OperationResult[Dict[str, Any]]: Validation result with status and messages
    """
    try:
        if not chapter_head:
            return OperationResult.ok(
                {"valid": True, "message": "No chapter head assigned"}, message=_("No chapter head assigned")
            )

        # Check if member exists and is active
        member = frappe.get_doc("Member", chapter_head)
        if member.status != "Active":
            return OperationResult.ok(
                {"valid": False, "message": _("Selected member is not active"), "warning": True},
                message=_("Selected member is not active"),
            )

        # Check if member is a volunteer (required for chapter head)
        volunteer = frappe.db.get_value("Volunteer", {"member": chapter_head}, "name")
        if not volunteer:
            return OperationResult.ok(
                {
                    "valid": False,
                    "message": _("Chapter head must be a registered volunteer"),
                    "error": True,
                },
                message=_("Chapter head must be a registered volunteer"),
            )

        return OperationResult.ok(
            {"valid": True, "message": _("Chapter head assignment is valid"), "volunteer": volunteer},
            message=_("Chapter head assignment is valid"),
        )

    except Exception as e:
        frappe.log_error(
            f"Chapter head validation error: {str(e)}\n{traceback.format_exc()}",
            "Chapter Head Validation Error",
        )
        return OperationResult.fail(
            _("Error validating chapter head assignment"),
            errors=[str(e)],
            context={"operation": "validate_chapter_head", "chapter_name": chapter_name},
        )


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def validate_region(chapter_name: str, region) -> OperationResult[Dict[str, Any]]:
    """
    Validate region assignment and suggest postal codes

    Args:
        chapter_name: Name of the chapter
        region: Region being assigned

    Returns:
        OperationResult[Dict[str, Any]]: Validation result with suggestions
    """
    try:
        if not region:
            return OperationResult.ok(
                {"valid": True, "message": "No region assigned"}, message=_("No region assigned")
            )

        # Get other chapters in the same region for postal code suggestions
        other_chapters = frappe.get_all(
            "Chapter",
            filters={"region": region, "name": ["!=", chapter_name], "postal_codes": ["is", "set"]},
            fields=["name", "postal_codes"],
            limit=5,
        )

        suggestions = []
        if other_chapters:
            for chapter in other_chapters:
                if chapter.postal_codes:
                    suggestions.append({"chapter": chapter.name, "postal_codes": chapter.postal_codes})

        return OperationResult.ok(
            {
                "valid": True,
                "message": _("Region assignment is valid"),
                "suggestions": suggestions,
                "region": region,
            },
            message=_("Region assignment is valid"),
        )

    except Exception as e:
        frappe.log_error(
            f"Region validation error: {str(e)}\n{traceback.format_exc()}", "Region Validation Error"
        )
        return OperationResult.fail(
            _("Error validating region assignment"),
            errors=[str(e)],
            context={"operation": "validate_region", "chapter_name": chapter_name},
        )


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def update_publication_status(chapter_name: str, published) -> OperationResult[Dict[str, Any]]:
    """
    Update chapter publication status with validation

    Args:
        chapter_name: Name of the chapter
        published: Publication status (0 or 1)

    Returns:
        OperationResult[Dict[str, Any]]: Update result with status
    """
    try:
        chapter = frappe.get_doc("Chapter", chapter_name)

        # Validate chapter can be published
        if published and not chapter.postal_codes:
            return OperationResult.ok(
                {
                    "valid": False,
                    "message": _("Chapter must have postal codes defined before publishing"),
                    "warning": True,
                },
                message=_("Chapter must have postal codes defined before publishing"),
            )

        if published and not chapter.introduction:
            return OperationResult.ok(
                {
                    "valid": False,
                    "message": _("Chapter should have an introduction before publishing"),
                    "warning": True,
                },
                message=_("Chapter should have an introduction before publishing"),
            )

        # SECURITY: Verify user has write permission on chapter before updating
        chapter.check_permission("write")

        # Update publication status
        chapter.published = int(published)
        chapter.save()  # Removed ignore_permissions - permission checked above

        status_text = _("published") if published else _("unpublished")

        return OperationResult.ok(
            {
                "valid": True,
                "message": _("Chapter has been {0}").format(status_text),
                "published": bool(published),
                "chapter": chapter_name,
            },
            message=_("Chapter has been {0}").format(status_text),
        )

    except Exception as e:
        frappe.log_error(
            f"Publication status update error: {str(e)}\n{traceback.format_exc()}",
            "Publication Status Update Error",
        )
        return OperationResult.fail(
            _("Error updating publication status"),
            errors=[str(e)],
            context={"operation": "update_publication_status", "chapter_name": chapter_name},
        )


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def validate_board_member(chapter_name: str, volunteer, role) -> OperationResult[Dict[str, Any]]:
    """
    Validate board member assignment

    Args:
        chapter_name: Name of the chapter
        volunteer: Volunteer ID being assigned
        role: Chapter role being assigned

    Returns:
        OperationResult[Dict[str, Any]]: Validation result
    """
    try:
        if not volunteer:
            return OperationResult.ok(
                {"valid": True, "message": "No volunteer specified"}, message=_("No volunteer specified")
            )

        # Check if volunteer exists and is active
        volunteer_doc = frappe.get_doc("Volunteer", volunteer)
        if volunteer_doc.status != "Active":
            return OperationResult.ok(
                {"valid": False, "message": _("Selected volunteer is not active"), "warning": True},
                message=_("Selected volunteer is not active"),
            )

        # Check if volunteer is already on the board
        existing = frappe.db.exists(
            "Chapter Board Member", {"parent": chapter_name, "volunteer": volunteer, "status": "Active"}
        )

        if existing:
            return OperationResult.ok(
                {
                    "valid": False,
                    "message": _("Volunteer is already on the chapter board"),
                    "warning": True,
                },
                message=_("Volunteer is already on the chapter board"),
            )

        return OperationResult.ok(
            {
                "valid": True,
                "message": _("Board member assignment is valid"),
                "volunteer": volunteer,
                "role": role,
            },
            message=_("Board member assignment is valid"),
        )

    except Exception as e:
        frappe.log_error(
            f"Board member validation error: {str(e)}\n{traceback.format_exc()}",
            "Board Member Validation Error",
        )
        return OperationResult.fail(
            _("Error validating board member assignment"),
            errors=[str(e)],
            context={"operation": "validate_board_member", "chapter_name": chapter_name},
        )


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def validate_board_removal(chapter_name: str) -> OperationResult[Dict[str, Any]]:
    """
    Validate board member removal

    Args:
        chapter_name: Name of the chapter

    Returns:
        OperationResult[Dict[str, Any]]: Validation result
    """
    try:
        # Get current board size
        board_count = frappe.db.count("Chapter Board Member", {"parent": chapter_name, "status": "Active"})

        if board_count <= 1:
            return OperationResult.ok(
                {
                    "valid": False,
                    "message": _("Chapter must have at least one board member"),
                    "warning": True,
                },
                message=_("Chapter must have at least one board member"),
            )

        return OperationResult.ok(
            {
                "valid": True,
                "message": _("Board member removal is valid"),
                "current_board_size": board_count,
            },
            message=_("Board member removal is valid"),
        )

    except Exception as e:
        frappe.log_error(
            f"Board removal validation error: {str(e)}\n{traceback.format_exc()}",
            "Board Removal Validation Error",
        )
        return OperationResult.fail(
            _("Error validating board member removal"),
            errors=[str(e)],
            context={"operation": "validate_board_removal", "chapter_name": chapter_name},
        )
