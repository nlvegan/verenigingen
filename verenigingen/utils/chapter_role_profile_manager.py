"""
Chapter Role Profile Manager

Automatically assigns role profiles when users join/leave chapter board positions based on chapter board configuration.
This implementation uses the BaseRoleProfileManager for shared functionality.

Business Rules:
- When a user joins a chapter board, they get the associated role profile
- When a user leaves a chapter board, their role profile is removed (if no other boards require it)
- Multiple chapters can share the same role profile requirements
- Users can have multiple role profiles from different chapter positions

Author: Verenigingen Development Team
Last Updated: 2025-08-26
"""

from typing import Dict, List, Optional

import frappe
from frappe import _
from frappe.query_builder import DocType

from verenigingen.utils.base_role_profile_manager import (
    BaseRoleProfileManager,
    EntityConfig,
    _is_system_operation_authorized,
    safe_hook_execution,
)
from verenigingen.utils.security.api_security_framework import OperationType, critical_api, high_security_api

# Chapter-specific configuration
CHAPTER_CONFIG = EntityConfig(
    entity_type="chapter",
    entity_label="Chapter",
    doctype="Chapter",
    member_doctype="Chapter Board Member",
    role_doctype="Chapter Role",
    default_profile_field="default_board_role_profile",
    enable_specific_field="enable_board_role_specific_profiles",
    specific_profiles_field="board_role_specific_profiles",
    child_table_doctype="Chapter Role Profile Mapping",
    role_field_in_child="chapter_role",
    member_enabled_field="is_active",
    member_status_field=None,
    member_status_active_value=None,
    member_role_field="chapter_role",
    log_context="Chapter Role Profile Manager",
)


class ChapterRoleProfileManager(BaseRoleProfileManager):
    """Chapter-specific implementation of role profile management"""

    def __init__(self):
        """Initialize with chapter configuration"""
        super().__init__(CHAPTER_CONFIG)

    def _user_still_in_other_entities(self, user: str, other_entities: List[str]) -> bool:
        """Check if user is still active in other chapter boards"""
        user_member = frappe.db.get_value("Member", {"user": user}, "name")

        if user_member and other_entities:
            # Check if user is still on other chapter boards that require this profile
            other_board_memberships = frappe.db.exists(
                "Chapter Board Member",
                {"member": user_member, "is_active": 1, "parent": ["in", other_entities]},
            )
            return bool(other_board_memberships)

        return False

    def _get_bulk_members_data(self, entity_name: str) -> List[Dict]:
        """Get chapter board members data for bulk operations"""
        CBM = DocType("Chapter Board Member")
        Member = DocType("Member")
        User = DocType("User")

        return (
            frappe.qb.from_(CBM)
            .left_join(Member)
            .on(CBM.member == Member.name)
            .left_join(User)
            .on(Member.user == User.name)
            .select(CBM.member, CBM.chapter_role, Member.user, User.enabled.as_("user_enabled"))
            .where(
                (CBM.parent == entity_name)
                & (CBM.is_active == 1)
                & (Member.user.isnotnull())
                & (User.enabled == 1)
            )
        ).run(as_dict=True)

    def _get_user_from_member_doc(self, doc: "frappe._dict") -> Optional[str]:
        """Extract user from chapter board member document

        Args:
            doc: ChapterBoardMember document with volunteer and chapter_role fields
        """
        # Chapter board members have a volunteer field
        if doc.get("volunteer"):
            volunteer_member = frappe.db.get_value(
                "Volunteer", doc.volunteer, "member"  # ast-skip: doc is ChapterBoardMember
            )
            if volunteer_member:
                return frappe.db.get_value("Member", volunteer_member, "user")
        return None


# Global instance for convenience
_chapter_manager = ChapterRoleProfileManager()


# Public API Functions (maintain backward compatibility)
def get_chapter_role_profile_config(chapter_name):
    """
    Get role profile configuration for a chapter from database.

    Returns:
        dict: Configuration with default_profile and role_specific_profiles
    """
    return _chapter_manager.get_entity_role_profile_config(chapter_name)


