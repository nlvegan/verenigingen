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
            "fieldtype": "Data",
            "label": _("Email"),
            "width": 200,
        },
        {
            "fieldname": "active_chapter",
            "label": _("Active Chapter"),
            "fieldtype": "Link",
            "options": "Chapter",
            "width": 150,
        },
        {
            "fieldname": "interested_in_volunteering",
            "label": _("Vol/Emp Expected"),
            "fieldtype": "Check",
            "width": 110,
        },
        {
            "fieldname": "has_user",
            "label": _("User Exists"),
            "fieldtype": "Check",
            "width": 90,
        },
        {
            "fieldname": "user_linked",
            "label": _("User Linked"),
            "fieldtype": "Check",
            "width": 90,
        },
        {
            "fieldname": "has_volunteer",
            "label": _("Vol Exists"),
            "fieldtype": "Check",
            "width": 85,
        },
        {
            "fieldname": "volunteer_linked",
            "label": _("Vol Linked"),
            "fieldtype": "Check",
            "width": 85,
        },
        {
            "fieldname": "has_employee",
            "label": _("Emp Exists"),
            "fieldtype": "Check",
            "width": 85,
        },
        {
            "fieldname": "employee_linked",
            "label": _("Emp Linked"),
            "fieldtype": "Check",
            "width": 85,
        },
        {
            "fieldname": "has_customer",
            "label": _("Customer Exists"),
            "fieldtype": "Check",
            "width": 100,
        },
        {
            "fieldname": "customer_linked",
            "label": _("Customer Linked"),
            "fieldtype": "Check",
            "width": 100,
        },
        {
            "fieldname": "has_address",
            "label": _("Address Exists"),
            "fieldtype": "Check",
            "width": 100,
        },
        {
            "fieldname": "address_linked",
            "label": _("Address Linked"),
            "fieldtype": "Check",
            "width": 100,
        },
        {
            "fieldname": "has_membership",
            "label": _("Membership Exists"),
            "fieldtype": "Check",
            "width": 120,
        },
        {
            "fieldname": "membership_status",
            "label": _("Membership Status"),
            "fieldtype": "Data",
            "width": 120,
        },
        {
            "fieldname": "has_dues_schedule",
            "label": _("Dues Schedule"),
            "fieldtype": "Check",
            "width": 100,
        },
        {
            "fieldname": "dues_schedule_status",
            "label": _("Schedule Status"),
            "fieldtype": "Data",
            "width": 120,
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
    # Check for actual record existence first, then linking status
    data = frappe.db.sql(
        f"""
        SELECT
            m.name as member_name,
            m.full_name,
            m.email,
            (
                SELECT cm.parent
                FROM `tabChapter Member` cm
                WHERE cm.member = m.name
                    AND cm.enabled = 1
                    AND cm.status = 'Active'
                ORDER BY cm.chapter_join_date DESC
                LIMIT 1
            ) as active_chapter,
            m.interested_in_volunteering,
            CASE
                WHEN u.name IS NOT NULL THEN 1
                ELSE 0
            END as has_user,
            CASE
                WHEN m.user IS NOT NULL AND m.user != '' AND u.name IS NOT NULL THEN 1
                ELSE 0
            END as user_linked,
            CASE
                WHEN vol.name IS NOT NULL THEN 1
                ELSE 0
            END as has_volunteer,
            CASE
                WHEN vol.user IS NOT NULL AND vol.user != '' THEN 1
                ELSE 0
            END as volunteer_linked,
            CASE
                WHEN emp.name IS NOT NULL THEN 1
                ELSE 0
            END as has_employee,
            CASE
                WHEN emp.user_id IS NOT NULL AND emp.user_id != '' THEN 1
                ELSE 0
            END as employee_linked,
            CASE
                WHEN cust.name IS NOT NULL THEN 1
                ELSE 0
            END as has_customer,
            CASE
                WHEN m.customer IS NOT NULL AND m.customer != '' AND cust.name IS NOT NULL THEN 1
                ELSE 0
            END as customer_linked,
            CASE
                WHEN addr.name IS NOT NULL THEN 1
                ELSE 0
            END as has_address,
            CASE
                WHEN m.primary_address IS NOT NULL AND m.primary_address != '' AND addr.name IS NOT NULL THEN 1
                ELSE 0
            END as address_linked,
            CASE
                WHEN mem.name IS NOT NULL THEN 1
                ELSE 0
            END as has_membership,
            mem.status as membership_status,
            CASE
                WHEN mds.name IS NOT NULL THEN 1
                ELSE 0
            END as has_dues_schedule,
            mds.status as dues_schedule_status,
            acr.status as account_request_status,
            acr.failure_reason,
            acr.retry_count,
            acr.name as account_request_name
        FROM `tabMember` m
        LEFT JOIN `tabUser` u ON u.name = m.email OR u.name = m.user
        LEFT JOIN `tabVolunteer` vol ON vol.member = m.name
        LEFT JOIN `tabEmployee` emp ON emp.user_id = m.user OR emp.user_id = m.email
        LEFT JOIN `tabCustomer` cust ON cust.name = m.customer
        LEFT JOIN `tabAddress` addr ON addr.name = m.primary_address
        LEFT JOIN `tabMembership` mem ON mem.member = m.name AND mem.docstatus = 1
        LEFT JOIN `tabMembership Dues Schedule` mds ON mds.member = m.name
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
                WHEN u.name IS NULL THEN 2
                WHEN mem.name IS NULL THEN 3
                WHEN mds.name IS NULL THEN 4
                WHEN vol.name IS NULL THEN 5
                WHEN emp.name IS NULL THEN 6
                WHEN cust.name IS NULL THEN 7
                WHEN addr.name IS NULL THEN 8
                ELSE 9
            END,
            m.modified DESC
        LIMIT 1000
        """,
        as_dict=1,
    )

    return data


def get_summary_data():
    """Get summary statistics for the report header."""

    # Active members (excludes terminated, banned, deceased)
    active_members = frappe.db.sql(
        """
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN EXISTS (SELECT 1 FROM `tabMembership` mem WHERE mem.member = `tabMember`.name AND mem.docstatus = 1) THEN 1 ELSE 0 END) as with_membership,
            SUM(CASE WHEN EXISTS (SELECT 1 FROM `tabMembership Dues Schedule` mds WHERE mds.member = `tabMember`.name) THEN 1 ELSE 0 END) as with_dues_schedule
        FROM `tabMember`
        WHERE status NOT IN ('Terminated', 'Banned', 'Deceased')
        """,
        as_dict=1,
    )[0]

    # Active members with chapter membership (excludes terminated, banned, deceased)
    active_chapter_members = frappe.db.sql(
        """
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN user IS NOT NULL AND user != '' THEN 1 ELSE 0 END) as with_user,
            SUM(CASE WHEN has_volunteer = 1 THEN 1 ELSE 0 END) as with_volunteer,
            SUM(CASE WHEN EXISTS (SELECT 1 FROM `tabEmployee` e WHERE e.user_id = user) THEN 1 ELSE 0 END) as with_employee
        FROM (
            SELECT DISTINCT m.name, m.user,
                CASE WHEN EXISTS (SELECT 1 FROM `tabVolunteer` v WHERE v.member = m.name) THEN 1 ELSE 0 END as has_volunteer
            FROM `tabMember` m
            INNER JOIN `tabChapter Member` cm ON cm.member = m.name
            WHERE cm.enabled = 1
                AND cm.status = 'Active'
                AND m.status NOT IN ('Terminated', 'Banned', 'Deceased')
        ) as unique_members
        """,
        as_dict=1,
    )[0]

    # Overall member statistics
    member_stats = frappe.db.sql(
        """
        SELECT
            COUNT(*) as total_members,
            SUM(CASE WHEN user IS NOT NULL AND user != '' THEN 1 ELSE 0 END) as members_with_user,
            SUM(CASE WHEN EXISTS (SELECT 1 FROM `tabVolunteer` v WHERE v.member = `tabMember`.name) THEN 1 ELSE 0 END) as members_with_volunteer,
            SUM(CASE WHEN EXISTS (SELECT 1 FROM `tabEmployee` e WHERE e.user_id = `tabMember`.user) THEN 1 ELSE 0 END) as members_with_employee,
            SUM(CASE WHEN customer IS NOT NULL AND customer != '' THEN 1 ELSE 0 END) as members_with_customer,
            SUM(CASE WHEN primary_address IS NOT NULL AND primary_address != '' THEN 1 ELSE 0 END) as members_with_address,
            SUM(CASE WHEN EXISTS (SELECT 1 FROM `tabMembership` mem WHERE mem.member = `tabMember`.name AND mem.docstatus = 1) THEN 1 ELSE 0 END) as members_with_membership,
            SUM(CASE WHEN EXISTS (SELECT 1 FROM `tabMembership Dues Schedule` mds WHERE mds.member = `tabMember`.name) THEN 1 ELSE 0 END) as members_with_dues_schedule
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

    # Build summary - total members first, then active members
    summary = [
        {
            "label": _("Total Members (All)"),
            "value": member_stats["total_members"],
            "indicator": "blue",
            "datatype": "Int",
        },
        {
            "label": _("Active Members"),
            "value": active_members["total"],
            "indicator": "green",
            "datatype": "Int",
        },
        {
            "label": _("Active Chapter Members"),
            "value": active_chapter_members["total"],
            "indicator": "green",
            "datatype": "Int",
        },
        {
            "label": _("└─ with Membership"),
            "value": active_members["with_membership"],
            "indicator": "green"
            if active_members["with_membership"] == active_members["total"]
            else "orange",
            "datatype": "Int",
        },
        {
            "label": _("└─ with Dues Schedule"),
            "value": active_members["with_dues_schedule"],
            "indicator": "green"
            if active_members["with_dues_schedule"] == active_members["total"]
            else "orange",
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
            "label": _("└─ with User Account"),
            "value": active_chapter_members["with_user"],
            "indicator": "green"
            if active_chapter_members["with_user"] == member_stats["members_with_user"]
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
            "label": _("└─ with Volunteer Record"),
            "value": active_chapter_members["with_volunteer"],
            "indicator": "green"
            if active_chapter_members["with_volunteer"] == member_stats["members_with_volunteer"]
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
        {
            "label": _("└─ with Employee Record"),
            "value": active_chapter_members["with_employee"],
            "indicator": "green"
            if active_chapter_members["with_employee"] == member_stats["members_with_employee"]
            else "orange",
            "datatype": "Int",
        },
        {
            "label": _("Members with Customer Record"),
            "value": member_stats["members_with_customer"],
            "indicator": "green"
            if member_stats["members_with_customer"] == member_stats["total_members"]
            else "orange",
            "datatype": "Int",
        },
        {
            "label": _("Members with Address"),
            "value": member_stats["members_with_address"],
            "indicator": "green"
            if member_stats["members_with_address"] == member_stats["total_members"]
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
