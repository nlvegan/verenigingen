"""
Chapter Role Profile Manager

Automatically assigns role profiles when users join/leave chapter board positions based on chapter board configuration.
This provides a reusable, maintainable way to manage chapter board-based role assignments.

Business Rules:
- When a user joins a chapter board, they get the associated role profile
- When a user leaves a chapter board, their role profile is removed (if no other boards require it)
- Multiple chapters can share the same role profile requirements
- Users can have multiple role profiles from different chapter positions

Author: Verenigingen Development Team
Last Updated: 2025-08-24
"""

from typing import Dict, List, Optional

import frappe
from frappe import _

# Chapter Board Position to Role Profile Mapping
CHAPTER_BOARD_ROLE_PROFILE_MAPPING = {
    # All chapter board positions get the Chapter Board role profile
    # This could be expanded for specific roles in the future:
    # "Chapter Treasurer": "Verenigingen Treasurer",
    # "Chapter Secretary": "Verenigingen Chapter Board",
    "default": "Verenigingen Board Member",  # Default for all chapter board positions
}


@frappe.whitelist()
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
    try:
        # For now, all chapter board positions get the same role profile
        # In the future, this could be expanded to handle specific roles
        role_profile = CHAPTER_BOARD_ROLE_PROFILE_MAPPING.get(
            board_role, CHAPTER_BOARD_ROLE_PROFILE_MAPPING["default"]
        )

        # Check if role profile exists
        if not frappe.db.exists("Role Profile", role_profile):
            frappe.logger().warning(f"Role Profile {role_profile} does not exist for chapter board position")
            return {"success": False, "error": f"Role Profile {role_profile} does not exist"}

        # Get user document
        user_doc = frappe.get_doc("User", user)

        # Assign the role profile if not already assigned
        if user_doc.role_profile_name != role_profile:
            # Store previous role profile for rollback if needed
            previous_role_profile = user_doc.role_profile_name

            user_doc.role_profile_name = role_profile
            user_doc.save(ignore_permissions=True)  # System operation

            frappe.logger().info(
                f"Chapter Role Profile Manager: Assigned '{role_profile}' to user {user} "
                f"for chapter {chapter_name} board position (role: {board_role or 'Member'})"
            )

            return {
                "success": True,
                "message": f"Assigned role profile '{role_profile}' to user",
                "role_profile": role_profile,
                "previous_role_profile": previous_role_profile,
                "action": "assigned",
            }
        else:
            return {
                "success": True,
                "message": f"User already has role profile '{role_profile}'",
                "action": "already_assigned",
            }

    except Exception as e:
        error_msg = f"Error assigning role profile for chapter {chapter_name} board: {str(e)}"
        frappe.log_error(frappe.get_traceback(), "Chapter Board Role Profile Assignment Error")
        return {"success": False, "error": error_msg}


@frappe.whitelist()
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
    try:
        # For now, all chapter board positions get the same role profile
        role_profile = CHAPTER_BOARD_ROLE_PROFILE_MAPPING.get(
            board_role, CHAPTER_BOARD_ROLE_PROFILE_MAPPING["default"]
        )

        # Check if user still belongs to other chapter boards that require this role profile
        user_member = frappe.db.get_value("Member", {"user": user}, "name")
        if user_member:
            # Check if user is still on other chapter boards
            other_board_memberships = frappe.db.exists(
                "Chapter Board Member",
                {"member": user_member, "enabled": 1, "parent": ["!=", chapter_name]},  # Different chapter
            )

            if other_board_memberships:
                return {
                    "success": True,
                    "message": f"User still on other chapter boards requiring '{role_profile}', keeping role profile",
                    "action": "kept",
                }

        # Safe to remove role profile
        user_doc = frappe.get_doc("User", user)
        if user_doc.role_profile_name == role_profile:
            previous_role_profile = user_doc.role_profile_name
            user_doc.role_profile_name = None  # or set to default member profile
            user_doc.save(ignore_permissions=True)  # System operation

            frappe.logger().info(
                f"Chapter Role Profile Manager: Removed '{role_profile}' from user {user} "
                f"for chapter {chapter_name} board position (role: {board_role or 'Member'})"
            )

            return {
                "success": True,
                "message": f"Removed role profile '{role_profile}' from user",
                "previous_role_profile": previous_role_profile,
                "action": "removed",
            }
        else:
            return {
                "success": True,
                "message": f"User does not have role profile '{role_profile}'",
                "action": "not_assigned",
            }

    except Exception as e:
        error_msg = f"Error removing role profile for chapter {chapter_name} board: {str(e)}"
        frappe.log_error(frappe.get_traceback(), "Chapter Board Role Profile Removal Error")
        return {"success": False, "error": error_msg}


def on_chapter_board_member_add(doc, method):
    """Hook called when Chapter Board Member is added"""
    if doc.enabled and doc.volunteer:
        # Get user from volunteer's member
        volunteer_member = frappe.db.get_value("Volunteer", doc.volunteer, "member")
        user = frappe.db.get_value("Member", volunteer_member, "user") if volunteer_member else None
        if user:
            result = assign_chapter_board_role_profile(user, doc.parent, doc.chapter_role)
            if not result.get("success"):
                frappe.logger().warning(f"Failed to assign chapter board role profile: {result.get('error')}")


def on_chapter_board_member_remove(doc, method):
    """Hook called when Chapter Board Member is removed"""
    if doc.member:
        # Get user from member
        user = frappe.db.get_value("Member", doc.member, "user")
        if user:
            result = remove_chapter_board_role_profile(user, doc.parent, doc.chapter_role)
            if not result.get("success"):
                frappe.logger().warning(f"Failed to remove chapter board role profile: {result.get('error')}")


def on_chapter_board_member_update(doc, method):
    """Hook called when Chapter Board Member is updated"""
    # Handle enabled status changes
    if doc.has_value_changed("enabled"):
        if doc.member:
            user = frappe.db.get_value("Member", doc.member, "user")
            if user:
                if doc.enabled:
                    assign_chapter_board_role_profile(user, doc.parent, doc.chapter_role)
                else:
                    remove_chapter_board_role_profile(user, doc.parent, doc.chapter_role)


@frappe.whitelist()
def get_chapter_board_role_profile_mapping():
    """Get the current chapter board to role profile mapping for admin reference"""
    return CHAPTER_BOARD_ROLE_PROFILE_MAPPING


@frappe.whitelist()
def bulk_assign_chapter_board_role_profiles(chapter_name):
    """
    Bulk assign role profiles to all existing board members of a chapter
    Useful for initial setup or fixing missing assignments
    """
    try:
        # Get all active chapter board members
        board_members = frappe.get_all(
            "Chapter Board Member",
            filters={"parent": chapter_name, "enabled": 1},
            fields=["member", "chapter_role"],
        )

        results = []
        for bm in board_members:
            if bm.member:
                user = frappe.db.get_value("Member", bm.member, "user")
                if user:
                    result = assign_chapter_board_role_profile(user, chapter_name, bm.chapter_role)
                    results.append({"user": user, "member": bm.member, "result": result})

        return {
            "success": True,
            "message": f"Processed {len(results)} chapter board members",
            "results": results,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
