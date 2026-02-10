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
            # Get volunteer record for this member
            volunteer = frappe.db.get_value("Volunteer", {"member": user_member}, "name")
            if not volunteer:
                return False

            # Check if volunteer is still on other chapter boards that require this profile
            other_board_memberships = frappe.db.exists(
                "Chapter Board Member",
                {"volunteer": volunteer, "is_active": 1, "parent": ["in", other_entities]},
            )
            return bool(other_board_memberships)

        return False

    def _get_bulk_members_data(self, entity_name: str) -> List[Dict]:
        """Get chapter board members data for bulk operations.

        Chapter Board Member has a `volunteer` field (not `member`), so the
        join path is: CBM.volunteer → Volunteer.member → Member.user → User.
        """
        CBM = DocType("Chapter Board Member")
        Volunteer = DocType("Volunteer")
        Member = DocType("Member")
        User = DocType("User")

        return (
            frappe.qb.from_(CBM)
            .left_join(Volunteer)
            .on(CBM.volunteer == Volunteer.name)
            .left_join(Member)
            .on(Volunteer.member == Member.name)
            .left_join(User)
            .on(Member.user == User.name)
            .select(Member.name.as_("member"), CBM.chapter_role, Member.user, User.enabled.as_("user_enabled"))
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
    """Recalculate role profiles for all active board members of a chapter.

    Uses auto_sync_on_role_change() which derives the correct profile from
    ground truth (actual DB state) rather than trying to assign a specific profile.
    """
    from verenigingen.utils.user_role_profile_calculator import auto_sync_on_role_change

    if not frappe.db.exists("Chapter", chapter_name):
        return {"success": False, "members_updated": 0, "message": f"Chapter '{chapter_name}' does not exist"}

    # Get active board members: CBM.volunteer → Volunteer.member → Member.user
    board_members = frappe.db.sql(
        """
        SELECT DISTINCT m.user
        FROM `tabChapter Board Member` cbm
        JOIN `tabVolunteer` v ON cbm.volunteer = v.name
        JOIN `tabMember` m ON v.member = m.name
        WHERE cbm.parent = %s
          AND cbm.is_active = 1
          AND m.user IS NOT NULL
          AND m.user != ''
        """,
        (chapter_name,),
        as_dict=True,
    )

    updated = 0
    for row in board_members:
        user = row["user"] if isinstance(row, dict) else row.user
        try:
            auto_sync_on_role_change(user)
            updated += 1
        except Exception as e:
            frappe.log_error(
                f"Role profile sync failed for {user}: {e}",
                "Bulk Board Role Profile Sync",
            )

    return {"success": updated > 0 or len(board_members) == 0, "members_updated": updated}


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


# REMOVED: Child table hook functions (on_chapter_board_member_add/remove/update).
# Frappe child table doc_events (after_insert, on_update, on_trash) never fire when
# rows are managed via parent save. Role assignment and role profile sync are now
# handled by BoardManager.handle_board_member_additions/changes/deletions.


# For backward compatibility - maintain the old validation function
def _validate_role_assignment_inputs(user, entity_name, role, entity_type):
    """Legacy validation function for backward compatibility"""
    return _chapter_manager._validate_role_assignment_inputs(user, entity_name, role)
