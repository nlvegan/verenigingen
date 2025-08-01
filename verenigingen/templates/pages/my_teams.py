"""
My Teams Page
Shows user's team memberships and provides access to team member reports
"""

from typing import Any, Dict

import frappe
from frappe import _

from verenigingen.utils.constants import Membership
from verenigingen.utils.error_handling import validate_member_for_user, validate_user_logged_in


def get_context(context: Dict[str, Any]) -> Dict[str, Any]:
    """Get context for my teams page"""

    # Modernized validation with helpers
    user = validate_user_logged_in()
    member = validate_member_for_user(user)

    # Ensure context is a frappe._dict for attribute access
    if not hasattr(context, "no_cache"):
        context = frappe._dict(context)

    context.no_cache = 1
    context.title = _("My Teams")

    # Get volunteer record
    volunteer = frappe.db.get_value("Volunteer", {"member": member})
    if not volunteer:
        context.teams = []
        context.volunteer = None
        return context

    context.volunteer = volunteer

    # Get user's teams with detailed information - modernized ORM approach
    # First get active team memberships for the volunteer
    team_memberships = frappe.get_all(
        "Team Member",
        filters={"volunteer": volunteer, "is_active": 1},
        fields=[
            "parent as team_name",
            "role_type",
            "role",
            "status as member_status",
            "from_date",
            "to_date",
            "is_active",
        ],
        order_by="from_date DESC",
    )

    # Extract unique team names for batch fetching
    team_names = list(set(tm.team_name for tm in team_memberships))

    # Batch fetch team details to avoid N+1 queries
    teams_data = {}
    if team_names:
        teams_info = frappe.get_all(
            "Team",
            filters={"name": ["in", team_names], "status": Membership.STATUS_ACTIVE},
            fields=["name", "team_name", "team_type", "description", "status"],
        )
        teams_data = {team.name: team for team in teams_info}

    # Combine team info with membership data
    teams = []
    for membership in team_memberships:
        team_info = teams_data.get(membership.team_name)
        if team_info:  # Only include teams that are active
            # Both team_info and membership are already dictionaries from frappe.get_all()
            # Convert membership to dict if it has as_dict method, otherwise use as-is
            membership_dict = (
                membership.as_dict()
                if hasattr(membership, "as_dict") and callable(getattr(membership, "as_dict"))
                else dict(membership)
            )
            team_info_dict = (
                team_info.as_dict()
                if hasattr(team_info, "as_dict") and callable(getattr(team_info, "as_dict"))
                else dict(team_info)
            )

            combined_data = {
                **team_info_dict,
                **membership_dict,
                "team_status": team_info.get("status", "Active"),
            }
            teams.append(frappe._dict(combined_data))

    # Group teams and get additional info
    teams_dict = {}
    for team in teams:
        team_name = team.name
        if team_name not in teams_dict:
            teams_dict[team_name] = {"info": team, "roles": [], "can_view_members": False}

        teams_dict[team_name]["roles"].append(
            {
                "role_type": team.role_type,
                "role": team.role,
                "from_date": team.from_date,
                "to_date": team.to_date,
                "is_active": team.is_active,
            }
        )

        # Check if user can view team members (any team member can view other members)
        # This is now controlled by the permission system in permissions.py
        teams_dict[team_name]["can_view_members"] = True

    # Convert to list for template
    context.teams = list(teams_dict.values())

    return context


def has_website_permission(doc: Any, ptype: str, user: str, verbose: bool = False) -> bool:
    """Check website permission for my teams page"""
    # Only logged-in users can access
    if user == "Guest":
        return False

    # Check if user has a member record
    member = frappe.db.get_value("Member", {"email": user})
    return bool(member)
