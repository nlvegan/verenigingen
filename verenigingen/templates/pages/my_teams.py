"""
My Teams Page
Shows user's team memberships and provides access to team member reports
"""

import frappe
from frappe import _


def get_context(context):
    """Get context for my teams page"""

    # Require login
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to access this page"), frappe.PermissionError)

    context.no_cache = 1
    context.title = _("My Teams")

    # Get member record
    member = frappe.db.get_value("Member", {"email": frappe.session.user})
    if not member:
        frappe.throw(_("No member record found for your account"), frappe.DoesNotExistError)

    # Get volunteer record
    volunteer = frappe.db.get_value("Volunteer", {"member": member})
    if not volunteer:
        context.teams = []
        context.volunteer = None
        return context

    context.volunteer = volunteer

    # Get user's teams with detailed information
    teams = frappe.db.sql(
        """
        SELECT DISTINCT
            t.name,
            t.team_name,
            t.team_type,
            t.description,
            t.status as team_status,
            tm.role_type,
            tm.role,
            tm.status as member_status,
            tm.from_date,
            tm.to_date,
            tm.is_active
        FROM `tabTeam` t
        INNER JOIN `tabTeam Member` tm ON t.name = tm.parent
        WHERE tm.volunteer = %(volunteer)s
        AND tm.is_active = 1
        AND t.status = 'Active'
        ORDER BY t.team_name, tm.from_date DESC
    """,
        {"volunteer": volunteer},
        as_dict=True,
    )

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


def has_website_permission(doc, ptype, user, verbose=False):
    """Check website permission for my teams page"""
    # Only logged-in users can access
    if user == "Guest":
        return False

    # Check if user has a member record
    member = frappe.db.get_value("Member", {"email": user})
    return bool(member)
