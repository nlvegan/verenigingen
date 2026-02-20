"""
Team Administration Utilities

This module provides administrative utilities for team management,
separated from core business logic and API endpoints.
"""

import frappe
from frappe import _

from verenigingen.utils.constants import Roles
from verenigingen.utils.error_handling import handle_api_error
from verenigingen.utils.security.api_security_framework import OperationType, critical_api
from verenigingen.utils.validation.api_validators import require_roles


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)  # Fixed: ADMIN not ADMINISTRATIVE
@handle_api_error
@require_roles(list(Roles.ADMIN_PAIR))
def fix_all_missing_assignment_history():
    """Fix missing assignment history for all teams - admin utility function"""

    teams_fixed = 0
    volunteers_fixed = 0

    # Get all teams with active members - use pagination for large datasets
    teams = frappe.get_all("Team", fields=["name"], limit_page_length=100)

    for team_data in teams:
        team = frappe.get_doc("Team", team_data.name)

        for member in team.team_members:
            if member.is_active and member.volunteer:
                # Check if assignment history exists
                history_exists = frappe.db.exists(
                    "Assignment History",
                    {
                        "volunteer": member.volunteer,
                        "reference_doctype": "Team",
                        "reference_name": team.name,
                        "status": "Active",
                    },
                )

                if not history_exists:
                    # Import here to avoid circular imports
                    from verenigingen.services.team_service import TeamService

                    success = TeamService().add_assignment_history(
                        team_doc=team,
                        volunteer_id=member.volunteer,
                        team_role=member.team_role or member.role or "Team Member",
                        start_date=member.from_date or frappe.utils.today(),
                    )

                    if success:
                        volunteers_fixed += 1
                        frappe.logger().info(
                            f"✅ Fixed assignment history for {member.volunteer_name} in {team.name}"
                        )
                    else:
                        frappe.logger().error(
                            f"❌ Failed to fix assignment history for {member.volunteer_name} in {team.name}"
                        )

        if volunteers_fixed > 0:
            teams_fixed += 1

    return {
        "success": True,
        "message": f"Fixed assignment history for {volunteers_fixed} volunteers across {teams_fixed} teams",
        "teams_fixed": teams_fixed,
        "volunteers_fixed": volunteers_fixed,
    }


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
@handle_api_error
@require_roles(list(Roles.ADMIN_PAIR))
def fix_missing_assignment_history(team_name=None, volunteer_name=None):
    """Fix missing team assignment history for existing assignments"""

    if not team_name or not volunteer_name:
        frappe.throw(_("Both team_name and volunteer_name are required"))

    # Validate inputs exist using DocumentExistenceValidator
    from verenigingen.utils.validation_utilities import validate_document_exists

    validate_document_exists("Team", team_name)
    validate_document_exists("Volunteer", volunteer_name)

    team = frappe.get_doc("Team", team_name)

    for member in team.team_members:
        if member.volunteer == volunteer_name and member.is_active:
            frappe.logger().info(f"Found active assignment: {member.volunteer} -> {member.role}")

            # Check if assignment history already exists
            history_exists = frappe.db.exists(
                "Assignment History",
                {
                    "volunteer": volunteer_name,
                    "reference_doctype": "Team",
                    "reference_name": team_name,
                    "status": "Active",
                },
            )

            if not history_exists:
                from verenigingen.services.team_service import TeamService

                success = TeamService().add_assignment_history(
                    team_doc=team,
                    volunteer_id=volunteer_name,
                    team_role=member.team_role or member.role or "Team Member",
                    start_date=member.from_date or frappe.utils.today(),
                )

                if success:
                    frappe.logger().info(f"✅ Successfully added assignment history for {volunteer_name}")
                    return {"success": True, "message": "Assignment history added successfully"}
                else:
                    frappe.logger().error(f"❌ Failed to add assignment history for {volunteer_name}")
                    return {"success": False, "error": "Failed to add assignment history"}
            else:
                return {"success": True, "message": "Assignment history already exists"}

    return {"success": False, "error": "No matching active assignment found"}


