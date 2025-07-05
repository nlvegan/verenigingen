import frappe
from frappe import _


def execute(filters=None):
    """
    Main execution function for the Users by Team report.

    Args:
        filters (dict, optional): Filter criteria. Defaults to {}.

    Returns:
        tuple: Columns definition and data for the report
    """
    if not filters:
        filters = {}

    columns = get_columns()
    data = get_data(filters)

    return columns, data


def get_columns():
    """Define columns for the report"""
    return [
        {"label": _("Team"), "fieldname": "team", "fieldtype": "Link", "options": "Team", "width": 140},
        {
            "label": _("Team Lead"),
            "fieldname": "team_lead",
            "fieldtype": "Link",
            "options": "User",
            "width": 140,
        },
        {"label": _("User"), "fieldname": "user", "fieldtype": "Link", "options": "User", "width": 140},
        {"label": _("User Name"), "fieldname": "user_full_name", "fieldtype": "Data", "width": 180},
        {
            "label": _("Role"),
            "fieldname": "team_role",
            "fieldtype": "Link",
            "options": "Team Role",
            "width": 120,
        },
        {"label": _("Permission Level"), "fieldname": "permissions_level", "fieldtype": "Data", "width": 120},
        {"label": _("From Date"), "fieldname": "from_date", "fieldtype": "Date", "width": 100},
        {"label": _("To Date"), "fieldname": "to_date", "fieldtype": "Date", "width": 100},
        {"label": _("Active"), "fieldname": "is_active", "fieldtype": "Check", "width": 70},
    ]


def get_data(filters):
    """
    Fetch and process data for the report based on filters

    Args:
        filters (dict): Filter criteria

    Returns:
        list: List of dictionaries containing report data
    """
    # Build conditions based on filters
    conditions = []
    values = {}

    if filters.get("active_only"):
        conditions.append("tmr.is_active = 1")

    # Additional filters can be added here
    if filters.get("team"):
        conditions.append("t.name = %(team)s")
        values["team"] = filters.get("team")

    if filters.get("user"):
        conditions.append("tmr.user = %(user)s")
        values["user"] = filters.get("user")

    if filters.get("team_role"):
        conditions.append("tmr.team_role = %(team_role)s")
        values["team_role"] = filters.get("team_role")

    conditions_str = " AND " + " AND ".join(conditions) if conditions else ""

    try:
        # Verify tables exist before running query
        tables = ["tabTeam", "tabTeam Member Role", "tabTeam Role"]
        for table in tables:
            if not frappe.db.table_exists(table.replace("tab", "")):
                frappe.log_error(f"Table {table} does not exist", "Users by Team Report Error")
                return []

        # Use safer parameterized query with proper JOIN syntax
        query = """
        SELECT
            t.name as team,
            t.team_lead as team_lead,
            tmr.user as user,
            u.full_name as user_full_name,
            tmr.team_role as team_role,
            tr.permissions_level as permissions_level,
            tmr.from_date as from_date,
            tmr.to_date as to_date,
            tmr.is_active as is_active
        FROM
            `tabTeam Member Role` tmr
        JOIN
            `tabTeam` t ON tmr.parent = t.name
        LEFT JOIN
            `tabUser` u ON tmr.user = u.name
        LEFT JOIN
            `tabTeam Role` tr ON tmr.team_role = tr.name
        WHERE
            tmr.parenttype = 'Team'
            {conditions}
        ORDER BY
            t.name, tmr.user
        """.format(
            conditions=conditions_str
        )

        result = frappe.db.sql(query, values=values, as_dict=1)
        return result

    except Exception as e:
        # Create a more compact error message to avoid length issues
        error_msg = str(e)
        if len(error_msg) > 100:
            error_msg = error_msg[:97] + "..."

        frappe.log_error(message=f"Report query error: {error_msg}", title="Users by Team Report Error")

        # Return empty result instead of crashing
        return []
