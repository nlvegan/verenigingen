"""
Team Role Profile Manager

Automatically assigns role profiles when users join/leave teams based on team configuration.
This implementation uses the BaseRoleProfileManager for shared functionality.

Business Rules:
- When a user joins a team, they get the team's associated role profile
- When a user leaves a team, their role profile is removed (if no other teams require it)
- Multiple teams can share the same role profile
- Users can have multiple role profiles from different teams

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

# Team-specific configuration
TEAM_CONFIG = EntityConfig(
    entity_type="team",
    entity_label="Team",
    doctype="Team",
    member_doctype="Team Member",
    role_doctype="Team Role",
    default_profile_field="default_role_profile",
    enable_specific_field="enable_role_specific_profiles",
    specific_profiles_field="role_specific_profiles",
    child_table_doctype="Team Role Profile Assignment",
    role_field_in_child="team_role",
    member_enabled_field=None,
    member_status_field="status",
    member_status_active_value="Active",
    member_role_field="team_role",
    log_context="Team Role Profile Manager",
)


class TeamRoleProfileManager(BaseRoleProfileManager):
    """Team-specific implementation of role profile management"""

    def __init__(self):
        """Initialize with team configuration"""
        super().__init__(TEAM_CONFIG)

    def _user_still_in_other_entities(self, user: str, other_entities: List[str]) -> bool:
        """Check if user is still active in other teams"""
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
                        "parent": ["in", other_entities],
                        "status": "Active",
                    },
                )
                return bool(still_in_other_teams)

        return False

    def _get_bulk_members_data(self, entity_name: str) -> List[Dict]:
        """Get team members data for bulk operations"""
        TM = DocType("Team Member")
        Volunteer = DocType("Volunteer")
        Member = DocType("Member")
        User = DocType("User")

        return (
            frappe.qb.from_(TM)
            .left_join(Volunteer)
            .on(TM.volunteer == Volunteer.name)
            .left_join(Member)
            .on(Volunteer.member == Member.name)
            .left_join(User)
            .on(Member.user == User.name)
            .select(
                TM.volunteer, TM.team_role, Volunteer.member, Member.user, User.enabled.as_("user_enabled")
            )
            .where(
                (TM.parent == entity_name)
                & (TM.status == "Active")
                & (Member.user.isnotnull())
                & (User.enabled == 1)
            )
        ).run(as_dict=True)

    def _get_user_from_team_member_doc(self, doc: "frappe._dict") -> Optional[str]:
        """Extract user from team member document

        Args:
            doc: TeamMember document with volunteer and team_role fields
        """
        # Team members only have volunteer field
        if doc.get("volunteer"):
            member = frappe.db.get_value("Volunteer", doc.volunteer, "member")  # ast-skip: doc is TeamMember
            if member:
                return frappe.db.get_value("Member", member, "user")
        return None


# Global instance for convenience
_team_manager = TeamRoleProfileManager()


# Public API Functions (maintain backward compatibility)
def get_team_role_profile_config(team_name):
    """
    Get role profile configuration for a team from database.

    Returns:
        dict: Configuration with default_profile and role_specific_profiles
    """
    return _team_manager.get_entity_role_profile_config(team_name)


def determine_role_profile_for_team_member(team_name, team_role=None):
    """
    Determine which role profile should be assigned to a team member.

    Args:
        team_name: Name of the team
        team_role: Specific team role (optional)

    Returns:
        str: Role profile name or None
    """
    return _team_manager.determine_role_profile_for_member(team_name, team_role)


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
    return _team_manager.assign_role_profile(user, team_name, team_role)


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
    return _team_manager.remove_role_profile(user, team_name, team_role)


@frappe.whitelist()
def bulk_assign_team_role_profiles(team_name):
    """
    Bulk assign role profiles to all existing members of a team
    Useful for initial setup or fixing missing assignments
    """
    return _team_manager.bulk_assign_role_profiles(team_name)


@frappe.whitelist()
def get_team_role_profile_mapping():
    """Get the current team to role profile mapping for admin reference"""
    mapping = {}

    # Get configured team mappings only
    teams = frappe.get_all(
        "Team", filters={"default_role_profile": ["is", "set"]}, fields=["name", "default_role_profile"]
    )

    for team in teams:
        if team.default_role_profile:
            mapping[team.name] = team.default_role_profile

    return mapping


def get_teams_requiring_role_profile(role_profile, exclude_team=None):
    """
    Get list of teams that require a specific role profile.

    Args:
        role_profile: Role profile name to search for
        exclude_team: Team to exclude from results

    Returns:
        list: Team names that require this role profile
    """
    return _team_manager.get_entities_requiring_role_profile(role_profile, exclude_team)


def get_teams_for_role_profile(role_profile):
    """
    Get all teams that are configured to use a specific role profile.

    Args:
        role_profile: Role profile name to search for

    Returns:
        List of dicts with team info: [{"name": team_name, "entity_label": team_name, "usage_type": type}]
    """
    return _team_manager.get_entities_using_role_profile(role_profile)


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


# Hook functions for Team Member document events
def on_team_member_add(doc: "frappe._dict", method: str):
    """Hook called when Team Member is added

    Args:
        doc: TeamMember document with volunteer, parent, and team_role fields
        method: Hook method name
    """
    if doc.status == "Active":
        user = _team_manager._get_user_from_team_member_doc(doc)
        if user:

            def assign_role():
                return assign_team_role_profile(
                    user, doc.parent, doc.team_role  # ast-skip: doc is TeamMember
                )

            result = safe_hook_execution(assign_role)
            if result and not result.get("success"):
                frappe.logger().warning(f"Failed to assign team role profile: {result.get('error')}")


def on_team_member_remove(doc: "frappe._dict", method: str):
    """Hook called when Team Member is removed

    Args:
        doc: TeamMember document with volunteer, parent, and team_role fields
        method: Hook method name
    """
    user = _team_manager._get_user_from_team_member_doc(doc)
    if user:

        def remove_role():
            return remove_team_role_profile(user, doc.parent, doc.team_role)  # ast-skip: doc is TeamMember

        result = safe_hook_execution(remove_role)
        if result and not result.get("success"):
            frappe.logger().warning(f"Failed to remove team role profile: {result.get('error')}")


def on_team_member_update(doc: "frappe._dict", method: str):
    """Hook called when Team Member is updated

    Args:
        doc: TeamMember document with volunteer, parent, and team_role fields
        method: Hook method name
    """
    # Handle status changes (active -> inactive, etc.)
    if doc.has_value_changed("status"):
        user = _team_manager._get_user_from_team_member_doc(doc)
        if user:
            if doc.status == "Active":

                def assign_role():
                    return assign_team_role_profile(
                        user, doc.parent, doc.team_role  # ast-skip: doc is TeamMember
                    )

                safe_hook_execution(assign_role)
            else:

                def remove_role():
                    return remove_team_role_profile(
                        user, doc.parent, doc.team_role  # ast-skip: doc is TeamMember
                    )

                safe_hook_execution(remove_role)


# For backward compatibility - maintain the old validation function
def _validate_role_assignment_inputs(user, entity_name, role, entity_type):
    """Legacy validation function for backward compatibility"""
    return _team_manager._validate_role_assignment_inputs(user, entity_name, role)