@frappe.whitelist()
@critical_api(operation_type=OperationType.UTILITY)
@handle_api_error
@require_roles(list(Roles.ADMIN_PAIR))
def debug_team_assignments():
    """Debug team assignments and volunteers - diagnostic utility"""

    result = {}

    # Get teams with pagination
    teams = frappe.get_all("Team", fields=["name", "team_name"], limit_page_length=50)
    result["teams"] = []

    for team in teams:
        team_doc = frappe.get_doc("Team", team.name)
        team_info = {"name": team.name, "team_name": team.team_name, "members": []}

        for member in team_doc.team_members:
            team_info["members"].append(
                {
                    "volunteer": member.volunteer,
                    "volunteer_name": member.volunteer_name,
                    "role": member.role,
                    "team_role": member.team_role,
                    "is_active": member.is_active,
                    "from_date": str(member.from_date) if member.from_date else None,
                }
            )

        result["teams"].append(team_info)

    # Get specific volunteers for debugging
    volunteers = frappe.get_all(
        "Volunteer",
        filters={"volunteer_name": ["like", "%Test%"]},  # Changed from Foppe for privacy
        fields=["name", "volunteer_name"],
        limit_page_length=20,
    )

    result["debug_volunteers"] = []
    for vol in volunteers:
        volunteer_doc = frappe.get_doc("Volunteer", vol.name)
        vol_info = {"name": vol.name, "volunteer_name": vol.volunteer_name, "assignment_history": []}

        for assignment in volunteer_doc.assignment_history or []:
            vol_info["assignment_history"].append(
                {
                    "assignment_type": assignment.assignment_type,
                    "reference_doctype": assignment.reference_doctype,
                    "reference_name": assignment.reference_name,
                    "role": assignment.role,
                    "status": assignment.status,
                    "start_date": str(assignment.start_date) if assignment.start_date else None,
                    "end_date": str(assignment.end_date) if assignment.end_date else None,
                }
            )

        result["debug_volunteers"].append(vol_info)

    return result


@frappe.whitelist()
@critical_api(operation_type=OperationType.UTILITY)
@handle_api_error
@require_roles(list(Roles.ADMIN_PAIR))
def validate_team_data_integrity():
    """Validate team data integrity - comprehensive diagnostic tool"""

    issues = []
    stats = {
        "teams_checked": 0,
        "members_checked": 0,
        "missing_history": 0,
        "orphaned_members": 0,
        "invalid_roles": 0,
    }

    teams = frappe.get_all("Team", fields=["name"], limit_page_length=100)

    for team_data in teams:
        stats["teams_checked"] += 1
        team = frappe.get_doc("Team", team_data.name)

        for member in team.team_members:
            stats["members_checked"] += 1

            # Check if volunteer exists using DocumentExistenceValidator
            from verenigingen.utils.validation_utilities import DocumentExistenceValidator

            if member.volunteer and not DocumentExistenceValidator.validate_document_exists(
                "Volunteer", member.volunteer, throw_on_error=False
            ):
                issues.append(
                    {
                        "type": "orphaned_member",
                        "team": team.name,
                        "volunteer": member.volunteer,
                        "message": f"Team member references non-existent volunteer: {member.volunteer}",
                    }
                )
                stats["orphaned_members"] += 1
                continue

            # Check if team role exists using DocumentExistenceValidator
            if member.team_role and not DocumentExistenceValidator.validate_document_exists(
                "Team Role", member.team_role, throw_on_error=False
            ):
                issues.append(
                    {
                        "type": "invalid_role",
                        "team": team.name,
                        "volunteer": member.volunteer,
                        "role": member.team_role,
                        "message": f"Team member has invalid team role: {member.team_role}",
                    }
                )
                stats["invalid_roles"] += 1

            # Check for missing assignment history
            if member.is_active and member.volunteer:
                history_exists = frappe.db.exists(
                    "Assignment History",
                    {
                        "volunteer": member.volunteer,
                        "reference_doctype": "Team",
                        "reference_name": team.name,
                        "status": "Active",
                    },
                )

                if not history_exists:
                    issues.append(
                        {
                            "type": "missing_history",
                            "team": team.name,
                            "volunteer": member.volunteer,
                            "volunteer_name": member.volunteer_name,
                            "message": "Active team member missing assignment history",
                        }
                    )
                    stats["missing_history"] += 1

    return {
        "success": True,
        "stats": stats,
        "issues": issues,
        "summary": f"Found {len(issues)} issues across {stats['teams_checked']} teams",
    }
