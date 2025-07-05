import frappe
import frappe.utils
from frappe import _


def execute(filters=None):
    if not filters:
        filters = {}

    team = filters.get("team")
    if not team:
        frappe.throw("Team parameter is required")

    # Security check: Only allow team members to see their own team
    # or administrators to see any team
    if not (
        frappe.session.user == "Administrator"
        or "System Manager" in frappe.get_roles()
        or "Verenigingen Administrator" in frappe.get_roles()
        or "Verenigingen Manager" in frappe.get_roles()
        or "Volunteer Manager" in frappe.get_roles()
    ):
        # Check if user is a member of this team
        user_email = frappe.session.user
        member = frappe.db.get_value("Member", {"user": user_email}, "name")

        if member:
            # Check via volunteer relationship
            volunteer = frappe.db.get_value("Volunteer", {"member": member}, "name")

            if volunteer:
                is_team_member = frappe.db.exists(
                    "Team Member", {"parent": team, "volunteer": volunteer, "is_active": 1}
                )

                if not is_team_member:
                    frappe.throw(_("You can only view members of teams where you are a member"))
            else:
                frappe.throw(_("You must be registered as a volunteer to access this report"))
        else:
            frappe.throw(_("You must be a member to access this report"))

    columns = [
        {
            "fieldname": "volunteer",
            "label": "Volunteer",
            "fieldtype": "Link",
            "options": "Volunteer",
            "width": 200,
        },
        {"fieldname": "volunteer_name", "label": "Name", "fieldtype": "Data", "width": 200},
        {"fieldname": "role_type", "label": "Role Type", "fieldtype": "Data", "width": 120},
        {"fieldname": "role", "label": "Specific Role", "fieldtype": "Data", "width": 150},
        {"fieldname": "email", "label": "Email", "fieldtype": "Data", "width": 200},
        {"fieldname": "from_date", "label": "Start Date", "fieldtype": "Date", "width": 120},
        {"fieldname": "to_date", "label": "End Date", "fieldtype": "Date", "width": 120},
        {"fieldname": "status", "label": "Status", "fieldtype": "Data", "width": 100},
    ]

    data = frappe.db.sql(
        """
        SELECT
            tm.volunteer,
            tm.volunteer_name,
            tm.role_type,
            tm.role,
            v.email,
            tm.from_date,
            tm.to_date,
            tm.status
        FROM
            `tabTeam Member` tm
        LEFT JOIN
            `tabVolunteer` v ON tm.volunteer = v.name
        WHERE
            tm.parent = %(team)s
            AND tm.is_active = 1
        ORDER BY
            tm.role_type DESC, tm.from_date ASC
    """,
        {"team": team},
        as_dict=True,
    )

    return columns, data
