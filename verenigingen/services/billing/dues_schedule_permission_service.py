# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
DuesSchedulePermissionService - Permission management for Membership Dues Schedule.

This service handles all permission-related logic for dues schedules, including:
- Document permission validation
- User edit permission checks
- Member self-edit validation
- Chapter board financial permission checks
- List view query conditions

Extracted from membership_dues_schedule.py to reduce controller size
and improve testability.

Architecture:
- StatelessService base class for consistent logging and error handling
- Returns OperationResult for success/failure with detailed messages
"""

from typing import TYPE_CHECKING, Any, Dict, List, Optional

import frappe
from frappe import _

from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.utils.constants import Roles
from verenigingen.utils.member_utils import get_member_chapters

if TYPE_CHECKING:
    from frappe.model.document import Document


class PermissionResult:
    """
    Result object for permission checks.

    Provides structured permission status with detailed reasons.

    Attributes:
        allowed: Whether the permission is granted
        reason: Human-readable explanation
        permission_level: The level of permission ("admin", "staff", "board", "member", "none")
    """

    def __init__(self, allowed: bool, reason: str, permission_level: str = "none"):
        self.allowed = allowed
        self.reason = reason
        self.permission_level = permission_level
        # OperationResult-compatible properties
        self.success = allowed
        self.error_message = reason if not allowed else None

    def __bool__(self):
        return self.allowed


class DuesSchedulePermissionService(StatelessService):
    """
    Service for managing permissions on Membership Dues Schedule documents.

    Centralizes all permission logic for dues schedules including:
    - Document-level permission checks (has_permission)
    - Edit validation based on user role
    - Chapter board financial permission verification
    - List view query condition generation

    Example:
        service = get_dues_schedule_permission_service()
        result = service.validate_permissions(schedule_doc)
        if not result.allowed:
            frappe.throw(result.reason)
    """

    def __init__(self):
        super().__init__(service_name="DuesSchedulePermissionService")

    def validate_permissions(self, schedule_doc: "Document", user: Optional[str] = None) -> PermissionResult:
        """
        Validate user permissions for editing a dues schedule document.

        This is the main entry point for permission validation during document
        validation (before save).

        Args:
            schedule_doc: The Membership Dues Schedule document
            user: User to check permissions for (defaults to current user)

        Returns:
            PermissionResult with allowed status and reason

        Raises:
            frappe.ValidationError: If permission check fails and should stop save
        """
        # Skip permission check if ignore_permissions flag is set
        if getattr(schedule_doc, "_ignore_permissions", False) or frappe.flags.ignore_permissions:
            return PermissionResult(True, "Permissions explicitly ignored", "admin")

        if not schedule_doc.is_new() and schedule_doc.has_value_changed("is_template"):
            return PermissionResult(False, "Cannot change template status after creation")

        if not user:
            user = frappe.session.user

        # System Manager and configured creation user always have full access
        creation_user = None
        try:
            settings = frappe.get_single("Verenigingen Settings")
            creation_user = getattr(settings, "creation_user", None)
        except Exception:
            pass

        admin_users = [Roles.SYSTEM_MANAGER]
        if creation_user:
            admin_users.append(creation_user)
        else:
            admin_users.append("Administrator")  # Fallback

        if user in admin_users or Roles.SYSTEM_MANAGER in frappe.get_roles(user):
            return PermissionResult(True, "System Manager access", "admin")

        # Check if user has Verenigingen Administrator role
        if Roles.VERENIGINGEN_ADMIN in frappe.get_roles(user):
            return PermissionResult(True, "Verenigingen Administrator access", "admin")

        # Template editing is restricted to Verenigingen Administrator only
        if schedule_doc.is_template:
            return PermissionResult(False, "Only Verenigingen Administrators can edit template schedules")

        # For individual schedules, check various permission levels
        can_edit_result = self.can_user_edit_schedule(schedule_doc, user)
        if not can_edit_result.allowed:
            return can_edit_result

        return PermissionResult(True, "Permission granted", can_edit_result.permission_level)

    def can_user_edit_schedule(self, schedule_doc: "Document", user: str) -> PermissionResult:
        """
        Check if user can edit an individual (non-template) schedule.

        Checks in order of precedence:
        1. Is the user the member themselves?
        2. Does the user have Verenigingen Staff role?
        3. Is the user a chapter board member with financial permissions?

        Args:
            schedule_doc: The dues schedule document
            user: User to check permissions for

        Returns:
            PermissionResult with allowed status, reason, and permission level
        """
        if not schedule_doc.member:
            return PermissionResult(False, "Schedule has no member assigned")

        # Check if user is the member themselves
        member_user = frappe.db.get_value("Member", schedule_doc.member, "user")
        if member_user == user:
            # Member can edit their own schedule (with field restrictions)
            member_edit_result = self.validate_member_edit(schedule_doc)
            if member_edit_result.allowed:
                return PermissionResult(True, "Member self-edit allowed", "member")
            return member_edit_result

        # Check if user has Verenigingen Staff role
        if Roles.VERENIGINGEN_STAFF in frappe.get_roles(user):
            return PermissionResult(True, "Verenigingen Staff access", "staff")

        # Check if user is a chapter board member with finance permissions
        if self.is_chapter_board_with_finance(schedule_doc.member, user):
            return PermissionResult(True, "Chapter board with finance access", "board")

        return PermissionResult(False, "You don't have permission to edit this dues schedule")

    def validate_member_edit(self, schedule_doc: "Document") -> PermissionResult:
        """
        Validate what fields a member can edit on their own schedule.

        Members can only edit certain fields:
        - dues_rate (if meets minimum)
        - base_multiplier
        - contribution_mode
        - selected_tier
        - uses_custom_amount
        - custom_amount_reason
        - notes
        - status

        Args:
            schedule_doc: The dues schedule document being edited

        Returns:
            PermissionResult indicating if the edit is allowed
        """
        allowed_fields = [
            "dues_rate",
            "default_multiplier",
            "contribution_mode",
            "selected_tier",
            "uses_custom_amount",
            "custom_amount_reason",
            "notes",
            "status",
        ]

        # New documents are always allowed
        if schedule_doc.is_new():
            return PermissionResult(True, "New schedule creation allowed", "member")

        # Check each field for changes
        for field in schedule_doc.meta.fields:
            if field.fieldname in allowed_fields:
                continue

            if schedule_doc.has_value_changed(field.fieldname):
                # Special case: dues_rate can be changed if it meets minimum
                if field.fieldname == "dues_rate":
                    from verenigingen.services.billing.dues_schedule_validation_service import (
                        get_dues_schedule_validation_service,
                    )

                    rate_valid = get_dues_schedule_validation_service().validate_dues_rate_change(
                        schedule_doc
                    )
                    if rate_valid:
                        continue

                return PermissionResult(False, f"Members cannot modify the field: {field.label}")

        return PermissionResult(True, "Member edit validation passed", "member")

    def is_chapter_board_with_finance(self, member_name: str, user: str) -> bool:
        """
        Check if user is a chapter board member with financial permissions.

        This allows chapter treasurers and financial officers to manage
        dues schedules for members in their chapter.

        Args:
            member_name: Name of the member whose schedule is being accessed
            user: User to check permissions for

        Returns:
            True if user has chapter board financial permissions, False otherwise
        """
        if not member_name:
            return False

        # Get member's chapter through standardized utility
        chapters = get_member_chapters(member_name, active_only=True)
        if not chapters:
            return False
        chapter = chapters[0]  # Use first active chapter

        # Get the user's member record
        user_member_name = frappe.db.get_value("Member", {"user": user}, "name")
        if not user_member_name:
            return False

        # Get the volunteer linked to the member
        volunteer_name = frappe.db.get_value("Volunteer", {"member": user_member_name}, "name")
        if not volunteer_name:
            return False

        # Check if user is a board member of this chapter with finance permissions
        board_member = frappe.db.get_value(
            "Chapter Board Member",
            {
                "parent": chapter,
                "volunteer": volunteer_name,
                "is_active": 1,
            },
            ["name", "chapter_role"],
            as_dict=True,
        )

        if not board_member:
            return False

        # Check if the role has financial permissions
        if board_member.chapter_role:
            role_doc = frappe.get_doc("Chapter Role", board_member.chapter_role)
            return getattr(role_doc, "permissions_level", None) in ["Financial", "Admin"]

        return False

    def check_document_permission(
        self,
        doc: "Document",
        user: Optional[str] = None,
        permission_type: str = "read",
    ) -> bool:
        """
        Custom permission handler for Membership Dues Schedule.

        This is called by Frappe's permission system (has_permission hook).

        Args:
            doc: The document to check permissions for
            user: User to check (defaults to current user)
            permission_type: Type of permission ("read", "write", etc.)

        Returns:
            True if permission is granted, False otherwise
        """
        if not user:
            user = frappe.session.user

        self.logger.debug(
            f"Permission check: User {user}, Doc {doc.name if hasattr(doc, 'name') else 'Unknown'}, "
            f"Type {permission_type}"
        )

        # System Manager always has access
        if Roles.SYSTEM_MANAGER in frappe.get_roles(user):
            return True

        # Verenigingen Administrator and Manager have full access
        user_roles = frappe.get_roles(user)
        if any(role in user_roles for role in [Roles.VERENIGINGEN_ADMIN, Roles.VERENIGINGEN_STAFF]):
            return True

        # Templates are visible to all authenticated users (for viewing available options)
        if hasattr(doc, "is_template") and doc.is_template:
            return True

        # For non-templates, only allow access if user is the member
        if hasattr(doc, "member") and doc.member:
            member_user = frappe.db.get_value("Member", doc.member, "user")
            if member_user == user:
                return True

        # Check if user is chapter board member
        if hasattr(doc, "member") and doc.member and "Verenigingen Chapter Board Member" in user_roles:
            try:
                # Get member's chapters
                member_chapters = frappe.db.get_all(
                    "Chapter Member",
                    filters={"member": doc.member, "status": "Active"},
                    fields=["parent"],
                    pluck="parent",
                )

                if member_chapters:
                    # Get user's member and volunteer records
                    user_member = frappe.db.get_value("Member", {"user": user}, "name")
                    if user_member:
                        user_volunteer = frappe.db.get_value("Volunteer", {"member": user_member}, "name")
                        if user_volunteer:
                            # Check if user is board member in any of the member's chapters
                            board_position = frappe.db.exists(
                                "Chapter Board Member",
                                {
                                    "parent": ["in", member_chapters],
                                    "volunteer": user_volunteer,
                                    "is_active": 1,
                                },
                            )
                            if board_position:
                                return True
            except Exception as e:
                self.logger.error(f"Error checking chapter board permission: {str(e)}")

        return False

    def get_permission_query_conditions(self, user: Optional[str] = None) -> str:
        """
        Generate permission query conditions for Membership Dues Schedule list views.

        Returns SQL WHERE clause fragment to filter documents based on user permissions.

        Args:
            user: User to generate conditions for (defaults to current user)

        Returns:
            SQL WHERE clause fragment (empty string for full access)
        """
        if not user:
            user = frappe.session.user

        # System Manager and admin roles get full access
        user_roles = frappe.get_roles(user)
        if Roles.SYSTEM_MANAGER in user_roles:
            return ""  # No restrictions

        if any(role in user_roles for role in [Roles.VERENIGINGEN_ADMIN, Roles.VERENIGINGEN_STAFF]):
            return ""  # No restrictions

        # Chapter Board Members can access dues schedules for members in their chapters
        if "Verenigingen Chapter Board Member" in user_roles:
            # Get chapters where user is a board member
            user_member = frappe.db.get_value("Member", {"user": user}, "name")
            if user_member:
                volunteer = frappe.db.get_value("Volunteer", {"member": user_member}, "name")
                if volunteer:
                    chapters = frappe.db.sql(
                        """
                        SELECT DISTINCT cbm.parent
                        FROM `tabChapter Board Member` cbm
                        WHERE cbm.volunteer = %s AND cbm.is_active = 1
                        """,
                        volunteer,
                        as_dict=False,
                    )

                    if chapters:
                        # Use proper SQL escaping to prevent SQL injection
                        chapter_names = [frappe.db.escape(c[0]) for c in chapters]
                        escaped_member = frappe.db.escape(user_member)
                        # Allow templates OR records for members in their chapters OR their own
                        return f"""(
                            `tabMembership Dues Schedule`.is_template = 1
                            OR `tabMembership Dues Schedule`.member IN (
                                SELECT DISTINCT cm.member
                                FROM `tabChapter Member` cm
                                WHERE cm.parent IN ({','.join(chapter_names)})
                                  AND cm.status = 'Active'
                            )
                            OR `tabMembership Dues Schedule`.member = {escaped_member}
                        )"""

        # For regular members, restrict to templates OR their own records
        user_member = frappe.db.get_value("Member", {"user": user}, "name")

        if user_member:
            # Use proper SQL escaping to prevent SQL injection
            escaped_member = frappe.db.escape(user_member)
            # Allow templates OR records where the member field matches their member record
            return f"(`tabMembership Dues Schedule`.is_template = 1 OR `tabMembership Dues Schedule`.member = {escaped_member})"
        else:
            # Only allow templates if user is not linked to a member
            return "`tabMembership Dues Schedule`.is_template = 1"


def get_dues_schedule_permission_service() -> DuesSchedulePermissionService:
    """Get singleton instance of DuesSchedulePermissionService."""
    return DuesSchedulePermissionService()


# Module-level functions for Frappe hooks compatibility
def has_permission(doc, user=None, permission_type="read"):
    """
    Frappe hook-compatible function for document permission checks.

    This function is registered in hooks.py to be called by Frappe's permission system.
    """
    return get_dues_schedule_permission_service().check_document_permission(doc, user, permission_type)


def get_permission_query_conditions(user=None):
    """
    Frappe hook-compatible function for list view permission filtering.

    This function is registered in hooks.py to filter list views.
    """
    return get_dues_schedule_permission_service().get_permission_query_conditions(user)
