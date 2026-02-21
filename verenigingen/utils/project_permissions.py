#!/usr/bin/env python3
"""
Project Permission System for Team and Chapter-Based Access

This module provides team-based and chapter board-based project access for volunteers,
allowing them to access projects that their teams or chapters are working on.

Team Access:
- Team members get access based on their team role
- Team Leaders/Coordinators: read, write, create
- Core/Senior Members: read, write
- Regular Members: read only

Chapter Board Access:
- Chapter board members get access based on their board role and permissions level
- Admin level: read, write, create, delete
- Financial level: read, write, create
- Basic level: read, write
- Chapter Chair (any level): read, write, create

Projects can be linked to teams/chapters either:
1. Directly via custom_team or custom_chapter fields
2. Indirectly via name matching (project name contains team/chapter name)
"""
import re
from functools import lru_cache

import frappe
from frappe import _

from verenigingen.utils.constants import Roles


# Custom Exceptions
# -----------------
class PermissionCheckError(Exception):
    """Base exception for permission check failures"""

    pass


class PermissionDenied(PermissionCheckError):
    """Permission explicitly denied"""

    pass


class PermissionSystemError(PermissionCheckError):
    """System error during permission check"""

    pass


# Permission Level Constants
# --------------------------
class TeamPermissionLevel:
    """Team role permission levels"""

    TEAM_LEADER = "Team Leader"
    PROJECT_COORDINATOR = "Project Coordinator"
    COORDINATOR = "Coordinator"
    CORE_MEMBER = "Core Member"
    SENIOR_MEMBER = "Senior Member"
    REGULAR_MEMBER = "Regular Member"
    VOLUNTEER = "Volunteer"

    @classmethod
    def get_permissions(cls, role_name):
        """Get permissions for a team role with validation"""
        permission_matrix = {
            cls.TEAM_LEADER: ["read", "write", "create"],
            cls.PROJECT_COORDINATOR: ["read", "write", "create"],
            cls.COORDINATOR: ["read", "write", "create"],
            cls.CORE_MEMBER: ["read", "write"],
            cls.SENIOR_MEMBER: ["read", "write"],
            cls.REGULAR_MEMBER: ["read"],
            cls.VOLUNTEER: ["read"],
        }
        if role_name not in permission_matrix:
            frappe.log_error(f"Unknown team role: {role_name}")
            return ["read"]  # Safe fallback
        return permission_matrix[role_name]


class ChapterPermissionLevel:
    """Chapter role permission levels"""

    ADMIN = "Admin"
    FINANCIAL = "Financial"
    BASIC = "Basic"

    @classmethod
    def get_permissions(cls, level, is_chair=False):
        """Get permissions for a chapter role with validation"""
        # Chair gets elevated permissions regardless of base level
        if is_chair:
            return ["read", "write", "create"]

        permission_matrix = {
            cls.ADMIN: ["read", "write", "create", "delete"],
            cls.FINANCIAL: ["read", "write", "create"],
            cls.BASIC: ["read", "write"],
        }

        if level not in permission_matrix:
            frappe.log_error(f"Unknown chapter permission level: {level}")
            return ["read"]  # Safe fallback
        return permission_matrix[level]


# Helper Functions
# ----------------
def validate_identifier(value, max_length=140, context="identifier"):
    """
    Validate DocType name/identifier for safe SQL usage

    Args:
        value: Identifier to validate
        max_length: Maximum allowed length (default: 140, Frappe's DocType name limit)
        context: Context description for logging (e.g., "team name", "test input")

    Returns:
        bool: True if valid, False otherwise
    """
    if not value:
        return False

    if len(value) > max_length:
        frappe.log_error(
            title=f"Security: Identifier Validation ({context})",
            message=f"[{context}] Identifier too long (>{max_length}): {value[:50]}...",
        )
        return False

    # Allow alphanumeric, spaces, hyphens, underscores, and common international characters
    # This is more permissive than strict alphanumeric to support international names
    if not re.match(r"^[\w\s\-]+$", value, re.UNICODE):
        frappe.log_error(
            title=f"Security: Identifier Validation ({context})",
            message=f"[{context}] Invalid characters in identifier: {value}",
        )
        return False

    return True


