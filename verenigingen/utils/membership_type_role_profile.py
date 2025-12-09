"""
Membership Type Role Profile Utility

Simple utility functions for assigning/removing role profiles based on membership type.
Called from:
- Contribution Amendment Request (when membership type changes)
- Member approval workflow (when membership is first created)
- Member termination workflow (when membership ends)

Unlike the chapter/team role profile managers which handle complex entity-based assignments,
this utility handles the simpler case where each membership type has exactly one role profile.

Author: Verenigingen Development Team
Created: 2025-12-09
"""

from typing import Dict, Optional

import frappe
from frappe import _

from verenigingen.utils.secure_operations import secure_document_operation


def get_role_profile_for_membership_type(membership_type: str) -> Optional[str]:
    """
    Get the role profile configured for a membership type.

    Args:
        membership_type: Name of the Membership Type

    Returns:
        Role profile name or None if not configured
    """
    if not membership_type:
        return None

    return frappe.db.get_value("Membership Type", membership_type, "role_profile")


def assign_membership_type_role_profile(user: str, membership_type: str) -> Dict:
    """
    Assign role profile to user based on their membership type.

    Args:
        user: User email/name
        membership_type: Name of the Membership Type

    Returns:
        dict with success status and message
    """
    if not user:
        return {"success": False, "message": _("No user specified")}

    if not membership_type:
        return {"success": False, "message": _("No membership type specified")}

    # Get the role profile for this membership type
    role_profile = get_role_profile_for_membership_type(membership_type)

    if not role_profile:
        frappe.logger().warning(
            f"[Membership Role Profile] No role profile configured for membership type: {membership_type}"
        )
        return {
            "success": False,
            "message": _("No role profile configured for membership type: {0}").format(membership_type),
        }

    # Check if role profile exists
    if not frappe.db.exists("Role Profile", role_profile):
        frappe.logger().error(f"[Membership Role Profile] Role profile does not exist: {role_profile}")
        return {"success": False, "message": _("Role profile does not exist: {0}").format(role_profile)}

    # Check if user exists and is enabled
    user_doc = frappe.db.get_value("User", user, ["name", "enabled"], as_dict=True)
    if not user_doc:
        return {"success": False, "message": _("User not found: {0}").format(user)}

    if not user_doc.enabled:
        frappe.logger().info(f"[Membership Role Profile] Skipping disabled user: {user}")
        return {"success": False, "message": _("User is disabled: {0}").format(user)}

    # Get current role profile
    current_profile = frappe.db.get_value("User", user, "role_profile_name")

    if current_profile == role_profile:
        frappe.logger().info(
            f"[Membership Role Profile] User {user} already has role profile: {role_profile}"
        )
        return {
            "success": True,
            "message": _("User already has role profile: {0}").format(role_profile),
            "already_assigned": True,
        }

    # Assign the role profile
    try:
        user_doc_full = frappe.get_doc("User", user)
        user_doc_full.role_profile_name = role_profile

        result = secure_document_operation(
            operation="save",
            doc=user_doc_full,
            justification=f"Assigning role profile {role_profile} for membership type {membership_type}",
            required_permissions=["User:write"],
        )

        if result.success:
            frappe.logger().info(
                f"[Membership Role Profile] Assigned role profile {role_profile} to user {user} "
                f"for membership type {membership_type}"
            )
            return {
                "success": True,
                "message": _("Role profile {0} assigned successfully").format(role_profile),
                "role_profile": role_profile,
                "previous_profile": current_profile,
            }
        else:
            return {
                "success": False,
                "message": _("Failed to assign role profile: {0}").format("; ".join(result.errors)),
            }

    except Exception as e:
        frappe.log_error(
            f"Error assigning role profile {role_profile} to user {user}: {str(e)}",
            "Membership Role Profile Error",
        )
        return {"success": False, "message": _("Error assigning role profile: {0}").format(str(e))}


def remove_membership_role_profile(user: str) -> Dict:
    """
    Remove membership-based role profile from user (on termination).

    This clears the user's role_profile_name field. In practice, this is called
    when a member terminates their membership entirely.

    Args:
        user: User email/name

    Returns:
        dict with success status and message
    """
    if not user:
        return {"success": False, "message": _("No user specified")}

    # Check if user exists
    if not frappe.db.exists("User", user):
        return {"success": False, "message": _("User not found: {0}").format(user)}

    # Get current role profile
    current_profile = frappe.db.get_value("User", user, "role_profile_name")

    if not current_profile:
        return {"success": True, "message": _("User has no role profile to remove"), "already_removed": True}

    # Remove the role profile
    try:
        user_doc = frappe.get_doc("User", user)
        user_doc.role_profile_name = None

        result = secure_document_operation(
            operation="save",
            doc=user_doc,
            justification="Removing role profile due to membership termination",
            required_permissions=["User:write"],
        )

        if result.success:
            frappe.logger().info(
                f"[Membership Role Profile] Removed role profile {current_profile} from user {user}"
            )
            return {
                "success": True,
                "message": _("Role profile removed successfully"),
                "previous_profile": current_profile,
            }
        else:
            return {
                "success": False,
                "message": _("Failed to remove role profile: {0}").format("; ".join(result.errors)),
            }

    except Exception as e:
        frappe.log_error(
            f"Error removing role profile from user {user}: {str(e)}", "Membership Role Profile Error"
        )
        return {"success": False, "message": _("Error removing role profile: {0}").format(str(e))}


def update_membership_type_role_profile(
    user: str, old_membership_type: str, new_membership_type: str
) -> Dict:
    """
    Update user's role profile when membership type changes.

    This is the main function called during membership type change amendments.
    It handles the transition from old to new role profile.

    Args:
        user: User email/name
        old_membership_type: Previous membership type name
        new_membership_type: New membership type name

    Returns:
        dict with success status, message, and profile change details
    """
    if not user:
        return {"success": False, "message": _("No user specified")}

    old_profile = get_role_profile_for_membership_type(old_membership_type) if old_membership_type else None
    new_profile = get_role_profile_for_membership_type(new_membership_type)

    if old_profile == new_profile:
        return {
            "success": True,
            "message": _("No role profile change needed"),
            "no_change": True,
            "role_profile": new_profile,
        }

    # Assign the new profile
    result = assign_membership_type_role_profile(user, new_membership_type)

    if result.get("success"):
        result["old_profile"] = old_profile
        result["new_profile"] = new_profile

    return result


def get_user_for_member(member_name: str) -> Optional[str]:
    """
    Get the user account linked to a member.

    Args:
        member_name: Name of the Member record

    Returns:
        User email/name or None if no user linked
    """
    if not member_name:
        return None

    return frappe.db.get_value("Member", member_name, "user")


def sync_member_role_profile(member_name: str) -> Dict:
    """
    Sync a member's role profile based on their current membership type.

    Convenience function that gets the member's user and current membership type,
    then assigns the appropriate role profile.

    Args:
        member_name: Name of the Member record

    Returns:
        dict with success status and message
    """
    if not member_name:
        return {"success": False, "message": _("No member specified")}

    member_data = frappe.db.get_value(
        "Member", member_name, ["user", "current_membership_type"], as_dict=True
    )

    if not member_data:
        return {"success": False, "message": _("Member not found: {0}").format(member_name)}

    if not member_data.user:
        return {"success": False, "message": _("Member has no user account linked"), "no_user": True}

    if not member_data.current_membership_type:
        return {
            "success": False,
            "message": _("Member has no current membership type"),
            "no_membership_type": True,
        }

    return assign_membership_type_role_profile(member_data.user, member_data.current_membership_type)
