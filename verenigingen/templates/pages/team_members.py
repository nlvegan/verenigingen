"""
Team Members Portal Page
Shows team members for a specific team that the user has access to
"""

from typing import Any, Dict, Optional

import frappe
from frappe import _
from frappe.utils import format_date

from verenigingen.utils.constants import get_volunteer_admin_roles
from verenigingen.utils.error_handling import (
    validate_entity_exists,
    validate_member_for_user,
    validate_user_logged_in,
)


def get_context(context: Dict[str, Any]) -> Dict[str, Any]:
    """Get context for team members page"""

    # Modernized validation with helpers
    user = validate_user_logged_in()
    team_name = validate_entity_exists("Team", frappe.form_dict.get("team"))
    member = validate_member_for_user(user)

    context.no_cache = 1
    context.title = _("Team Members")
    context.team = frappe.get_doc("Team", team_name)

    volunteer = frappe.db.get_value("Volunteer", {"member": member}, "name")

    # Allow members to view team information even if they're not volunteers yet
    # This is important for members who want to explore volunteering opportunities

    # Security check: Only allow team members or admins to view team members
    # Modernized with centralized role constants
    admin_roles = get_volunteer_admin_roles()
    user_roles = frappe.get_roles(user)
    is_admin = any(role in user_roles for role in admin_roles)

    if not is_admin:
        # Check if user is a member of this team (only if they have a volunteer record)
        is_team_member = False
        if volunteer:
            is_team_member = frappe.db.exists(
                "Team Member", {"parent": team_name, "volunteer": volunteer, "is_active": 1}
            )

        # Also check if member has chapter membership that relates to this team
        if not is_team_member:
            # Allow if member belongs to the same chapter as the team
            team_doc = frappe.get_doc("Team", team_name)
            if team_doc.chapter:
                member_in_chapter = frappe.db.exists(
                    "Chapter Member", {"parent": team_doc.chapter, "member": member, "enabled": 1}
                )
                is_team_member = bool(member_in_chapter)

        if not is_team_member:
            frappe.throw(
                _("You can only view members of teams where you are a member or belong to the same chapter"),
                frappe.PermissionError,
            )

    # Get team members - modernized ORM approach with batch queries
    # First get team member records
    team_member_records = frappe.get_all(
        "Team Member",
        filters={"parent": team_name, "is_active": 1},
        fields=["volunteer", "volunteer_name", "role_type", "role", "from_date", "to_date", "status"],
        order_by="role_type DESC, from_date ASC",
    )

    # Extract volunteer IDs for batch fetching
    volunteer_ids = [tm.volunteer for tm in team_member_records if tm.volunteer]

    # Batch fetch volunteer and member data
    volunteer_data = {}
    member_data = {}

    if volunteer_ids:
        # Get volunteer email addresses
        volunteers = frappe.get_all(
            "Volunteer", filters={"name": ["in", volunteer_ids]}, fields=["name", "email", "member"]
        )
        volunteer_data = {v.name: v for v in volunteers}

        # Get member details
        member_ids = [v.member for v in volunteers if v.member]
        if member_ids:
            members = frappe.get_all(
                "Member",
                filters={"name": ["in", member_ids]},
                fields=["name", "first_name", "last_name", "member_id"],
            )
            member_data = {m.name: m for m in members}

    # Combine all data
    team_members = []
    for tm in team_member_records:
        volunteer_info = volunteer_data.get(tm.volunteer, frappe._dict())
        member_info = member_data.get(volunteer_info.get("member"), frappe._dict())

        combined = frappe._dict(
            {
                **tm.as_dict(),
                "email": volunteer_info.get("email"),
                "first_name": member_info.get("first_name"),
                "last_name": member_info.get("last_name"),
                "member_id": member_info.get("member_id"),
            }
        )
        team_members.append(combined)

    # Format the data for display
    for member in team_members:
        if member.from_date:
            member.formatted_from_date = format_date(member.from_date)
        if member.to_date:
            member.formatted_to_date = format_date(member.to_date)

        # Create display name (Team Member has volunteer_name fetched from Volunteer)
        member.display_name = member.volunteer_name or "Unknown"

    context.team_members = team_members
    context.current_user_volunteer = volunteer

    return context


def has_website_permission(doc: Any, ptype: str, user: str, verbose: bool = False) -> bool:
    """Check website permission for team members page"""
    # Only logged-in users can access
    if user == "Guest":
        return False

    # Check if user has a member record
    member = frappe.db.get_value("Member", {"user": user})
    return bool(member)
