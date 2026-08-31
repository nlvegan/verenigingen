"""
Chapter Role Event Handlers
===========================

This module provides event handlers for Chapter Board Member and Chapter Role changes
to automatically manage Chapter Board Member system role assignments and permissions.

Event Triggers:
- Chapter Board Member creation/update/deletion
- Chapter Role changes that affect board membership
- Member/Volunteer record changes that affect board positions

Security Features:
- Automatic role assignment based on active board positions
- Role removal when board positions end
- Permission validation and audit logging
- Prevention of orphaned system roles
"""

import frappe

from verenigingen.permissions import assign_chapter_board_role, get_user_chapter_board_positions
from verenigingen.utils.security.api_security_framework import OperationType, critical_api, high_security_api
from verenigingen.utils.security_decorators import development_only

# REMOVED: on_chapter_board_member_after_insert, on_chapter_board_member_on_update,
# on_chapter_board_member_on_trash. These child table doc_events never fire when
# rows are managed via parent save. Role assignment and role profile sync are now
# handled by BoardManager.handle_board_member_additions/changes/deletions.
#
# REMOVED: on_volunteer_on_update (#688). It re-ran assign_chapter_board_role()
# when Volunteer.member changed. It was registered under "Verenigingen Volunteer"
# -- a Role name, not a DocType -- so it never fired, and BoardManager was built
# in its absence to own the same decision. Restoring it would make a second writer
# of the board role, and a broken one: assign_chapter_board_role()'s else-branch
# raw-deletes the Has Role row WITHOUT the role-profile sync that must precede it
# (User.populate_role_profile_roles resets User.roles from the assigned profile on
# every save), so the removal would be undone by the next User save. See
# BoardManager.flush_pending_board_profile_syncs for the ordering that is correct.
#
# That defect is NOT gone -- it was only removed from a registration that never
# ran. on_member_on_update and on_chapter_role_on_update below are registered
# under real DocTypes and call the same function, so they ship it live. Tracked
# in #702; do not read this block as "the second-writer problem was fixed".
#
# #702 also carries the case BoardManager structurally cannot see: Volunteer.member
# is editable (unique, but not set_only_once), and BoardManager runs only from
# Chapter.on_update, so a re-link leaves board access on the old member's user.
# Restoring this handler would not have closed that either -- it removes the Role
# and never the role profile that re-grants it.


def on_member_on_update(doc, method):
    """
    Event handler for Member updates
    Re-evaluates board roles if user field changes
    """
    try:
        # Check if the user field changed
        if doc.has_value_changed("user"):
            old_user = doc._doc_before_save.get("user") if doc._doc_before_save else None
            new_user = doc.user

            # Handle old user - remove board role
            if old_user:
                assign_chapter_board_role(old_user)
                frappe.logger().info(f"Re-evaluated board role for old user {old_user}")

            # Handle new user - assign board role if they have board positions
            if new_user:
                assign_chapter_board_role(new_user)
                frappe.logger().info(f"Re-evaluated board role for new user {new_user}")

    except Exception as e:
        frappe.log_error(f"Error in member update handler: {str(e)}")


def on_chapter_role_on_update(doc, method):
    """
    Event handler for Chapter Role updates
    Re-evaluates board member roles if permissions_level changes
    """
    try:
        # Check if permissions_level changed - this affects treasurer status
        if doc.has_value_changed("permissions_level") or doc.has_value_changed("is_active"):
            # Get all board members with this chapter role
            board_members = frappe.get_all(
                "Chapter Board Member",
                filters={"chapter_role": doc.name, "is_active": 1},
                fields=["volunteer"],
            )

            for board_member in board_members:
                if board_member.volunteer:
                    volunteer_doc = frappe.get_doc("Volunteer", board_member.volunteer)
                    if volunteer_doc.member:
                        member_doc = frappe.get_doc("Member", volunteer_doc.member)
                        user_email = member_doc.user or member_doc.email

                        if user_email:
                            assign_chapter_board_role(user_email)
                            frappe.logger().info(
                                f"Re-evaluated board role for {user_email} due to chapter role changes"
                            )

    except Exception as e:
        frappe.log_error(f"Error in chapter role update handler: {str(e)}")


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def sync_all_chapter_board_roles():
    """
    Maintenance function to sync all Chapter Board Member system roles
    Can be called manually or scheduled
    """
    try:
        from verenigingen.permissions import update_all_chapter_board_roles

        result = update_all_chapter_board_roles()

        return {
            "success": True,
            "updated_count": result,
            "message": f"Successfully synced Chapter Board Member roles for {result} users",
        }

    except Exception as e:
        frappe.log_error(f"Error syncing chapter board roles: {str(e)}")
        return {"success": False, "error": str(e), "message": "Failed to sync Chapter Board Member roles"}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.REPORTING)
def get_user_board_summary(user_email: str | None = None):
    """
    Get summary of user's board positions and permissions
    Useful for debugging and administration
    """
    try:
        if not user_email:
            user_email = frappe.session.user

        # Get user's member record
        user_member = frappe.db.get_value("Member", {"user": user_email}, "name")
        if not user_member:
            user_member = frappe.db.get_value("Member", {"email": user_email}, "name")

        if not user_member:
            return {"success": False, "message": "No member record found for user"}

        # Get board positions
        board_positions = get_user_chapter_board_positions(user_member)

        # Check system role status
        has_board_role = frappe.db.exists(
            "Has Role", {"parent": user_email, "role": "Verenigingen Chapter Board Member"}
        )

        # Check treasurer status
        treasurer_chapters = []
        for position in board_positions:
            if position.get("permissions_level") == "Financial":
                treasurer_chapters.append(position.get("chapter_name"))

        return {
            "success": True,
            "user_email": user_email,
            "member_name": user_member,
            "board_positions": board_positions,
            "has_chapter_board_role": bool(has_board_role),
            "treasurer_chapters": treasurer_chapters,
            "can_approve_expenses": len(treasurer_chapters) > 0,
        }

    except Exception as e:
        frappe.log_error(f"Error getting user board summary: {str(e)}")
        return {"success": False, "error": str(e), "message": "Failed to get user board summary"}
