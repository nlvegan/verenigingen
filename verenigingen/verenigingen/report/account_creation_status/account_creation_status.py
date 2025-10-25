"""
Account Creation Status Report
================================

Comprehensive tracking report for import and account creation operations.
Shows overall status, progress, failures, and provides retry capabilities.

This report helps answer:
- How many members have complete accounts (User, Employee, Volunteer)?
- How many account creation requests failed and why?
- Which members are missing accounts?
- Ability to retry failed requests in bulk

Author: Verenigingen Development Team
"""

import frappe
from frappe import _


def execute(filters=None):
    """Generate account creation status report."""
    columns = get_columns()
    data = get_data(filters)
    summary = get_summary_data()
    chart = get_chart_data()

    return columns, data, None, chart, summary


def get_columns():
    """Define report columns."""
    return [
        {
            "fieldname": "member_name",
            "label": _("Member ID"),
            "fieldtype": "Link",
            "options": "Member",
            "width": 150,
        },
        {
            "fieldname": "full_name",
            "label": _("Full Name"),
            "fieldtype": "Data",
            "width": 200,
        },
        {
            "fieldname": "email",
            "label": _("Email"),
            "fieldtype": "Data",
            "width": 200,
        },
        {
            "fieldname": "has_user",
            "label": _("User Account"),
            "fieldtype": "Check",
            "width": 100,
        },
        {
            "fieldname": "has_volunteer",
            "label": _("Volunteer"),
            "fieldtype": "Check",
            "width": 90,
        },
        {
            "fieldname": "has_employee",
            "label": _("Employee"),
            "fieldtype": "Check",
            "width": 90,
        },
        {
            "fieldname": "account_request_status",
            "label": _("Request Status"),
            "fieldtype": "Data",
            "width": 120,
        },
        {
            "fieldname": "failure_reason",
            "label": _("Failure Reason"),
            "fieldtype": "Data",
            "width": 300,
        },
        {
            "fieldname": "retry_count",
            "label": _("Retries"),
            "fieldtype": "Int",
            "width": 70,
        },
        {
            "fieldname": "account_request_name",
            "label": _("Request ID"),
            "fieldtype": "Link",
            "options": "Account Creation Request",
            "width": 150,
        },
    ]


def get_data(filters):
    """Get member account creation status data."""

    # Build filters
    conditions = []
    if filters and filters.get("status_filter"):
        if filters["status_filter"] == "Missing User":
            conditions.append("m.user IS NULL OR m.user = ''")
        elif filters["status_filter"] == "Missing Volunteer":
            conditions.append("vol.name IS NULL")
        elif filters["status_filter"] == "Missing Employee":
            conditions.append("emp.name IS NULL")
        elif filters["status_filter"] == "Failed Requests":
            conditions.append("acr.status = 'Failed'")
        elif filters["status_filter"] == "Complete":
            conditions.append("m.user IS NOT NULL AND m.user != ''")
            conditions.append("vol.name IS NOT NULL")
            conditions.append("emp.name IS NOT NULL")

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    # Get comprehensive member and account creation data
    data = frappe.db.sql(
        f"""
        SELECT
            m.name as member_name,
            m.full_name,
            m.email,
            CASE WHEN m.user IS NOT NULL AND m.user != '' THEN 1 ELSE 0 END as has_user,
            CASE WHEN vol.name IS NOT NULL THEN 1 ELSE 0 END as has_volunteer,
            CASE WHEN emp.name IS NOT NULL THEN 1 ELSE 0 END as has_employee,
            acr.status as account_request_status,
            acr.failure_reason,
            acr.retry_count,
            acr.name as account_request_name
        FROM `tabMember` m
        LEFT JOIN `tabVolunteer` vol ON vol.member = m.name
        LEFT JOIN `tabEmployee` emp ON emp.user_id = m.user
        LEFT JOIN (
            SELECT *
            FROM `tabAccount Creation Request`
            WHERE name IN (
                SELECT MAX(name)
                FROM `tabAccount Creation Request`
                GROUP BY source_record
            )
        ) acr ON acr.source_record = m.name
        {where_clause}
        ORDER BY
            CASE
                WHEN acr.status = 'Failed' THEN 1
                WHEN m.user IS NULL OR m.user = '' THEN 2
                WHEN vol.name IS NULL THEN 3
                WHEN emp.name IS NULL THEN 4
                ELSE 5
            END,
            m.modified DESC
        LIMIT 1000
        """,
        as_dict=1,
    )

    return data


