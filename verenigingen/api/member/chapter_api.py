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
"""

import frappe

from verenigingen.utils.security.api_security_framework import (
    OperationType,
    standard_api,
)


@frappe.whitelist()
@standard_api(operation_type=OperationType.MEMBER_DATA)
def get_member_current_chapters(member_name):
    """
    Get current chapters for a member - safe for client calls.

    Delegates to ChapterManagementService for optimized query execution.
    This function maintains backward compatibility for API endpoints.
    """
    if not member_name:
        return []

    try:
        from verenigingen.services.member.chapter.chapter_management_service import (
            get_chapter_management_service,
        )

        # Use optimized service method
        return get_chapter_management_service().get_member_chapters_optimized(member_name)

    except frappe.PermissionError:
        # If no permission to member, return empty list (API compatibility)
        return []
    except Exception as e:
        frappe.log_error(f"Error getting member chapters: {str(e)}", "Member Chapters API")
        return []


@frappe.whitelist()
@standard_api(operation_type=OperationType.MEMBER_DATA)
def get_member_chapter_names(member_name):
    """
    Get simple list of chapter names for a member.

    Delegates to ChapterManagementService for optimized query execution.
    """
    if not member_name:
        return []

    try:
        from verenigingen.services.member.chapter.chapter_management_service import (
            get_chapter_management_service,
        )

        return get_chapter_management_service().get_chapter_names(member_name)
    except Exception as e:
        frappe.log_error(f"Error getting member chapter names: {str(e)}", "Member Chapter Names API")
        return []


@frappe.whitelist()
@standard_api(operation_type=OperationType.MEMBER_DATA)
def get_member_chapter_display_html(member_name):
    """
    Get HTML display of member's chapters.

    Delegates to ChapterManagementService for optimized query execution.
    """
    if not member_name:
        return "<div class='text-muted'>No member specified</div>"

    try:
        from verenigingen.services.member.chapter.chapter_management_service import (
            get_chapter_management_service,
        )

        return get_chapter_management_service().get_chapter_display_html(member_name)

    except Exception as e:
        frappe.log_error(f"Error generating chapter display HTML: {str(e)}", "Member Chapter Display")
        return f"<div class='text-danger'>Error loading chapters: {str(e)}</div>"
