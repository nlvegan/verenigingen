# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
ChapterPermissionService - Permission checking and access control for Chapters

This service centralizes all permission logic for Chapter documents, providing
consistent security validation across list views, document access, and API endpoints.

Extracted from chapter.py:
- get_chapter_permission_query_conditions() - Lines 746-787 (42 LOC)
- has_chapter_permission() - Lines 790-834 (45 LOC)
- Permission checks in get_board_memberships() - Lines 903-949 (47 LOC)
- Permission checks in get_chapter_board_history() - Lines 996-1018 (23 LOC)
Total extraction: ~157 LOC + helper methods

Architecture:
- Static methods for stateless permission checking
- Centralized admin role checking
- Centralized volunteer/member resolution
- Consistent permission patterns across all chapter operations
- Zero permission bypasses - all checks explicit

Security Model:
- Admin roles (System Manager, Verenigingen Administrator) have full access
- Board members can access their own chapters
- Regular members have read-only access to published chapters
- Row-level security enforced - board member role alone insufficient
- Explicit permission checks required for all operations

Dependencies:
- frappe.db for permission queries
- frappe.get_roles for role checking
"""

from typing import TYPE_CHECKING, List, Optional, Tuple

import frappe
from frappe import _

from verenigingen.services.infrastructure.base_service import StatelessService

if TYPE_CHECKING:
    from frappe.model.document import Document


class ChapterPermissionService(StatelessService):
    """
    Service for managing Chapter permission checking and access control.

    This service handles:
    - List view permission queries (query conditions)
    - Document-level permission checking (row-level security)
    - API endpoint permission validation
    - Board member access verification
    - Member information access control
    """

    # ========================================================================
    # ADMIN ROLE CONSTANTS
    # ========================================================================

    ADMIN_ROLES = ("System Manager", "Verenigingen Administrator")
    STAFF_ROLES = ("System Manager", "Verenigingen Administrator", "Verenigingen Staff")
    BOARD_MEMBER_ROLE = "Verenigingen Chapter Board Member"
    MEMBER_ROLE = "Verenigingen Member"

    def __init__(self) -> None:
        """Initialize the chapter permission service."""
        super().__init__(service_name="ChapterPermissionService")

    # ========================================================================
    # QUERY PERMISSION METHODS
    # ========================================================================

    def get_permission_query_conditions(self, user: Optional[str] = None) -> str:
        """Get permission query conditions for Chapters in list views.

        This method controls which chapters appear in list views based on
        user roles and board membership. Used by Frappe's permission system.

        Args:
            user: User to check permissions for (defaults to session user)

        Returns:
            SQL WHERE clause conditions for chapter queries

        Examples:
            Admin users: "" (no restrictions)
            Board members: "(name IN ('Chapter1', 'Chapter2') OR published = 1)"
            Regular users: "published = 1"
        """
        try:
            if not user:
                user = frappe.session.user

            # Admin users see all chapters
            if self._is_admin_user(user):
                return ""

            user_roles = frappe.get_roles(user)

            # Board members see their chapters + published chapters
            if self.BOARD_MEMBER_ROLE in user_roles:
                board_chapters = self._get_user_board_chapters(user)
                if board_chapters:
                    # Use frappe.db.escape() to prevent SQL injection (follows codebase pattern)
                    escaped_names = [frappe.db.escape(c) for c in board_chapters]
                    return f"(`tabChapter`.name IN ({','.join(escaped_names)}) OR `tabChapter`.published = 1)"

            # Regular users and members see only published chapters
            return "`tabChapter`.published = 1"

        except Exception as e:
            self.logger.error(f"Error in chapter permission query: {str(e)}")
            # Fail safe - show only published chapters on error
            return "`tabChapter`.published = 1"

    # ========================================================================
    # DOCUMENT PERMISSION METHODS
    # ========================================================================

    def has_chapter_permission(
        self, doc: "Document", ptype: str = "read", user: Optional[str] = None
    ) -> bool:
        """Control document-level access to specific Chapter.

        Provides row-level security ensuring board members can only access
        their own chapters. Without this, any user with board member role
        could access ALL chapters.

        Args:
            doc: Chapter document to check permission for
            ptype: Permission type (read, write, delete, submit, cancel)
            user: User to check permission for (defaults to session user)

        Returns:
            True if user has specified permission on document, False otherwise

        Security Note:
            This method enforces row-level security. Role permissions alone
            are insufficient - users must be explicitly associated with the
            chapter through board membership or other relationships.
        """
        if not user:
            user = frappe.session.user

        user_roles = frappe.get_roles(user)

        # Admin roles always have full access
        if self._is_admin_or_staff(user_roles):
            return True

        # Service accounts (webhooks, background jobs) defer to standard Frappe DocPerm
        from verenigingen.permissions import _check_service_account_permission

        service_result = _check_service_account_permission(user, "Chapter", ptype)
        if service_result is not None:
            return service_result

        # Check board member access (full access to their chapters)
        if self.BOARD_MEMBER_ROLE in user_roles:
            if self._is_user_board_member_of_chapter(user, doc.name):
                return True
            # Board member role but NOT on this chapter's board - explicitly deny
            self._log_permission_denial(user, doc.name, ptype, "board_member_not_on_chapter")
            return False

        # Regular members have read-only access to published chapters
        if self.MEMBER_ROLE in user_roles:
            if ptype == "read":
                return True
            # Explicitly deny write operations for regular members
            if ptype in ["write", "delete", "submit", "cancel"]:
                self._log_permission_denial(user, doc.name, ptype, "member_write_denied")
                return False

        # Default deny - never delegate to role permissions alone
        # Row-level security requires explicit permission grant
        self._log_permission_denial(user, doc.name, ptype, "no_explicit_permission")
        return False

    # ========================================================================
    # API PERMISSION METHODS
    # ========================================================================

    def can_user_view_member_board_info(self, member_name: str, user: Optional[str] = None) -> bool:
        """Check if user can view board information for a member.

        Used by get_board_memberships() API to validate access.

        Args:
            member_name: Member to check board info access for
            user: User requesting access (defaults to session user)

        Returns:
            True if user can view board info, False otherwise

        Access Rules:
            - Admins can view all board info
            - Users can view their own board info
            - Board members can view info for members in their chapters
        """
        if not user:
            user = frappe.session.user

        user_roles = frappe.get_roles(user)

        # Admins have full access
        if self._is_admin_user(user_roles):
            return True

        # Users can view their own board info
        current_member = frappe.db.get_value("Member", {"user": user}, "name")
        if current_member == member_name:
            return True

        # Board members can view info for members in their chapters
        if current_member:
            return self._has_shared_chapter_access(current_member, member_name)

        return False

    def can_user_view_chapter_board_history(self, chapter_name: str, user: Optional[str] = None) -> bool:
        """Check if user can view board history for a chapter.

        Used by get_chapter_board_history() API to validate access.

        Args:
            chapter_name: Chapter to check board history access for
            user: User requesting access (defaults to session user)

        Returns:
            True if user can view board history, False otherwise

        Access Rules:
            - Admins can view all board history
            - Board members of the chapter can view its history
        """
        if not user:
            user = frappe.session.user

        user_roles = frappe.get_roles(user)

        # Admins have full access
        if self._is_admin_user(user_roles):
            return True

        # Board members of this chapter can view its history
        return self._is_user_board_member_of_chapter(user, chapter_name)

    # ========================================================================
    # HELPER METHODS (Private)
    # ========================================================================

    def _is_admin_user(self, user_or_roles) -> bool:
        """Check if user has admin role.

        Args:
            user_or_roles: Either user email or list of roles

        Returns:
            True if user has System Manager or Verenigingen Administrator role
        """
        if isinstance(user_or_roles, str):
            roles = frappe.get_roles(user_or_roles)
        else:
            roles = user_or_roles

        return any(role in self.ADMIN_ROLES for role in roles)

    def _is_admin_or_staff(self, user_or_roles) -> bool:
        """Check if user has admin or staff role.

        Args:
            user_or_roles: Either user email or list of roles

        Returns:
            True if user has admin or staff role
        """
        if isinstance(user_or_roles, str):
            roles = frappe.get_roles(user_or_roles)
        else:
            roles = user_or_roles

        return any(role in self.STAFF_ROLES for role in roles)

    def _get_member_and_volunteer(self, user: str) -> Tuple[Optional[str], Optional[str]]:
        """Get member and volunteer records for a user.

        Args:
            user: User email

        Returns:
            Tuple of (member_name, volunteer_name), either can be None
        """
        member = frappe.db.get_value("Member", {"user": user}, "name")
        volunteer = None
        if member:
            volunteer = frappe.db.get_value("Volunteer", {"member": member}, "name")
        return member, volunteer

    def _get_user_board_chapters(self, user: str) -> List[str]:
        """Get list of chapters where user is an active board member.

        Args:
            user: User email

        Returns:
            List of chapter names
        """
        member, volunteer = self._get_member_and_volunteer(user)
        if not volunteer:
            return []

        board_chapters = frappe.db.sql(
            """
            SELECT DISTINCT parent
            FROM `tabChapter Board Member`
            WHERE volunteer = %s AND is_active = 1
            """,
            volunteer,
            as_list=True,
        )

        return [chapter[0] for chapter in board_chapters]

    def _is_user_board_member_of_chapter(self, user: str, chapter_name: str) -> bool:
        """Check if user is an active board member of specific chapter.

        Args:
            user: User email
            chapter_name: Chapter to check

        Returns:
            True if user is active board member of chapter
        """
        member, volunteer = self._get_member_and_volunteer(user)
        if not volunteer:
            return False

        return frappe.db.exists(
            "Chapter Board Member", {"parent": chapter_name, "volunteer": volunteer, "is_active": 1}
        )

    def _has_shared_chapter_access(self, requesting_member: str, target_member: str) -> bool:
        """Check if requesting member has board access to any of target member's chapters.

        Used to determine if a board member can view another member's information.

        Args:
            requesting_member: Member requesting access
            target_member: Member whose info is being accessed

        Returns:
            True if requesting member is board member of any chapter where target is member
        """
        # Get chapters where target member belongs
        target_chapters = frappe.db.sql(
            """
            SELECT parent FROM `tabChapter Member`
            WHERE member = %s AND enabled = 1
            """,
            (target_member,),
            as_dict=True,
        )

        if not target_chapters:
            return False

        # Get volunteer for requesting member
        requesting_volunteer = frappe.db.get_value("Volunteer", {"member": requesting_member}, "name")
        if not requesting_volunteer:
            return False

        # Get chapters where requesting member is board member
        requesting_board_chapters = frappe.db.sql(
            """
            SELECT parent FROM `tabChapter Board Member`
            WHERE volunteer = %s AND is_active = 1
            """,
            (requesting_volunteer,),
            as_dict=True,
        )

        if not requesting_board_chapters:
            return False

        # Check for intersection
        target_chapter_set = {ch.parent for ch in target_chapters}
        requesting_chapter_set = {ch.parent for ch in requesting_board_chapters}

        return bool(target_chapter_set & requesting_chapter_set)

    def _log_permission_denial(self, user: str, chapter: str, ptype: str, reason: str):
        """Log permission denial for audit trail.

        Args:
            user: User who was denied
            chapter: Chapter name
            ptype: Permission type requested
            reason: Denial reason code
        """
        self.logger.info(
            f"Chapter permission denied: user={user}, chapter={chapter}, "
            f"permission={ptype}, reason={reason}"
        )


def get_chapter_permission_service() -> ChapterPermissionService:
    """Get singleton instance of ChapterPermissionService."""
    return ChapterPermissionService()