@lru_cache(maxsize=128)
def get_volunteer_for_user(user):
    """
    Get volunteer record for user with caching

    This helper consolidates the repeated member→volunteer lookup pattern
    used throughout the permission system, reducing database queries and
    improving performance.

    Args:
        user: User email

    Returns:
        tuple: (member_name, volunteer_name) or (None, None)

    Raises:
        PermissionSystemError: If database error occurs
    """
    try:
        # Single optimized query with JOIN instead of 2 separate lookups
        result = frappe.db.sql(
            """
            SELECT m.name as member_name, v.name as volunteer_name
            FROM `tabMember` m
            LEFT JOIN `tabVolunteer` v ON v.member = m.name
            WHERE m.user = %s
            LIMIT 1
        """,
            (user,),
            as_dict=True,
        )

        if result:
            return result[0].member_name, result[0].volunteer_name
        return None, None

    except frappe.db.DatabaseError as e:
        frappe.log_error(f"Database error getting volunteer for user {user}: {str(e)}")
        raise PermissionSystemError("Database error during volunteer lookup") from e
    except Exception as e:
        frappe.log_error(f"Unexpected error getting volunteer for user {user}: {str(e)}")
        raise PermissionSystemError("Unexpected error during volunteer lookup") from e


def has_project_permission_via_team(doc, ptype=None, user=None, debug=False):
    """
    Check if user has project permission through team membership or chapter board membership

    Args:
        doc: Project document or None for list access
        ptype: 'read', 'write', 'create', 'delete', etc. (defaults to 'read' if None)
        user: User email (defaults to current user if None)
        debug: Debug flag (unused, but required by Frappe's permission interface)

    Returns:
        bool: True if user has permission through team or chapter membership
    """
    if user is None:
        user = frappe.session.user

    # Default to 'read' if ptype is None (Frappe passes None for general permission checks)
    if ptype is None:
        ptype = "read"

    if not doc:
        # For list view, check if user is a volunteer on any team or chapter board
        return user_has_any_team_projects(user) or user_has_any_chapter_projects(user)

    # For specific project, check both team and chapter access
    return user_has_project_team_access(user, doc.name, ptype) or user_has_project_chapter_access(
        user, doc.name, ptype
    )


