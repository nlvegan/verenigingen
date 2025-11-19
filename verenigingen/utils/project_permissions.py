#!/usr/bin/env python3
"""
Project Permission System for Team-Based Access

This module provides team-based project access for volunteers, allowing
them to access projects that their teams are working on.
"""
import frappe
from frappe import _


def has_project_permission_via_team(doc, user, permission_type):
    """
    Check if user has project permission through team membership

    Args:
        doc: Project document or None for list access
        user: User email
        permission_type: 'read', 'write', 'create', 'delete', etc.

    Returns:
        bool: True if user has permission through team membership
    """
    if not doc:
        # For list view, check if user is a volunteer on any team
        return user_has_any_team_projects(user)

    # For specific project, check if user's teams are associated with this project
    return user_has_project_team_access(user, doc.name, permission_type)


def user_has_any_team_projects(user):
    """Check if user is a volunteer on any team that has projects"""
    try:
        # Get user's member record
        user_member = frappe.db.get_value("Member", {"user": user}, "name")
        if not user_member:
            return False

        # Get user's volunteer record
        volunteer = frappe.db.get_value("Volunteer", {"member": user_member}, "name")
        if not volunteer:
            return False

        # Check if volunteer is on any teams with projects
        teams_with_projects = frappe.db.sql(
            """
            SELECT DISTINCT tm.parent as team_name
            FROM `tabTeam Member` tm
            INNER JOIN `tabTeam` t ON tm.parent = t.name
            WHERE tm.volunteer = %s
            AND tm.status = 'Active'
            AND t.status = 'Active'
            AND EXISTS (
                SELECT 1 FROM `tabProject` p
                WHERE p.custom_team = t.name OR p.project_name LIKE CONCAT('%%', t.team_name, '%%')
            )
        """,
            (volunteer,),
        )

        return len(teams_with_projects) > 0

    except Exception as e:
        frappe.log_error(f"Error checking user team projects for {user}: {str(e)}")
        return False


def user_has_project_team_access(user, project_name, permission_type):
    """Check if user has access to specific project through team membership"""
    try:
        # Get user's member record
        user_member = frappe.db.get_value("Member", {"user": user}, "name")
        if not user_member:
            return False

        # Get user's volunteer record
        volunteer = frappe.db.get_value("Volunteer", {"member": user_member}, "name")
        if not volunteer:
            return False

        # Get project details
        project = frappe.get_doc("Project", project_name)

        # Check direct team assignment (if project has custom_team field)
        if hasattr(project, "custom_team") and project.custom_team:
            team_member = frappe.db.exists(
                "Team Member", {"parent": project.custom_team, "volunteer": volunteer, "status": "Active"}
            )
            if team_member:
                return get_team_permission_level(project.custom_team, volunteer, permission_type)

        # Check indirect team assignment (project name contains team name)
        user_teams = frappe.db.sql(
            """
            SELECT tm.parent as team_name, tr.role as team_role
            FROM `tabTeam Member` tm
            LEFT JOIN `tabTeam Role` tr ON tm.team_role = tr.name
            WHERE tm.volunteer = %s AND tm.status = 'Active'
        """,
            (volunteer,),
            as_dict=True,
        )

        for team in user_teams:
            if team.team_name.lower() in project.project_name.lower():
                return get_team_permission_level(team.team_name, volunteer, permission_type)

        return False

    except Exception as e:
        frappe.log_error(f"Error checking project team access for {user}, project {project_name}: {str(e)}")
        return False


def get_team_permission_level(team_name, volunteer, permission_type):
    """
    Determine permission level based on team role

    Team roles and their project permissions:
    - Team Leader: read, write, create (but not delete)
    - Core Member: read, write
    - Regular Member: read only
    - Coordinator: read, write, create
    """
    try:
        # Get volunteer's role in the team
        team_member = frappe.db.get_value(
            "Team Member",
            {"parent": team_name, "volunteer": volunteer},
            ["team_role", "role_type", "role", "notes"],
            as_dict=True,
        )

        if not team_member:
            return False

        # Get team role details
        if team_member.team_role:
            team_role = frappe.get_doc("Team Role", team_member.team_role)
            role_name = team_role.role_name
        else:
            role_name = "Regular Member"  # Default role

        # Permission mapping based on team role
        permission_matrix = {
            "Team Leader": ["read", "write", "create"],
            "Project Coordinator": ["read", "write", "create"],
            "Coordinator": ["read", "write", "create"],
            "Core Member": ["read", "write"],
            "Senior Member": ["read", "write"],
            "Regular Member": ["read"],
            "Volunteer": ["read"],
        }

        # Check if role has the requested permission
        allowed_permissions = permission_matrix.get(role_name, ["read"])  # Default to read-only
        return permission_type.lower() in allowed_permissions

    except Exception as e:
        frappe.log_error(
            f"Error getting team permission level for team {team_name}, volunteer {volunteer}: {str(e)}"
        )
        return False


