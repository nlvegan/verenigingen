# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
ChapterQueryService - Optimized query operations for Chapter

This service handles optimized database queries for Chapter records, including
permission queries and efficient data retrieval operations.

Extracted from chapter.py:
- get_user_permissions_optimized() - Lines 485-534 (50 LOC)

Architecture:
- Static methods for stateless operations
- Chapter document passed as parameter
- Optimized SQL queries for performance
- Parameterized queries for SQL injection safety

Security:
- SQL injection safe with parameterized queries
- Permission checks using frappe.has_permission()
- Role-based access control

Dependencies:
- frappe.session for user context
- frappe.get_roles() for role checking
- frappe.db.sql() for optimized queries
"""

from typing import TYPE_CHECKING, Any, Dict, Optional

import frappe

if TYPE_CHECKING:
    from frappe.model.document import Document


class ChapterQueryService:
    """
    Service for optimized Chapter query operations.

    This service handles:
    - User permission queries with role-based access
    - Optimized SQL queries for board membership checks
    - Permission calculation for chapter access
    """

    @staticmethod
    def get_user_permissions_optimized(chapter_doc: "Document") -> Dict[str, Any]:
        """
        Get all user permissions for this chapter using single optimized query.

        Performance Optimization:
            - Single SQL query instead of multiple ORM calls
            - Early return for System Manager/Admin roles
            - Parameterized query for SQL injection safety

        Args:
            chapter_doc: Chapter document instance

        Returns:
            Dict containing:
                - is_board_member (bool): Whether user is board member
                - board_role (str|None): Board role name if board member
                - is_system_manager (bool): Whether user has System Manager role
                - can_write_chapter (bool): Whether user can edit chapter
                - can_view_members (bool): Whether user can view member list

        Permission Logic:
            - System Manager: Full access to all permissions
            - Verenigingen Administrator: Full access to all permissions
            - Board Member: Limited access based on board membership
            - Other users: Minimal access based on standard permissions

        Example:
            >>> perms = ChapterQueryService.get_user_permissions_optimized(chapter_doc)
            >>> if perms['can_write_chapter']:
            ...     # User can edit this chapter
        """
        try:
            user = frappe.session.user
            user_roles = frappe.get_roles(user)

            is_system_manager = "System Manager" in user_roles
            is_verenigingen_manager = "Verenigingen Administrator" in user_roles

            # System Managers and Verenigingen Administrators have full access
            if is_system_manager or is_verenigingen_manager:
                return {
                    "is_board_member": True,
                    "board_role": "Admin",
                    "is_system_manager": is_system_manager,
                    "can_write_chapter": True,
                    "can_view_members": True,
                }

            # Single optimized query to check board membership and get role
            # Uses parameterized query for SQL injection safety
            board_query = """
                SELECT cbm.chapter_role, cbm.is_active
                FROM `tabChapter Board Member` cbm
                JOIN `tabVolunteer` v ON cbm.volunteer = v.name
                JOIN `tabMember` m ON v.member = m.name
                WHERE m.user = %s AND cbm.parent = %s AND cbm.is_active = 1
                LIMIT 1
            """

            board_result = frappe.db.sql(board_query, (user, chapter_doc.name), as_dict=True)

            is_board_member = bool(board_result)
            board_role = board_result[0].chapter_role if board_result else None

            return {
                "is_board_member": is_board_member,
                "board_role": board_role,
                "is_system_manager": is_system_manager,
                "can_write_chapter": frappe.has_permission("Chapter", doc=chapter_doc.name, ptype="write"),
                "can_view_members": is_board_member or is_system_manager or is_verenigingen_manager,
            }

        except Exception as e:
            frappe.log_error(f"Error getting user permissions for chapter {chapter_doc.name}: {str(e)}")
            # Return safe defaults on error
            return {
                "is_board_member": False,
                "board_role": None,
                "is_system_manager": False,
                "can_write_chapter": False,
                "can_view_members": False,
            }


def get_chapter_query_service() -> ChapterQueryService:
    """Get singleton instance of ChapterQueryService"""
    return ChapterQueryService()