def user_has_any_team_projects(user):
    """
    Check if user is a volunteer on any team that has projects

    Args:
        user: User email

    Returns:
        bool: True if user has team projects, False otherwise

    Raises:
        PermissionDenied: If user has no team projects
        PermissionSystemError: If system error occurs
    """
    try:
        # Use cached helper function (replaces 2 queries with 1)
        member_name, volunteer = get_volunteer_for_user(user)
        if not volunteer:
            raise PermissionDenied(f"User {user} is not a volunteer")

        # Check if volunteer is on any teams with projects (case-insensitive matching)
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
                WHERE p.custom_team = t.name
                OR LOWER(p.project_name) LIKE LOWER(CONCAT('%%', t.team_name, '%%'))
            )
        """,
            (volunteer,),
        )

        if len(teams_with_projects) > 0:
            return True

        raise PermissionDenied(f"User {user} has no team projects")

    except PermissionDenied:
        return False  # Expected case - no permission
    except PermissionSystemError:
        return False  # Already logged
    except frappe.db.DatabaseError as e:
        frappe.log_error(f"Database error checking team projects for {user}: {str(e)}")
        raise PermissionSystemError("Database error during team project check") from e
    except Exception as e:
        frappe.log_error(f"Unexpected error checking team projects for {user}: {str(e)}")
        raise PermissionSystemError("Unexpected error during team project check") from e


def user_has_project_team_access(user, project_name, permission_type):
    """
    Check if user has access to specific project through team membership

    Args:
        user: User email
        project_name: Project document name
        permission_type: Permission type ('read', 'write', 'create', 'delete')

    Returns:
        bool: True if user has required permission, False otherwise
    """
    try:
        # Use cached helper function (replaces 2 queries with 1)
        member_name, volunteer = get_volunteer_for_user(user)
        if not volunteer:
            raise PermissionDenied(f"User {user} is not a volunteer")

        # Get project details using database query (avoids permission recursion)
        project = frappe.db.get_value("Project", project_name, ["custom_team", "project_name"], as_dict=True)
        if not project:
            raise PermissionDenied(f"Project {project_name} not found")

        # Check direct team assignment (if project has custom_team field)
        if project.custom_team:
            team_member = frappe.db.exists(
                "Team Member", {"parent": project.custom_team, "volunteer": volunteer, "status": "Active"}
            )
            if team_member:
                return get_team_permission_level(project.custom_team, volunteer, permission_type)

        # Check indirect team assignment (project name contains team name) - case-insensitive
        user_teams = frappe.db.sql(
            """
            SELECT tm.parent as team_name, tr.role_name as team_role
            FROM `tabTeam Member` tm
            LEFT JOIN `tabTeam Role` tr ON tm.team_role = tr.name
            INNER JOIN `tabTeam` t ON tm.parent = t.name
            WHERE tm.volunteer = %s AND tm.status = 'Active' AND t.status = 'Active'
        """,
            (volunteer,),
            as_dict=True,
        )

        for team in user_teams:
            # Case-insensitive matching
            if team.team_name.lower() in project.project_name.lower():
                return get_team_permission_level(team.team_name, volunteer, permission_type)

        raise PermissionDenied(f"User {user} has no team access to project {project_name}")

    except PermissionDenied:
        return False  # Expected case - no permission
    except PermissionSystemError:
        return False  # Already logged
    except frappe.db.DatabaseError as e:
        frappe.log_error(f"Database error checking team access for {user}, project {project_name}: {str(e)}")
        raise PermissionSystemError("Database error during team access check") from e
    except Exception as e:
        frappe.log_error(
            f"Unexpected error checking team access for {user}, project {project_name}: {str(e)}"
        )
        raise PermissionSystemError("Unexpected error during team access check") from e


def user_has_any_chapter_projects(user):
    """
    Check if user is a chapter board member with access to projects

    Args:
        user: User email

    Returns:
        bool: True if user has chapter projects, False otherwise

    Raises:
        PermissionDenied: If user has no chapter projects
        PermissionSystemError: If system error occurs
    """
    try:
        # Use cached helper function (replaces 2 queries with 1)
        member_name, volunteer = get_volunteer_for_user(user)
        if not volunteer:
            raise PermissionDenied(f"User {user} is not a volunteer")

        # Check if volunteer is on any chapter boards with projects (case-insensitive matching)
        chapters_with_projects = frappe.db.sql(
            """
            SELECT DISTINCT cbm.parent as chapter_name
            FROM `tabChapter Board Member` cbm
            INNER JOIN `tabChapter` c ON cbm.parent = c.name
            WHERE cbm.volunteer = %s
            AND cbm.is_active = 1
            AND c.status = 'Active'
            AND EXISTS (
                SELECT 1 FROM `tabProject` p
                WHERE p.custom_chapter = c.name
                OR LOWER(p.project_name) LIKE LOWER(CONCAT('%%', c.name, '%%'))
            )
        """,
            (volunteer,),
        )

        if len(chapters_with_projects) > 0:
            return True

        raise PermissionDenied(f"User {user} has no chapter projects")

    except PermissionDenied:
        return False  # Expected case - no permission
    except PermissionSystemError:
        return False  # Already logged
    except frappe.db.DatabaseError as e:
        frappe.log_error(f"Database error checking chapter projects for {user}: {str(e)}")
        raise PermissionSystemError("Database error during chapter project check") from e
    except Exception as e:
        frappe.log_error(f"Unexpected error checking chapter projects for {user}: {str(e)}")
        raise PermissionSystemError("Unexpected error during chapter project check") from e


def user_has_project_chapter_access(user, project_name, permission_type):
    """
    Check if user has access to specific project through chapter board membership

    Args:
        user: User email
        project_name: Project document name
        permission_type: Permission type ('read', 'write', 'create', 'delete')

    Returns:
        bool: True if user has required permission, False otherwise
    """
    try:
        # Use cached helper function (replaces 2 queries with 1)
        member_name, volunteer = get_volunteer_for_user(user)
        if not volunteer:
            raise PermissionDenied(f"User {user} is not a volunteer")

        # Get project details using database query (avoids permission recursion)
        project = frappe.db.get_value(
            "Project", project_name, ["custom_chapter", "project_name"], as_dict=True
        )
        if not project:
            raise PermissionDenied(f"Project {project_name} not found")

        # Check direct chapter assignment (if project has custom_chapter field)
        if project.custom_chapter:
            board_member = frappe.db.exists(
                "Chapter Board Member",
                {"parent": project.custom_chapter, "volunteer": volunteer, "is_active": 1},
            )
            if board_member:
                return get_chapter_permission_level(project.custom_chapter, volunteer, permission_type)

        # Check indirect chapter assignment (project name contains chapter name) - case-insensitive
        user_chapters = frappe.db.sql(
            """
            SELECT cbm.parent as chapter_name, cr.role_name, cr.permissions_level, cr.is_chair
            FROM `tabChapter Board Member` cbm
            LEFT JOIN `tabChapter Role` cr ON cbm.chapter_role = cr.name
            INNER JOIN `tabChapter` c ON cbm.parent = c.name
            WHERE cbm.volunteer = %s AND cbm.is_active = 1 AND c.status = 'Active'
        """,
            (volunteer,),
            as_dict=True,
        )

        for chapter in user_chapters:
            # Case-insensitive matching
            if chapter.chapter_name.lower() in project.project_name.lower():
                return get_chapter_permission_level(chapter.chapter_name, volunteer, permission_type)

        raise PermissionDenied(f"User {user} has no chapter access to project {project_name}")

    except PermissionDenied:
        return False  # Expected case - no permission
    except PermissionSystemError:
        return False  # Already logged
    except frappe.db.DatabaseError as e:
        frappe.log_error(
            f"Database error checking chapter access for {user}, project {project_name}: {str(e)}"
        )
        raise PermissionSystemError("Database error during chapter access check") from e
    except Exception as e:
        frappe.log_error(
            f"Unexpected error checking chapter access for {user}, project {project_name}: {str(e)}"
        )
        raise PermissionSystemError("Unexpected error during chapter access check") from e


def get_chapter_permission_level(chapter_name, volunteer, permission_type):
    """
    Determine permission level based on chapter board role

    Uses ChapterPermissionLevel constants for consistent permission mapping.
    Chair role gets elevated permissions regardless of base level.

    Args:
        chapter_name: Chapter name
        volunteer: Volunteer document name
        permission_type: Permission type ('read', 'write', 'create', 'delete')

    Returns:
        bool: True if volunteer has required permission, False otherwise
    """
    try:
        # Get volunteer's role in the chapter board
        board_member = frappe.db.get_value(
            "Chapter Board Member",
            {"parent": chapter_name, "volunteer": volunteer},
            ["chapter_role", "is_active"],
            as_dict=True,
        )

        if not board_member or not board_member.is_active:
            return False

        # Get chapter role details using database query (avoids get_doc())
        if board_member.chapter_role:
            role_details = frappe.db.get_value(
                "Chapter Role",
                board_member.chapter_role,
                ["permissions_level", "is_chair"],
                as_dict=True,
            )
            if role_details:
                permissions_level = role_details.permissions_level or ChapterPermissionLevel.BASIC
                is_chair = role_details.is_chair or False
            else:
                permissions_level = ChapterPermissionLevel.BASIC
                is_chair = False
        else:
            permissions_level = ChapterPermissionLevel.BASIC
            is_chair = False

        # Use constants class for permission mapping
        allowed_permissions = ChapterPermissionLevel.get_permissions(permissions_level, is_chair)
        return permission_type.lower() in allowed_permissions

    except frappe.db.DatabaseError as e:
        frappe.log_error(
            f"Database error getting chapter permission level for chapter {chapter_name}, volunteer {volunteer}: {str(e)}"
        )
        return False
    except Exception as e:
        frappe.log_error(
            f"Unexpected error getting chapter permission level for chapter {chapter_name}, volunteer {volunteer}: {str(e)}"
        )
        return False


def get_team_permission_level(team_name, volunteer, permission_type):
    """
    Determine permission level based on team role

    Uses TeamPermissionLevel constants for consistent permission mapping.

    Args:
        team_name: Team name
        volunteer: Volunteer document name
        permission_type: Permission type ('read', 'write', 'create', 'delete')

    Returns:
        bool: True if volunteer has required permission, False otherwise
    """
    try:
        # Get volunteer's role in the team
        team_member = frappe.db.get_value(
            "Team Member",
            {"parent": team_name, "volunteer": volunteer},
            ["team_role"],
            as_dict=True,
        )

        if not team_member:
            return False

        # Get team role details using database query (avoids get_doc())
        if team_member.team_role:
            role_name = frappe.db.get_value("Team Role", team_member.team_role, "role_name")
            if not role_name:
                role_name = TeamPermissionLevel.REGULAR_MEMBER
        else:
            role_name = TeamPermissionLevel.REGULAR_MEMBER

        # Use constants class for permission mapping
        allowed_permissions = TeamPermissionLevel.get_permissions(role_name)
        return permission_type.lower() in allowed_permissions

    except frappe.db.DatabaseError as e:
        frappe.log_error(
            f"Database error getting team permission level for team {team_name}, volunteer {volunteer}: {str(e)}"
        )
        return False
    except Exception as e:
        frappe.log_error(
            f"Unexpected error getting team permission level for team {team_name}, volunteer {volunteer}: {str(e)}"
        )
        return False


@frappe.whitelist()
def get_user_project_teams(user=None):
    """
    Get all teams, chapters, and their projects that a user has access to

    Args:
        user: User email (defaults to current session user)

    Returns:
        dict: Dictionary with teams, chapters, projects, and volunteer_record
    """
    if not user:
        user = frappe.session.user

    try:
        # Use cached helper function (replaces 2 queries with 1)
        member_name, volunteer = get_volunteer_for_user(user)
        if not volunteer:
            return {"teams": [], "chapters": [], "projects": []}

        # Get user's teams
        user_teams = frappe.db.sql(
            """
            SELECT
                tm.parent as team_name,
                t.description,
                t.status,
                tm.team_role,
                tm.notes as responsibility,
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

        # Get user's chapter boards
        user_chapters = frappe.db.sql(
            """
            SELECT
                cbm.parent as chapter_name,
                c.status,
                cbm.chapter_role,
                cr.role_name,
                cr.permissions_level,
                cr.is_chair
            FROM `tabChapter Board Member` cbm
            INNER JOIN `tabChapter` c ON cbm.parent = c.name
            LEFT JOIN `tabChapter Role` cr ON cbm.chapter_role = cr.name
            WHERE cbm.volunteer = %s AND cbm.is_active = 1
            ORDER BY c.name
        """,
            (volunteer,),
            as_dict=True,
        )

        # Get projects associated with teams
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
                project["access_via"] = "team"
                project["permission_level"] = get_team_permission_level(team.team_name, volunteer, "write")
                team_projects.append(project)

        # Get projects associated with chapters
        chapter_projects = []
        for chapter in user_chapters:
            # Direct chapter assignment
            direct_projects = frappe.db.sql(
                """
                SELECT name, project_name, status, expected_end_date
                FROM `tabProject`
                WHERE custom_chapter = %s
            """,
                (chapter.chapter_name,),
                as_dict=True,
            )

            # Indirect assignment (project name contains chapter name)
            indirect_projects = frappe.db.sql(
                """
                SELECT name, project_name, status, expected_end_date
                FROM `tabProject`
                WHERE project_name LIKE %s
                AND (custom_chapter IS NULL OR custom_chapter != %s)
            """,
                (f"%{chapter.chapter_name}%", chapter.chapter_name),
                as_dict=True,
            )

            for project in direct_projects + indirect_projects:
                project["chapter_name"] = chapter.chapter_name
                project["access_type"] = "direct" if project in direct_projects else "indirect"
                project["access_via"] = "chapter"
                project["permission_level"] = get_chapter_permission_level(
                    chapter.chapter_name, volunteer, "write"
                )
                chapter_projects.append(project)

        # Combine all projects (remove duplicates)
        all_projects = team_projects + chapter_projects
        unique_projects = {p["name"]: p for p in all_projects}.values()

        return {
            "teams": user_teams,
            "chapters": user_chapters,
            "projects": list(unique_projects),
            "volunteer_record": volunteer,
        }

    except Exception as e:
        frappe.log_error(f"Error getting user project teams for {user}: {str(e)}")
        return {"teams": [], "chapters": [], "projects": [], "error": str(e)}


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
    """
    Generate query conditions for project list based on team and chapter membership

    Args:
        user: User email

    Returns:
        str: SQL WHERE clause conditions or "1=0" for no access

    Security:
        - All team/chapter names are validated and escaped before SQL usage
        - Uses frappe.db.escape() to prevent SQL injection
        - Validates identifiers against safe character set
    """
    if not user or user == "Guest":
        return "1=0"  # No access for guests

    # Admin users get full access
    user_roles = frappe.get_roles(user)
    admin_roles = [Roles.SYSTEM_MANAGER, "Projects Manager", Roles.VERENIGINGEN_ADMIN]
    if any(role in user_roles for role in admin_roles):
        return ""  # Full access

    # Check if user is a volunteer with team or chapter access
    try:
        # Use cached helper function (replaces 2 queries with 1)
        member_name, volunteer = get_volunteer_for_user(user)
        if not volunteer:
            return "1=0"

        all_conditions = []

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

        # Build conditions for projects accessible via teams
        for team in user_teams:
            # Validate team name before using in SQL
            if not validate_identifier(team, context="team name in permission query"):
                frappe.log_error(f"Invalid team name in permissions: {team}")
                continue

            # Escape values to prevent SQL injection
            escaped_team = frappe.db.escape(team)
            escaped_like_pattern = frappe.db.escape(f"%{team}%")

            # Direct team assignment - case-insensitive
            all_conditions.append(f"`tabProject`.custom_team = {escaped_team}")
            # Indirect assignment (project name contains team name) - case-insensitive
            all_conditions.append(f"LOWER(`tabProject`.project_name) LIKE LOWER({escaped_like_pattern})")

        # Get user's active chapter boards
        user_chapters = frappe.db.sql(
            """
            SELECT cbm.parent as chapter_name
            FROM `tabChapter Board Member` cbm
            INNER JOIN `tabChapter` c ON cbm.parent = c.name
            WHERE cbm.volunteer = %s AND cbm.is_active = 1 AND c.status = 'Active'
        """,
            (volunteer,),
            pluck=True,
        )

        # Build conditions for projects accessible via chapters
        for chapter in user_chapters:
            # Validate chapter name before using in SQL
            if not validate_identifier(chapter, context="chapter name in permission query"):
                frappe.log_error(f"Invalid chapter name in permissions: {chapter}")
                continue

            # Escape values to prevent SQL injection
            escaped_chapter = frappe.db.escape(chapter)
            escaped_like_pattern = frappe.db.escape(f"%{chapter}%")

            # Direct chapter assignment - case-insensitive
            all_conditions.append(f"`tabProject`.custom_chapter = {escaped_chapter}")
            # Indirect assignment (project name contains chapter name) - case-insensitive
            all_conditions.append(f"LOWER(`tabProject`.project_name) LIKE LOWER({escaped_like_pattern})")

        if all_conditions:
            return f"({' OR '.join(all_conditions)})"
        else:
            return "1=0"

    except PermissionSystemError:
        # Already logged by get_volunteer_for_user
        return "1=0"
    except frappe.db.DatabaseError as e:
        frappe.log_error(f"Database error generating project query conditions for {user}: {str(e)}")
        return "1=0"
    except Exception as e:
        frappe.log_error(f"Unexpected error generating project query conditions for {user}: {str(e)}")
        return "1=0"
