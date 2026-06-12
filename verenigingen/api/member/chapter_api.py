# Copyright (c) 2025, Verenigingen
# For license information, please see license.txt

"""
Chapter API - Member chapter membership endpoints.

Extracted from member.py module-level functions for better organization.
All functions delegate to ChapterManagementService for actual implementation.

Functions:
    - get_member_current_chapters: Get current chapters for a member
    - get_member_chapter_names: Get simple list of chapter names
    - get_member_chapter_display_html: Get HTML display of member's chapters

Error Codes:
    - CHAP_API_001: Permission denied for member chapters
    - CHAP_API_002: Error fetching member chapters
    - CHAP_API_003: Error fetching chapter names
    - CHAP_API_004: Error generating chapter display HTML
"""

import frappe

from verenigingen.utils.security.api_security_framework import (
    OperationType,
    standard_api,
)


def _log_api_error(error_code: str, message: str, member_name: str, exception: Exception = None):
    """Log API error with structured context for observability."""
    context = {
        "error_code": error_code,
        "member": member_name,
        "api": "chapter_api",
    }
    error_msg = f"[{error_code}] {message} | member={member_name}"
    if exception:
        error_msg += f" | error={str(exception)}"
    frappe.log_error(error_msg, f"Chapter API Error [{error_code}]")


@frappe.whitelist()
@standard_api(operation_type=OperationType.MEMBER_DATA)
def get_member_current_chapters(member_name: str, structured_response=False):
    """
    Get current chapters for a member - safe for client calls.

    Delegates to ChapterManagementService for optimized query execution.
    This function maintains backward compatibility for API endpoints.

    Args:
        member_name: The member's document name
        structured_response: If True, return {"success": bool, "data": [], "error": str}

    Returns:
        List of chapter data, or structured response if requested
    """
    if not member_name:
        if structured_response:
            return {"success": True, "data": [], "message": "No member specified"}
        return []

    try:
        from verenigingen.services.member.chapter.chapter_management_service import (
            get_chapter_management_service,
        )

        # Use optimized service method
        data = get_chapter_management_service().get_member_chapters_optimized(member_name)
        if structured_response:
            return {"success": True, "data": data}
        return data

    except frappe.PermissionError:
        _log_api_error("CHAP_API_001", "Permission denied", member_name)
        if structured_response:
            return {
                "success": False,
                "error": "Permission denied",
                "error_code": "CHAP_API_001",
                "fallback": [],
            }
        return []
    except Exception as e:
        _log_api_error("CHAP_API_002", "Error fetching chapters", member_name, e)
        if structured_response:
            # Don't expose raw exception to client - log full details server-side
            return {
                "success": False,
                "error": "An error occurred fetching chapters",
                "error_code": "CHAP_API_002",
                "fallback": [],
            }
        return []


@frappe.whitelist()
@standard_api(operation_type=OperationType.MEMBER_DATA)
def get_member_chapter_names(member_name: str, structured_response=False):
    """
    Get simple list of chapter names for a member.

    Delegates to ChapterManagementService for optimized query execution.

    Args:
        member_name: The member's document name
        structured_response: If True, return {"success": bool, "data": [], "error": str}
    """
    if not member_name:
        if structured_response:
            return {"success": True, "data": [], "message": "No member specified"}
        return []

    try:
        from verenigingen.services.member.chapter.chapter_management_service import (
            get_chapter_management_service,
        )

        data = get_chapter_management_service().get_chapter_names(member_name)
        if structured_response:
            return {"success": True, "data": data}
        return data
    except Exception as e:
        _log_api_error("CHAP_API_003", "Error fetching chapter names", member_name, e)
        if structured_response:
            return {
                "success": False,
                "error": "An error occurred fetching chapter names",
                "error_code": "CHAP_API_003",
                "fallback": [],
            }
        return []


@frappe.whitelist()
@standard_api(operation_type=OperationType.MEMBER_DATA)
def get_member_chapter_display_html(member_name: str, structured_response=False):
    """
    Get HTML display of member's chapters.

    Delegates to ChapterManagementService for optimized query execution.

    Args:
        member_name: The member's document name
        structured_response: If True, return {"success": bool, "data": str, "error": str}
    """
    empty_html = "<div class='text-muted'>No member specified</div>"

    if not member_name:
        if structured_response:
            return {"success": True, "data": empty_html, "message": "No member specified"}
        return empty_html

    try:
        from verenigingen.services.member.chapter.chapter_management_service import (
            get_chapter_management_service,
        )

        html = get_chapter_management_service().get_chapter_display_html(member_name)
        if structured_response:
            return {"success": True, "data": html}
        return html

    except Exception as e:
        _log_api_error("CHAP_API_004", "Error generating chapter display HTML", member_name, e)
        error_html = f"<div class='text-danger'>Error loading chapters</div>"
        if structured_response:
            return {
                "success": False,
                "error": "An error occurred generating chapter display",
                "error_code": "CHAP_API_004",
                "fallback": error_html,
            }
        return error_html
