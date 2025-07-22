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
    columns = [
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

    # Add dues schedule columns if requested
    if filters and filters.get("include_dues_schedule_info"):
        columns.extend(
            [
                _("Dues Schedule Status") + ":Data:120",
                _("Next Invoice Date") + ":Date:100",
                _("Days Overdue") + ":Int:80",
                _("Billing Frequency") + ":Data:100",
                _("Dues Rate") + ":Currency:100",
                _("Coverage Status") + ":HTML:120",
            ]
        )

    return columns


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
        data = frappe.db.sql(sql_query, as_dict=1)

        # Enhance with dues schedule information if requested
        if filters and filters.get("include_dues_schedule_info"):
            data = enhance_with_dues_schedule_info(data)

        return data
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

        summary = {
            "total": total_members,
            "by_status": by_status,
            # "by_chapter": by_chapter,
            # "top_chapters": sorted(by_chapter.items(), key=lambda x: x[1], reverse=True)[:5]
        }

        # Add dues schedule summary if requested
        if filters and filters.get("include_dues_schedule_info"):
            dues_summary = get_dues_schedule_summary(data)
            summary["dues_schedule_summary"] = dues_summary

        return summary
    except Exception as e:
        frappe.log_error(f"Error generating Members Without Active Memberships summary: {str(e)}")
        return {"error": str(e)}


def enhance_with_dues_schedule_info(data):
    """Enhance member data with dues schedule information"""
    from frappe.utils import date_diff

    enhanced_data = []

    for row in data:
        member_id = row.get("member_id")
        if not member_id:
            enhanced_data.append(row)
            continue

        # Get dues schedule information
        try:
            schedules = frappe.get_all(
                "Membership Dues Schedule",
                filters={"member": member_id, "status": "Active"},
                fields=[
                    "name",
                    "next_invoice_date",
                    "last_invoice_date",
                    "billing_frequency",
                    "dues_rate",
                    "auto_generate",
                ],
                order_by="modified desc",
                limit=1,
            )

            if schedules:
                schedule = schedules[0]
                today_date = getdate(today())

                # Calculate days overdue
                days_overdue = 0
                if schedule.next_invoice_date:
                    next_date = getdate(schedule.next_invoice_date)
                    if next_date < today_date:
                        days_overdue = date_diff(today_date, next_date)

                # Determine coverage status
                coverage_status = "Active"
                status_color = "green"

                if days_overdue > 7:
                    coverage_status = "Critical Gap"
                    status_color = "red"
                elif days_overdue > 0:
                    coverage_status = "Overdue"
                    status_color = "orange"
                elif not schedule.auto_generate:
                    coverage_status = "Manual"
                    status_color = "blue"

                coverage_status_html = f'<span class="indicator {status_color}">{coverage_status}</span>'

                # Add dues schedule fields to row
                row.update(
                    {
                        "dues_schedule_status": "Active" if schedules else "None",
                        "next_invoice_date": schedule.next_invoice_date,
                        "days_overdue": days_overdue,
                        "billing_frequency": schedule.billing_frequency,
                        "dues_rate": schedule.dues_rate,
                        "coverage_status": coverage_status_html,
                    }
                )
            else:
                # No active dues schedule
                row.update(
                    {
                        "dues_schedule_status": "None",
                        "next_invoice_date": None,
                        "days_overdue": 0,
                        "billing_frequency": None,
                        "dues_rate": None,
                        "coverage_status": '<span class="indicator gray">No Schedule</span>',
                    }
                )

        except Exception:
            # On error, add empty dues schedule fields
            row.update(
                {
                    "dues_schedule_status": "Error",
                    "next_invoice_date": None,
                    "days_overdue": 0,
                    "billing_frequency": None,
                    "dues_rate": None,
                    "coverage_status": '<span class="indicator red">Error</span>',
                }
            )

        enhanced_data.append(row)

    return enhanced_data


def get_dues_schedule_summary(data):
    """Generate summary statistics for dues schedule coverage"""
    if not data:
        return {}

    total_members = len(data)
    members_with_schedules = 0
    overdue_schedules = 0
    critical_schedules = 0
    total_overdue_amount = 0

    for row in data:
        if row.get("dues_schedule_status") == "Active":
            members_with_schedules += 1

            days_overdue = row.get("days_overdue", 0)
            if days_overdue > 0:
                overdue_schedules += 1
            if days_overdue > 7:
                critical_schedules += 1

            # Estimate overdue amount (rough calculation)
            if days_overdue > 0 and row.get("dues_rate"):
                rate = float(row.get("dues_rate", 0))
                billing_freq = row.get("billing_frequency", "Daily")

                if billing_freq == "Daily":
                    total_overdue_amount += rate * days_overdue
                elif billing_freq == "Weekly":
                    total_overdue_amount += rate * (days_overdue / 7)
                elif billing_freq == "Monthly":
                    total_overdue_amount += rate * (days_overdue / 30)

    coverage_percentage = (members_with_schedules / total_members * 100) if total_members > 0 else 0

    return {
        "total_members": total_members,
        "members_with_schedules": members_with_schedules,
        "members_without_schedules": total_members - members_with_schedules,
        "coverage_percentage": round(coverage_percentage, 1),
        "overdue_schedules": overdue_schedules,
        "critical_schedules": critical_schedules,
        "estimated_overdue_amount": round(total_overdue_amount, 2),
    }