def determine_role_profile_for_board_member(chapter_name, board_role=None):
    """
    Determine which role profile should be assigned to a chapter board member.

    Args:
        chapter_name: Name of the chapter
        board_role: Specific board role (optional)

    Returns:
        str: Role profile name or None
    """
    return _chapter_manager.determine_role_profile_for_member(chapter_name, board_role)


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def assign_chapter_board_role_profile(user, chapter_name, board_role=None):
    """
    Assign role profile when user joins a chapter board

    Args:
        user: User email/name
        chapter_name: Name of the chapter they're joining the board of
        board_role: Board role (optional, for future role-specific assignments)

    Returns:
        dict: Success/failure result
    """
    return _chapter_manager.assign_role_profile(user, chapter_name, board_role)


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def remove_chapter_board_role_profile(user, chapter_name, board_role=None):
    """
    Remove role profile when user leaves a chapter board

    Args:
        user: User email/name
        chapter_name: Name of the chapter they're leaving the board of
        board_role: Board role (optional, for future role-specific assignments)

    Returns:
        dict: Success/failure result
    """
    return _chapter_manager.remove_role_profile(user, chapter_name, board_role)


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def bulk_assign_chapter_board_role_profiles(chapter_name):
    """
    Bulk assign role profiles to all existing board members of a chapter
    Useful for initial setup or fixing missing assignments
    """
    return _chapter_manager.bulk_assign_role_profiles(chapter_name)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.REPORTING)
def get_chapter_board_role_profile_mapping():
    """Get the current chapter board to role profile mapping for admin reference"""
    mapping = {}

    # Get configured chapter mappings only
    chapters = frappe.get_all(
        "Chapter",
        filters={"default_board_role_profile": ["is", "set"]},
        fields=["name", "default_board_role_profile"],
    )

    for chapter in chapters:
        if chapter.default_board_role_profile:
            mapping[chapter.name] = chapter.default_board_role_profile

    return mapping


def get_chapters_requiring_role_profile(role_profile, exclude_chapter=None):
    """
    Get list of chapters that require a specific role profile for board members.

    Args:
        role_profile: Role profile name to search for
        exclude_chapter: Chapter to exclude from results

    Returns:
        list: Chapter names that require this role profile
    """
    return _chapter_manager.get_entities_requiring_role_profile(role_profile, exclude_chapter)


def get_chapters_for_role_profile(role_profile):
    """
    Get all chapters that are configured to use a specific role profile.

    Args:
        role_profile: Role profile name to search for

    Returns:
        List of dicts with chapter info: [{"name": chapter_name, "entity_label": chapter_name, "usage_type": type}]
    """
    return _chapter_manager.get_entities_using_role_profile(role_profile)


# Hook functions for Chapter Board Member document events
def on_chapter_board_member_add(doc: "frappe._dict", method: str):
    """Hook called when Chapter Board Member is added

    Args:
        doc: ChapterBoardMember document with volunteer, parent, and chapter_role fields
        method: Hook method name
    """
    if doc.is_active:
        user = _chapter_manager._get_user_from_member_doc(doc)
        if user:

            def assign_role():
                return assign_chapter_board_role_profile(
                    user, doc.parent, doc.chapter_role  # ast-skip: doc is ChapterBoardMember
                )

            result = safe_hook_execution(assign_role)
            if result and not result.get("success"):
                frappe.logger().warning(f"Failed to assign chapter board role profile: {result.get('error')}")


def on_chapter_board_member_remove(doc: "frappe._dict", method: str):
    """Hook called when Chapter Board Member is removed

    Args:
        doc: ChapterBoardMember document with volunteer, parent, and chapter_role fields
        method: Hook method name
    """
    user = _chapter_manager._get_user_from_member_doc(doc)
    if user:

        def remove_role():
            return remove_chapter_board_role_profile(
                user, doc.parent, doc.chapter_role  # ast-skip: doc is ChapterBoardMember
            )

        result = safe_hook_execution(remove_role)
        if result and not result.get("success"):
            frappe.logger().warning(f"Failed to remove chapter board role profile: {result.get('error')}")


def on_chapter_board_member_update(doc: "frappe._dict", method: str):
    """Hook called when Chapter Board Member is updated

    Args:
        doc: ChapterBoardMember document with volunteer, parent, and chapter_role fields
        method: Hook method name
    """
    # Handle is_active status changes
    if doc.has_value_changed("is_active"):
        user = _chapter_manager._get_user_from_member_doc(doc)
        if user:
            if doc.is_active:

                def assign_role():
                    return assign_chapter_board_role_profile(
                        user, doc.parent, doc.chapter_role  # ast-skip: doc is ChapterBoardMember
                    )

                safe_hook_execution(assign_role)
            else:

                def remove_role():
                    return remove_chapter_board_role_profile(
                        user, doc.parent, doc.chapter_role  # ast-skip: doc is ChapterBoardMember
                    )

                safe_hook_execution(remove_role)


# For backward compatibility - maintain the old validation function
def _validate_role_assignment_inputs(user, entity_name, role, entity_type):
    """Legacy validation function for backward compatibility"""
    return _chapter_manager._validate_role_assignment_inputs(user, entity_name, role)
