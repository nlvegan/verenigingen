"""
Team Role Profile Manager

Automatically assigns role profiles when users join/leave teams based on team configuration.
This provides a reusable, maintainable way to manage team-based role assignments.

Business Rules:
- When a user joins a team, they get the team's associated role profile
- When a user leaves a team, their role profile is removed (if no other teams require it)
- Multiple teams can share the same role profile
- Users can have multiple role profiles from different teams

Author: Verenigingen Development Team
Last Updated: 2025-08-24
"""

from typing import Dict, List, Optional

import frappe
from frappe import _

# Team to Role Profile Mapping
TEAM_ROLE_PROFILE_MAPPING = {
    "Kascommissie": "Verenigingen Auditor",
    # Add more teams as needed:
    # "Communications Team": "Verenigingen Communications Manager",
    # "Finance Team": "Verenigingen Treasurer",
    # "Board": "Verenigingen Board Member",
}


@frappe.whitelist()
def assign_team_role_profile(user, team_name, team_role=None):
    """
    Assign role profile when user joins a team

    Args:
        user: User email/name
        team_name: Name of the team they're joining
        team_role: Team role (optional, for logging)

    Returns:
        dict: Success/failure result
    """
    try:
        role_profile = TEAM_ROLE_PROFILE_MAPPING.get(team_name)
        if not role_profile:
            # No automatic role profile for this team
            return {"success": True, "message": f"No automatic role profile for team {team_name}"}

        # Check if role profile exists
        if not frappe.db.exists("Role Profile", role_profile):
            frappe.logger().warning(f"Role Profile {role_profile} does not exist for team {team_name}")
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
                f"Team Role Profile Manager: Assigned '{role_profile}' to user {user} "
                f"for team {team_name} (team role: {team_role or 'N/A'})"
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
        error_msg = f"Error assigning role profile for team {team_name}: {str(e)}"
        frappe.log_error(frappe.get_traceback(), "Team Role Profile Assignment Error")
        return {"success": False, "error": error_msg}


@frappe.whitelist()
def remove_team_role_profile(user, team_name, team_role=None):
    """
    Remove role profile when user leaves a team

    Args:
        user: User email/name
        team_name: Name of the team they're leaving
        team_role: Team role (optional, for logging)

    Returns:
        dict: Success/failure result
    """
    try:
        role_profile = TEAM_ROLE_PROFILE_MAPPING.get(team_name)
        if not role_profile:
            # No automatic role profile for this team
            return {"success": True, "message": f"No automatic role profile for team {team_name}"}

        # Check if user still belongs to other teams that require this role profile
        other_teams_with_same_profile = [
            team
            for team, profile in TEAM_ROLE_PROFILE_MAPPING.items()
            if profile == role_profile and team != team_name
        ]

        if other_teams_with_same_profile:
            # Check if user is still in any of those teams
            user_member = frappe.db.get_value("Member", {"user": user}, "name")
            if user_member:
                # Get user's volunteer record
                volunteer = frappe.db.get_value("Volunteer", {"member": user_member}, "name")
                if volunteer:
                    still_in_other_teams = frappe.db.exists(
                        "Team Member",
                        {
                            "volunteer": volunteer,
                            "parent": ["in", other_teams_with_same_profile],
                            "status": "Active",
                        },
                    )

                    if still_in_other_teams:
                        return {
                            "success": True,
                            "message": f"User still in other teams requiring '{role_profile}', keeping role profile",
                            "action": "kept",
                        }

        # Safe to remove role profile
        user_doc = frappe.get_doc("User", user)
        if user_doc.role_profile_name == role_profile:
            previous_role_profile = user_doc.role_profile_name
            user_doc.role_profile_name = None  # or set to default member profile
            user_doc.save(ignore_permissions=True)  # System operation

            frappe.logger().info(
                f"Team Role Profile Manager: Removed '{role_profile}' from user {user} "
                f"for team {team_name} (team role: {team_role or 'N/A'})"
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
        error_msg = f"Error removing role profile for team {team_name}: {str(e)}"
        frappe.log_error(frappe.get_traceback(), "Team Role Profile Removal Error")
        return {"success": False, "error": error_msg}


def setup_team_hooks():
    """
    Setup hooks to automatically call role profile assignment/removal
    This should be called from hooks.py
    """
    # Hook into Team Member creation/update
    # This would be configured in hooks.py as:
    # doc_events = {
    #     "Team Member": {
    #         "after_insert": "verenigingen.utils.team_role_profile_manager.on_team_member_add",
    #         "before_delete": "verenigingen.utils.team_role_profile_manager.on_team_member_remove",
    #         "on_update": "verenigingen.utils.team_role_profile_manager.on_team_member_update"
    #     }
    # }
    pass


def on_team_member_add(doc, method):
    """Hook called when Team Member is added"""
    if doc.status == "Active" and doc.volunteer:
        # Get user from volunteer -> member -> user
        member = frappe.db.get_value("Volunteer", doc.volunteer, "member")
        if member:
            user = frappe.db.get_value("Member", member, "user")
            if user:
                result = assign_team_role_profile(user, doc.parent, doc.team_role)
                if not result.get("success"):
                    frappe.logger().warning(f"Failed to assign role profile: {result.get('error')}")


def on_team_member_remove(doc, method):
    """Hook called when Team Member is removed"""
    if doc.volunteer:
        # Get user from volunteer -> member -> user
        member = frappe.db.get_value("Volunteer", doc.volunteer, "member")
        if member:
            user = frappe.db.get_value("Member", member, "user")
            if user:
                result = remove_team_role_profile(user, doc.parent, doc.team_role)
                if not result.get("success"):
                    frappe.logger().warning(f"Failed to remove role profile: {result.get('error')}")


def on_team_member_update(doc, method):
    """Hook called when Team Member is updated"""
    # Handle status changes (active -> inactive, etc.)
    if doc.has_value_changed("status"):
        member = frappe.db.get_value("Volunteer", doc.volunteer, "member")
        if member:
            user = frappe.db.get_value("Member", member, "user")
            if user:
                if doc.status == "Active":
                    assign_team_role_profile(user, doc.parent, doc.team_role)
                else:
                    remove_team_role_profile(user, doc.parent, doc.team_role)


@frappe.whitelist()
def get_team_role_profile_mapping():
    """Get the current team to role profile mapping for admin reference"""
    return TEAM_ROLE_PROFILE_MAPPING


@frappe.whitelist()
def bulk_assign_team_role_profiles(team_name):
    """
    Bulk assign role profiles to all existing members of a team
    Useful for initial setup or fixing missing assignments
    """
    try:
        role_profile = TEAM_ROLE_PROFILE_MAPPING.get(team_name)
        if not role_profile:
            return {"success": False, "error": f"No role profile mapping for team {team_name}"}

        # Get all active team members
        team_members = frappe.get_all(
            "Team Member",
            filters={"parent": team_name, "status": "Active"},
            fields=["volunteer", "team_role"],
        )

        results = []
        for tm in team_members:
            if tm.volunteer:
                member = frappe.db.get_value("Volunteer", tm.volunteer, "member")
                if member:
                    user = frappe.db.get_value("Member", member, "user")
                    if user:
                        result = assign_team_role_profile(user, team_name, tm.team_role)
                        results.append({"user": user, "volunteer": tm.volunteer, "result": result})

        return {"success": True, "message": f"Processed {len(results)} team members", "results": results}

    except Exception as e:
        return {"success": False, "error": str(e)}
