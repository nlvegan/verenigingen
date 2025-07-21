# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import getdate, today


def execute(filters=None):
    columns = get_columns(filters)
    data = get_data(filters)
    return columns, data


def get_columns(filters):
    return [
        _("Member ID") + ":Link/Member:120",
        _("Member Name") + ":Data:180",
        _("Email") + ":Data:200",
        _("Member Status") + ":Data:100",
        _("Member Since") + ":Date:100",
        # _("Chapter") + ":Data:120",  # Skip chapter for now - it's a computed field
        _("Last Membership ID") + ":Link/Membership:120",
        _("Last Membership Type") + ":Data:120",
        _("Last Membership Status") + ":Data:120",
        _("Last Membership End") + ":Date:100",
        _("Days Since Last Membership") + ":Int:80",
        _("Contact Number") + ":Data:120",
    ]


def get_data(filters):
    # Initialize filters if None
    if filters is None:
        filters = {}

    # Build dynamic WHERE conditions based on filters
    where_conditions = ["m.docstatus != 2"]  # Exclude cancelled member records

    # Handle member status filters
    status_conditions = []

    if not filters.get("include_terminated"):
        status_conditions.append("m.status != 'Terminated'")

    if not filters.get("include_suspended"):
        status_conditions.append("m.status != 'Suspended'")

    # Specific status filter takes precedence
    if filters.get("member_status"):
        status_conditions = [f"m.status = '{filters.get('member_status')}'"]

    if status_conditions:
        where_conditions.extend(status_conditions)

    # Chapter filter (skip for now since it's HTML field)
    # if filters.get("chapter"):
    #     where_conditions.append(f"m.current_chapter_display LIKE '%{filters.get('chapter')}%'")

    where_clause = " AND ".join(where_conditions)

    # Get all members without active memberships
    sql_query = f"""
        SELECT
            m.name as member_id,
            m.full_name as member_name,
            m.email,
            m.status as member_status,
            m.member_since,
            last_membership.name as last_membership_id,
            last_membership.membership_type as last_membership_type,
            last_membership.status as last_membership_status,
            last_membership.end_date as last_membership_end,
            CASE
                WHEN last_membership.end_date IS NOT NULL
                THEN DATEDIFF(CURDATE(), last_membership.end_date)
                ELSE NULL
            END as days_since_last_membership,
            m.contact_number
        FROM `tabMember` m
        LEFT JOIN (
            SELECT
                member,
                name,
                membership_type,
                status,
                COALESCE(cancellation_date, start_date) as end_date,
                ROW_NUMBER() OVER (PARTITION BY member ORDER BY creation DESC) as rn
            FROM `tabMembership`
            WHERE docstatus != 2
        ) last_membership ON m.name = last_membership.member AND last_membership.rn = 1
        WHERE {where_clause}
        AND m.name NOT IN (
            SELECT DISTINCT member
            FROM `tabMembership`
            WHERE status = 'Active'
            AND docstatus != 2
        )
        ORDER BY
            CASE
                WHEN m.status = 'Active' THEN 1
                WHEN m.status = 'Pending' THEN 2
                WHEN m.status = 'Suspended' THEN 3
                WHEN m.status = 'Terminated' THEN 4
                ELSE 5
            END,
            CASE WHEN last_membership.end_date IS NULL THEN 1 ELSE 0 END,
            last_membership.end_date DESC,
            m.member_since DESC
    """

    try:
        return frappe.db.sql(sql_query, as_dict=1)
    except Exception as e:
        frappe.log_error(f"Error in Members Without Active Memberships report: {str(e)}")
        return []


@frappe.whitelist()
def get_report_summary(filters=None):
    """Generate summary statistics for the report"""
    try:
        if filters is None:
            filters = {}
        data = get_data(filters)

        if not data:
            return {"total": 0}

        # Calculate summary statistics
        total_members = len(data)
        by_status = {}

        for row in data:
            # Count by member status
            status = row.get("member_status", "Unknown")
            by_status[status] = by_status.get(status, 0) + 1

            # Count by chapter (skip for now since chapter field removed)
            # chapter = row.get("chapter") or "No Chapter"
            # by_chapter[chapter] = by_chapter.get(chapter, 0) + 1

        return {
            "total": total_members,
            "by_status": by_status,
            # "by_chapter": by_chapter,
            # "top_chapters": sorted(by_chapter.items(), key=lambda x: x[1], reverse=True)[:5]
        }
    except Exception as e:
        frappe.log_error(f"Error generating Members Without Active Memberships summary: {str(e)}")
        return {"error": str(e)}