def get_summary_data():
    """Get summary statistics for the report header."""

    # Overall member statistics
    member_stats = frappe.db.sql(
        """
        SELECT
            COUNT(*) as total_members,
            SUM(CASE WHEN user IS NOT NULL AND user != '' THEN 1 ELSE 0 END) as members_with_user,
            SUM(CASE WHEN EXISTS (SELECT 1 FROM `tabVolunteer` v WHERE v.member = `tabMember`.name) THEN 1 ELSE 0 END) as members_with_volunteer,
            SUM(CASE WHEN EXISTS (SELECT 1 FROM `tabEmployee` e WHERE e.user_id = `tabMember`.user) THEN 1 ELSE 0 END) as members_with_employee
        FROM `tabMember`
        """,
        as_dict=1,
    )[0]

    # Account Creation Request statistics
    request_stats = frappe.db.sql(
        """
        SELECT
            status,
            COUNT(*) as count
        FROM `tabAccount Creation Request`
        GROUP BY status
        """,
        as_dict=1,
    )

    # Failed request breakdown
    failure_stats = frappe.db.sql(
        """
        SELECT
            CASE
                WHEN failure_reason LIKE '%Throttled%' OR failure_reason LIKE '%rate limit%' THEN 'Rate Limited'
                WHEN failure_reason LIKE '%already assigned to Employee%' THEN 'Employee Exists'
                WHEN failure_reason LIKE '%modified after you%' THEN 'Concurrent Modification'
                ELSE 'Other'
            END as failure_type,
            COUNT(*) as count
        FROM `tabAccount Creation Request`
        WHERE status = 'Failed'
        GROUP BY failure_type
        """,
        as_dict=1,
    )

    # Build summary
    summary = [
        {
            "label": _("Total Members"),
            "value": member_stats["total_members"],
            "indicator": "blue",
            "datatype": "Int",
        },
        {
            "label": _("Members with User Account"),
            "value": member_stats["members_with_user"],
            "indicator": "green"
            if member_stats["members_with_user"] == member_stats["total_members"]
            else "orange",
            "datatype": "Int",
        },
        {
            "label": _("Members with Volunteer Record"),
            "value": member_stats["members_with_volunteer"],
            "indicator": "green"
            if member_stats["members_with_volunteer"] == member_stats["total_members"]
            else "orange",
            "datatype": "Int",
        },
        {
            "label": _("Members with Employee Record"),
            "value": member_stats["members_with_employee"],
            "indicator": "green"
            if member_stats["members_with_employee"] == member_stats["total_members"]
            else "orange",
            "datatype": "Int",
        },
    ]

    # Add request status summary
    for req_stat in request_stats:
        indicator = "green"
        if req_stat["status"] == "Failed":
            indicator = "red"
        elif req_stat["status"] in ["Queued", "Processing"]:
            indicator = "orange"

        summary.append(
            {
                "label": _(f"Requests {req_stat['status']}"),
                "value": req_stat["count"],
                "indicator": indicator,
                "datatype": "Int",
            }
        )

    # Add failure breakdown
    for fail_stat in failure_stats:
        summary.append(
            {
                "label": _(f"Failed: {fail_stat['failure_type']}"),
                "value": fail_stat["count"],
                "indicator": "red",
                "datatype": "Int",
            }
        )

    return summary


def get_chart_data():
    """Generate chart showing account completion status."""

    # Get completion stats
    stats = frappe.db.sql(
        """
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN user IS NOT NULL AND user != '' THEN 1 ELSE 0 END) as with_user,
            SUM(CASE WHEN EXISTS (SELECT 1 FROM `tabVolunteer` v WHERE v.member = `tabMember`.name) THEN 1 ELSE 0 END) as with_volunteer,
            SUM(CASE WHEN EXISTS (SELECT 1 FROM `tabEmployee` e WHERE e.user_id = `tabMember`.user) THEN 1 ELSE 0 END) as with_employee,
            SUM(CASE
                WHEN user IS NOT NULL AND user != ''
                AND EXISTS (SELECT 1 FROM `tabVolunteer` v WHERE v.member = `tabMember`.name)
                AND EXISTS (SELECT 1 FROM `tabEmployee` e WHERE e.user_id = `tabMember`.user)
                THEN 1 ELSE 0
            END) as complete
        FROM `tabMember`
        """,
        as_dict=1,
    )[0]

    chart = {
        "data": {
            "labels": ["User Account", "Volunteer Record", "Employee Record", "Complete (All 3)"],
            "datasets": [
                {
                    "name": "Members",
                    "values": [
                        stats["with_user"],
                        stats["with_volunteer"],
                        stats["with_employee"],
                        stats["complete"],
                    ],
                }
            ],
        },
        "type": "bar",
        "colors": ["#28a745", "#17a2b8", "#ffc107", "#007bff"],
        "barOptions": {"stacked": 0},
    }

    return chart


@frappe.whitelist()
def retry_failed_requests_from_report(failure_type=None):
    """
    Wrapper to retry failed requests from the report interface.
    Calls the main retry function in account_creation_manager.
    """
    from verenigingen.utils.account_creation_manager import retry_all_failed_requests

    return retry_all_failed_requests(failure_type=failure_type)
