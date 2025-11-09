# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import getdate, today

from verenigingen.utils.security.api_security_framework import OperationType, standard_api


def validate_doctype_fields(doctype, required_fields):
    """Validate that required fields exist in DocType for defensive programming"""
    try:
        meta = frappe.get_meta(doctype)
        existing_fields = {field.fieldname for field in meta.fields if field.fieldname}
        # Add implicit fields that always exist on DocTypes
        existing_fields.update(["name", "creation", "modified", "owner", "modified_by", "docstatus"])
        missing_fields = set(required_fields) - existing_fields

        if missing_fields:
            frappe.logger().warning(f"Missing fields in {doctype}: {missing_fields}")
            return False
        return True
    except Exception as e:
        frappe.logger().error(f"Error validating {doctype} fields: {str(e)}")
        return False


def execute(filters=None):
    import time

    start_time = time.time()

    try:
        columns = get_columns(filters)
        data = get_data(filters)

        # Log performance metrics
        execution_time = time.time() - start_time
        frappe.logger().info(
            f"members_without_active_memberships report: {len(data)} rows processed in {execution_time:.2f}s"
        )

        return columns, data

    except Exception as e:
        execution_time = time.time() - start_time
        frappe.logger().error(
            f"members_without_active_memberships report failed after {execution_time:.2f}s: {str(e)}"
        )
        raise


def get_columns(filters):
    columns = [
        _("Member ID") + ":Link/Member:120",
        _("Member Name") + ":Data:180",
        _("Email") + ":Data:200",
        _("Member Status") + ":Data:100",
        _("Member Since") + ":Date:100",
        _("Last Membership ID") + ":Link/Membership:120",
        _("Last Membership Type") + ":Data:120",
        _("Last Membership Status") + ":Data:120",
        _("Last Membership End") + ":Date:100",
        _("Days Since Last Membership") + ":Int:80",
        _("Contact Number") + ":Data:120",
    ]

    # Add chapter column when filtering by chapter
    if filters and filters.get("chapter"):
        columns.insert(5, _("Chapter") + ":Link/Chapter:120")

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

    # Validate required fields exist before proceeding
    required_member_fields = ["name", "full_name", "email", "status", "member_since"]
    required_membership_fields = ["member", "status", "membership_type", "start_date", "creation"]
    required_schedule_fields = ["member", "status", "next_invoice_date", "billing_frequency", "dues_rate"]
    required_chapter_member_fields = ["member", "parent", "enabled", "status"]

    validations = [
        validate_doctype_fields("Member", required_member_fields),
        validate_doctype_fields("Membership", required_membership_fields),
        validate_doctype_fields("Membership Dues Schedule", required_schedule_fields),
    ]

    # Add chapter member validation if chapter filter is used
    if filters.get("chapter"):
        validations.append(validate_doctype_fields("Chapter Member", required_chapter_member_fields))

    if not all(validations):
        frappe.logger().error("Field validation failed in members_without_active_memberships report")
        return []  # Return empty data if validation fails

    # Build dynamic WHERE conditions based on filters
    where_conditions = ["m.docstatus != 2"]  # Exclude cancelled member records

    # Build query parameters for safe SQL execution
    query_params = {}

    # Specific status filter takes precedence over include/exclude filters
    if filters.get("member_status"):
        where_conditions.append("m.status = %(member_status)s")
        query_params["member_status"] = filters.get("member_status")
    else:
        # Build status exclusion list based on filters
        # Always exclude: Rejected, Deceased (these should never show in this report)
        excluded_statuses = ["'Rejected'", "'Deceased'"]

        # Conditionally exclude Terminated and Banned based on include_terminated filter
        if not filters.get("include_terminated"):
            excluded_statuses.extend(["'Terminated'", "'Banned'"])

        # Conditionally exclude Suspended based on include_suspended filter
        if not filters.get("include_suspended"):
            excluded_statuses.append("'Suspended'")

        if excluded_statuses:
            where_conditions.append(f"m.status NOT IN ({', '.join(excluded_statuses)})")

    where_clause = " AND ".join(where_conditions)

    # Add chapter filter if specified
    chapter_join = ""
    chapter_select = ""
    if filters.get("chapter"):
        chapter_join = """
        INNER JOIN `tabChapter Member` cm ON m.name = cm.member
        INNER JOIN `tabChapter` c ON c.name = cm.parent
        """
        chapter_select = "c.name as chapter,"
        where_conditions.append("c.name = %(chapter)s")
        where_conditions.append("cm.enabled = 1")
        where_conditions.append("cm.status = 'Active'")
        query_params["chapter"] = filters.get("chapter")
        where_clause = " AND ".join(where_conditions)

    # Get all members without active memberships
    sql_query = f"""
        SELECT
            m.name as member_id,
            m.full_name as member_name,
            m.email,
            m.status as member_status,
            m.member_since,
            {chapter_select}
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
        {chapter_join}
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
        data = frappe.db.sql(sql_query, query_params, as_dict=1)

        # Enhance with dues schedule information if requested
        if filters and filters.get("include_dues_schedule_info"):
            data = enhance_with_dues_schedule_info(data)

        return data
    except Exception as e:
        frappe.log_error(f"Error in Members Without Active Memberships report: {str(e)}")
        return []


@frappe.whitelist()
@standard_api(operation_type=OperationType.MEMBER_DATA)
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
    """Enhance member data with dues schedule information using batch loading"""
    from frappe.utils import date_diff

    # Batch load all dues schedules to avoid N+1 queries
    member_ids = [row.get("member_id") for row in data if row.get("member_id")]

    if not member_ids:
        return data

    # Get all active dues schedules for all members in single query
    all_schedules = frappe.get_all(
        "Membership Dues Schedule",
        filters={"member": ["in", member_ids], "status": "Active"},
        fields=[
            "member",
            "name",
            "next_invoice_date",
            "last_invoice_date",
            "billing_frequency",
            "dues_rate",
            "auto_generate",
            "modified",
        ],
        order_by="member, modified desc",
    )

    # Group schedules by member for fast lookup
    schedules_by_member = {}
    for schedule in all_schedules:
        member_id = schedule.member
        if member_id not in schedules_by_member:
            # Take the first (most recent) schedule for each member
            schedules_by_member[member_id] = schedule

    enhanced_data = []

    for row in data:
        member_id = row.get("member_id")
        if not member_id:
            enhanced_data.append(row)
            continue

        # Get pre-loaded dues schedule information
        try:
            schedule = schedules_by_member.get(member_id)

            if schedule:
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
                        "dues_schedule_status": "Active",
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

        except Exception as e:
            frappe.logger().error(f"Error processing dues schedule for member {member_id}: {str(e)}")
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
