"""
Team Management API

This module provides API endpoints for team management operations,
extracted from the Team DocType controller to maintain proper separation of concerns.
"""

import frappe
from frappe import _

from verenigingen.utils.error_handling import handle_api_error
from verenigingen.utils.security.api_security_framework import standard_api
from verenigingen.utils.validation.api_validators import validate_api_input


@frappe.whitelist()
@standard_api
@handle_api_error
def get_team_members(team):
    """Get team members with volunteer info"""
    if not team:
        frappe.throw(_("Team is required"))

    if not frappe.has_permission("Team", "read", team):
        frappe.throw(_("Insufficient permissions to access team data"))

    team_doc = frappe.get_doc("Team", team)
    members = []

    for member in team_doc.team_members:
        member_data = {
            "volunteer": member.volunteer,
            "volunteer_name": member.volunteer_name,
            "role": member.role,
            "team_role": member.team_role,
            "is_active": member.is_active,
            "from_date": member.from_date,
            "to_date": member.to_date,
        }

        if member.volunteer:
            try:
                volunteer_doc = frappe.get_doc("Volunteer", member.volunteer)
                member_data.update(
                    {
                        "email": volunteer_doc.email,
                        "phone": None,  # Phone field not available in Volunteer DocType
                        "skills": (
                            [skill.skill for skill in volunteer_doc.skills]
                            if hasattr(volunteer_doc, "skills")
                            else []
                        ),
                    }
                )
            except frappe.DoesNotExistError:
                pass

        members.append(member_data)

    return members


@frappe.whitelist()
@standard_api
@handle_api_error
@validate_api_input
def sync_team_with_volunteers(team_name=None):
    """Sync team members with volunteer system"""

    # Permission check
    if not frappe.has_permission("Team", "write"):
        frappe.throw(_("Insufficient permissions to sync teams"))

    teams_to_sync = []
    if team_name:
        if not frappe.has_permission("Team", "write", team_name):
            frappe.throw(_("Insufficient permissions to sync team {0}").format(team_name))
        teams_to_sync = [{"name": team_name}]
    else:
        teams_to_sync = frappe.get_all("Team", fields=["name"])

    updated_count = 0

    for team in teams_to_sync:
        try:
            team_doc = frappe.get_doc("Team", team["name"])
            # Import here to avoid circular imports
            from verenigingen.services.team_service import TeamService

            TeamService().sync_with_volunteers(team_doc)
            updated_count += 1
        except Exception as e:
            frappe.log_error(f"Failed to sync team {team['name']}: {str(e)}", "Team Sync Error")

    return {"updated_count": updated_count}


@frappe.whitelist()
@standard_api
@handle_api_error
def get_role_profile_preview(team_name):
    """Get preview of which role profiles would be assigned to team members"""

    if not frappe.has_permission("Team", "read", team_name):
        frappe.throw(_("Insufficient permissions to access team data"))

    team_doc = frappe.get_doc("Team", team_name)
    preview = []

    for member in team_doc.team_members:
        if member.is_active and member.volunteer:
            role_profile = None

            # Get role profile from team role configuration
            if member.team_role and team_doc.role_specific_profiles:
                for mapping in team_doc.role_specific_profiles:
                    if mapping.team_role == member.team_role:
                        role_profile = mapping.role_profile
                        break

            preview.append(
                {
                    "volunteer": member.volunteer,
                    "volunteer_name": member.volunteer_name,
                    "team_role": member.team_role,
                    "current_role_profile": role_profile,
                    "would_be_assigned": role_profile is not None,
                }
            )

    return preview


@frappe.whitelist()
@standard_api
@handle_api_error
def bulk_apply_team_role_profiles(team_name):
    """Apply role profiles to all current team members based on team configuration"""

    if not frappe.has_permission("Team", "write", team_name):
        frappe.throw(_("Insufficient permissions to modify team"))

    team_doc = frappe.get_doc("Team", team_name)
    applied_count = 0

    for member in team_doc.team_members:
        if member.is_active and member.volunteer and member.team_role:
            # Find matching role profile
            role_profile = None
            if team_doc.role_profile_mapping:
                for mapping in team_doc.role_profile_mapping:
                    if mapping.team_role == member.team_role:
                        role_profile = mapping.role_profile
                        break

            if role_profile:
                try:
                    # Apply role profile to volunteer
                    volunteer_doc = frappe.get_doc("Volunteer", member.volunteer)
                    volunteer_doc.role_profile = role_profile
                    volunteer_doc.save()
                    applied_count += 1
                except Exception as e:
                    frappe.log_error(f"Failed to apply role profile to {member.volunteer_name}: {str(e)}")

    return {
        "success": True,
        "applied_count": applied_count,
        "message": f"Applied role profiles to {applied_count} team members",
    }