@frappe.whitelist()
def get_user_project_teams(user=None):
    """Get all teams and their projects that a user has access to"""
    if not user:
        user = frappe.session.user

    try:
        # Get user's volunteer record
        user_member = frappe.db.get_value("Member", {"user": user}, "name")
        if not user_member:
            return {"teams": [], "projects": []}

        volunteer = frappe.db.get_value("Volunteer", {"member": user_member}, "name")
        if not volunteer:
            return {"teams": [], "projects": []}

        # Get user's teams
        user_teams = frappe.db.sql(
            """
            SELECT
                tm.parent as team_name,
                t.description,
                t.status,
                tm.team_role,
                tm.responsibility,
                tr.role_name
            FROM `tabTeam Member` tm
            INNER JOIN `tabTeam` t ON tm.parent = t.name
            LEFT JOIN `tabTeam Role` tr ON tm.team_role = tr.name
            WHERE tm.volunteer = %s AND tm.status = 'Active'
            ORDER BY t.team_name
        """,
            (volunteer,),
            as_dict=True,
        )

        # Get projects associated with these teams
        team_projects = []
        for team in user_teams:
            # Direct team assignment
            direct_projects = frappe.db.sql(
                """
                SELECT name, project_name, status, expected_end_date
                FROM `tabProject`
                WHERE custom_team = %s
            """,
                (team.team_name,),
                as_dict=True,
            )

            # Indirect assignment (project name contains team name)
            indirect_projects = frappe.db.sql(
                """
                SELECT name, project_name, status, expected_end_date
                FROM `tabProject`
                WHERE project_name LIKE %s
                AND (custom_team IS NULL OR custom_team != %s)
            """,
                (f"%{team.team_name}%", team.team_name),
                as_dict=True,
            )

            for project in direct_projects + indirect_projects:
                project["team_name"] = team.team_name
                project["access_type"] = "direct" if project in direct_projects else "indirect"
                project["permission_level"] = get_team_permission_level(team.team_name, volunteer, "write")
                team_projects.append(project)

        return {"teams": user_teams, "projects": team_projects, "volunteer_record": volunteer}

    except Exception as e:
        frappe.log_error(f"Error getting user project teams for {user}: {str(e)}")
        return {"teams": [], "projects": [], "error": str(e)}


def setup_project_team_permissions():
    """Setup custom permission handlers for Project DocType"""

    # Add custom permission for Project DocType
    permission_method = "verenigingen.utils.project_permissions.has_project_permission_via_team"

    # This would be added to hooks.py:
    """
    permission_query_conditions = {
        "Project": "verenigingen.utils.project_permissions.get_project_permission_query_conditions",
    }

    has_permission = {
        "Project": "verenigingen.utils.project_permissions.has_project_permission_via_team",
    }
    """

    return permission_method


def get_project_permission_query_conditions(user):
    """Generate query conditions for project list based on team membership"""
    if not user or user == "Guest":
        return "1=0"  # No access for guests

    # Admin users get full access
    user_roles = frappe.get_roles(user)
    admin_roles = ["System Manager", "Projects Manager", "Verenigingen Administrator"]
    if any(role in user_roles for role in admin_roles):
        return ""  # Full access

    # Check if user is a volunteer with team access
    try:
        user_member = frappe.db.get_value("Member", {"user": user}, "name")
        if not user_member:
            return "1=0"

        volunteer = frappe.db.get_value("Volunteer", {"member": user_member}, "name")
        if not volunteer:
            return "1=0"

        # Get user's active teams
        user_teams = frappe.db.sql(
            """
            SELECT tm.parent as team_name
            FROM `tabTeam Member` tm
            INNER JOIN `tabTeam` t ON tm.parent = t.name
            WHERE tm.volunteer = %s AND tm.status = 'Active' AND t.status = 'Active'
        """,
            (volunteer,),
            pluck=True,
        )

        if not user_teams:
            return "1=0"

        # Build conditions for projects accessible via teams
        team_conditions = []
        for team in user_teams:
            # Direct team assignment
            team_conditions.append(f"`tabProject`.custom_team = '{team}'")
            # Indirect assignment (project name contains team name)
            team_conditions.append(f"`tabProject`.project_name LIKE '%{team}%'")

        if team_conditions:
            return f"({' OR '.join(team_conditions)})"
        else:
            return "1=0"

    except Exception as e:
        frappe.log_error(f"Error generating project query conditions for {user}: {str(e)}")
        return "1=0"
