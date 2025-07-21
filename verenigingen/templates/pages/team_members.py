"""
Team Members Portal Page
Shows team members for a specific team that the user has access to
"""

import frappe
from frappe import _
from frappe.utils import format_date


def get_context(context):
    """Get context for team members page"""

    # Require login
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to access this page"), frappe.PermissionError)

    context.no_cache = 1
    context.title = _("Team Members")

    # Get team parameter
    team_name = frappe.form_dict.get("team")
    if not team_name:
        frappe.throw(_("Team parameter is required"), frappe.ValidationError)

    # Get team info
    try:
        team = frappe.get_doc("Team", team_name)
        context.team = team
    except frappe.DoesNotExistError:
        frappe.throw(_("Team not found"), frappe.DoesNotExistError)

    # Get user's member and volunteer records
    user = frappe.session.user
    member = frappe.db.get_value("Member", {"user": user}, "name")
    if not member:
        frappe.throw(_("No member record found for your account"), frappe.DoesNotExistError)

    volunteer = frappe.db.get_value("Volunteer", {"member": member}, "name")

    # Allow members to view team information even if they're not volunteers yet
    # This is important for members who want to explore volunteering opportunities

    # Security check: Only allow team members or admins to view team members
    admin_roles = [
        "System Manager",
        "Verenigingen Administrator",
        "Verenigingen Manager",
        "Volunteer Manager",
    ]
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

    # Get team members
    team_members = frappe.db.sql(
        """
        SELECT
            tm.volunteer,
            tm.volunteer_name,
            tm.role_type,
            tm.role,
            v.email,
            tm.from_date,
            tm.to_date,
            tm.status,
            m.first_name,
            m.last_name,
            m.member_id
        FROM
            `tabTeam Member` tm
        LEFT JOIN
            `tabVolunteer` v ON tm.volunteer = v.name
        LEFT JOIN
            `tabMember` m ON v.member = m.name
        WHERE
            tm.parent = %(team)s
            AND tm.is_active = 1
        ORDER BY
            tm.role_type DESC, tm.from_date ASC
    """,
        {"team": team_name},
        as_dict=True,
    )

    # Format the data for display
    for member in team_members:
        if member.from_date:
            member.formatted_from_date = format_date(member.from_date)
        if member.to_date:
            member.formatted_to_date = format_date(member.to_date)

        # Create display name
        if member.first_name and member.last_name:
            member.display_name = f"{member.first_name} {member.last_name}"
        else:
            member.display_name = member.volunteer_name or "Unknown"

    context.team_members = team_members
    context.current_user_volunteer = volunteer

    return context


def has_website_permission(doc, ptype, user, verbose=False):
    """Check website permission for team members page"""
    # Only logged-in users can access
    if user == "Guest":
        return False

    # Check if user has a member record
    member = frappe.db.get_value("Member", {"user": user})
    return bool(member)
