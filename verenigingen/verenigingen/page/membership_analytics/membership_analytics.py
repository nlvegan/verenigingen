# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

import json
from datetime import datetime, timedelta

import frappe
from frappe.utils import add_months, flt, fmt_money, getdate, now_datetime

from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)
from verenigingen.utils.validation_utilities import DocumentExistenceValidator


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_dashboard_data(
    year=None, period="year", compare_previous=False, cohort_interval="monthly", filters=None
):
    """Get all dashboard data for membership analytics"""
    if not year:
        year = datetime.now().year

    # Ensure year is an integer
    year = int(year)

    from verenigingen.utils.validation.api_validators import parse_json_filters

    filters = parse_json_filters(filters) or {}

    data = {
        "summary": get_summary_metrics(year, period, filters),
        "growth_trend": get_growth_trend(year, period, filters),
        "revenue_projection": get_revenue_projection(year, filters),
        "current_year_revenue": get_current_year_revenue(year),
        "membership_breakdown": get_membership_breakdown(year, filters),
        "goals": get_goals_progress(year),
        "insights": get_top_insights(year),
        "segmentation": get_segmentation_data(year, period, filters),
        "cohort_analysis": get_cohort_analysis(year, cohort_interval),
        "last_updated": now_datetime(),
    }

    if compare_previous:
        data["previous_period"] = get_summary_metrics(year - 1, period, filters)

    return data


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_summary_metrics(year, period="year", filters=None):
    """Get summary metrics for the dashboard header"""
    filters = filters or {}

    # Ensure year is an integer
    year = int(year)

    # Define date range
    if period == "year":
        start_date = f"{year}-01-01"
        end_date = f"{year}-12-31"
    elif period == "quarter":
        # Get current quarter
        current_month = datetime.now().month
        quarter = (current_month - 1) // 3 + 1
        start_month = (quarter - 1) * 3 + 1
        start_date = f"{year}-{start_month:02d}-01"
        end_date = getdate(add_months(start_date, 3)) - timedelta(days=1)
    else:  # month
        current_month = datetime.now().month
        start_date = f"{year}-{current_month:02d}-01"
        end_date = getdate(add_months(start_date, 1)) - timedelta(days=1)

    # Total members active as of the cutoff date
    # For current year: use today's date
    # For past/future years: use December 31st of that year
    from frappe.utils import getdate, nowdate

    current_year = datetime.now().year
    if year == current_year:
        # For current year, count members active as of today
        cutoff_date = nowdate()
    else:
        # For past/future years, count members active as of year-end
        cutoff_date = f"{year}-12-31"

    # Count active and suspended members as of the cutoff date
    # - Joined on or before the cutoff date
    # - Either never terminated, or terminated after the cutoff date
    # - Only Active or Suspended status (excludes Terminated, Banned, Deceased, Rejected)
    total_members = frappe.db.sql(
        """
        SELECT COUNT(*)
        FROM `tabMember`
        WHERE member_since <= %s
            AND status IN ('Active', 'Suspended')
            AND (member_end_date IS NULL OR member_end_date > %s)
        """,
        (cutoff_date, cutoff_date),
    )[0][0]

    # New members in period
    new_members = frappe.db.count(
        "Member", filters={"member_since": ["between", [start_date, end_date]], "status": ["!=", "Rejected"]}
    )

    # Lost members in period - count by member_end_date on Member DocType
    # This captures both formal termination requests AND imported terminated members
    lost_members = frappe.db.count(
        "Member",
        filters={
            "member_end_date": ["between", [start_date, end_date]],
            "status": ["in", ["Terminated", "Banned", "Suspended"]],
        },
    )

    # Net growth
    net_growth = new_members - lost_members

    # Growth rate
    members_at_start = frappe.db.count(
        "Member", filters={"member_since": ["<", start_date], "status": "Active"}
    )

    growth_rate = 0
    if members_at_start > 0:
        growth_rate = (net_growth / members_at_start) * 100

    # Calculate projected annual revenue
    projected_revenue = calculate_projected_revenue(year)

    return {
        "total_members": total_members,
        "new_members": new_members,
        "lost_members": lost_members,
        "net_growth": net_growth,
        "growth_rate": growth_rate,
        "projected_revenue": projected_revenue,
        "period": f"{start_date} to {end_date}",
    }


def calculate_projected_revenue(year):
    """Calculate projected annual revenue for the year following the selected year

    This projects revenue based on:
    - Active Membership Dues Schedules with their billing frequencies
    - Member dues_rate (custom rates) or schedule suggested_amount
    - Excludes members with termination dates within the projection year
    - Annualizes based on billing frequency (Monthly=12x, Quarterly=4x, Yearly=1x)

    Args:
        year: The reference year - will calculate projected revenue for year+1

    Returns:
        float: Projected annual revenue for the following year (year+1)
    """
    # Ensure year is an integer
    year = int(year)

    # Calculate projection for the following year
    from frappe.utils import getdate

    projection_year = year + 1
    projection_start = f"{projection_year}-01-01"
    projection_end = f"{projection_year}-12-31"

    # SQL query to calculate annualized revenue based on billing frequency
    # Includes members who were active during the projection year
    query = """
        SELECT
            SUM(
                CASE
                    WHEN mds.billing_frequency = 'Monthly' THEN
                        COALESCE(m.dues_rate, mds.suggested_amount, 0) * 12
                    WHEN mds.billing_frequency = 'Quarterly' THEN
                        COALESCE(m.dues_rate, mds.suggested_amount, 0) * 4
                    WHEN mds.billing_frequency = 'Yearly' THEN
                        COALESCE(m.dues_rate, mds.suggested_amount, 0)
                    WHEN mds.billing_frequency = 'Custom' THEN
                        -- For custom frequency, calculate based on how many periods fit in a year
                        CASE
                            WHEN mds.custom_frequency_unit = 'Month' THEN
                                COALESCE(m.dues_rate, mds.suggested_amount, 0) * (12 / NULLIF(mds.custom_frequency_number, 0))
                            WHEN mds.custom_frequency_unit = 'Week' THEN
                                COALESCE(m.dues_rate, mds.suggested_amount, 0) * (52 / NULLIF(mds.custom_frequency_number, 0))
                            WHEN mds.custom_frequency_unit = 'Year' THEN
                                COALESCE(m.dues_rate, mds.suggested_amount, 0) / NULLIF(mds.custom_frequency_number, 0)
                            ELSE
                                COALESCE(m.dues_rate, mds.suggested_amount, 0)
                        END
                    ELSE
                        COALESCE(m.dues_rate, mds.suggested_amount, 0)
                END
            ) as total_annual_revenue
        FROM `tabMembership Dues Schedule` mds
        JOIN `tabMember` m ON m.name = mds.member
        WHERE mds.status = 'Active'
            AND mds.is_template = 0
            AND m.status != 'Rejected'
            AND m.member_since <= %s
            AND (m.member_end_date IS NULL OR m.member_end_date > %s)
    """

    try:
        result = frappe.db.sql(query, (projection_end, projection_start), as_dict=True)
        total_revenue = result[0].total_annual_revenue if result and result[0].total_annual_revenue else 0
        return float(total_revenue)
    except Exception as e:
        frappe.log_error(
            f"Error calculating projected revenue: {str(e)}", "Membership Analytics Revenue Projection"
        )
        return 0


def get_current_year_revenue(year):
    """Calculate actual and estimated revenue for the selected year

    Returns both the invoiced revenue (all invoices generated whether paid or not)
    and estimated remaining revenue (pro-rated for members without invoices yet
    generated for the rest of the year).

    This function executes 4 SQL queries:
    1. All membership invoices (invoiced_amount)
    2. Direct payments via Mollie not linked to invoices
    3. Outstanding (unpaid) invoices
    4. Estimated ungenerated dues based on coverage gaps

    Performance Note: On large datasets (500+ members, 5000+ invoices),
    expect 2-5 second execution time.

    Args:
        year: The calendar year to calculate revenue for (int or str)

    Returns:
        dict: {
            'actual_revenue': float,  # All invoiced revenue (paid + unpaid) + direct payments
            'estimated_remaining': float,  # Estimated revenue not yet invoiced
            'total_estimated': float,  # actual + estimated
            'outstanding_invoices': float,  # Unpaid invoices (subset of actual)
            'breakdown': {
                'invoiced_amount': float,
                'direct_payments': float,
                'outstanding_invoices': float,
                'ungenerated_dues': float
            },
            'error': str  # Only present if an error occurred
        }

    Raises:
        ValueError: If year is invalid (caught and returned in error field)
    """
    try:
        year = int(year)
        year_start = f"{year}-01-01"
        year_end = f"{year}-12-31"
    except (ValueError, TypeError) as e:
        frappe.log_error(f"Invalid year parameter: {year}", "Membership Analytics Revenue Error")
        return _get_error_response(f"Invalid year: {str(e)}")

    try:
        # 1. Get all membership invoices for the year (paid or unpaid)
        invoiced_amount_query = """
            SELECT COALESCE(SUM(si.grand_total), 0) as total
            FROM `tabSales Invoice` si
            WHERE si.docstatus = 1
                AND si.posting_date BETWEEN %s AND %s
                AND (si.is_membership_invoice = 1 OR si.member IS NOT NULL)
        """
        invoiced_amount = frappe.db.sql(invoiced_amount_query, (year_start, year_end), as_dict=True)[0].total

        # 2. Get direct dues payments not linked to invoices
        # Get dues keywords and income account from settings
        payment_settings = frappe.get_single("Verenigingen Payments Settings")
        dues_keywords = [
            kw.strip().lower() for kw in (payment_settings.dues_keywords or "contributie").split(",")
        ]

        verenigingen_settings = frappe.get_single("Verenigingen Settings")
        dues_income_account = verenigingen_settings.dues_income_account

        # Build direct payment query considering both keywords and GL account allocation
        # Case 1: Payment Entry with dues keywords in remarks
        # Case 2: Payment Entry with allocation to dues income account
        direct_payments_query = """
            SELECT COALESCE(SUM(DISTINCT pe.paid_amount), 0) as total
            FROM `tabPayment Entry` pe
            LEFT JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
            LEFT JOIN `tabMember` m ON pe.party = m.name
            WHERE pe.docstatus = 1
                AND pe.posting_date BETWEEN %s AND %s
                AND pe.payment_type = 'Receive'
                AND per.name IS NULL
                AND (
                    (m.name IS NOT NULL AND ({keyword_conditions}))
                    {account_condition}
                )
        """

        # Build keyword matching conditions
        keyword_conditions = " OR ".join(["LOWER(pe.remarks) LIKE %s" for _ in dues_keywords])

        # Build account condition if dues_income_account is configured
        account_condition = ""
        params = [year_start, year_end]
        if dues_income_account:
            account_condition = """OR EXISTS (
                SELECT 1 FROM `tabGL Entry` gl
                WHERE gl.voucher_type = 'Payment Entry'
                    AND gl.voucher_no = pe.name
                    AND gl.account = %s
                    AND gl.is_cancelled = 0
            )"""
            params.append(dues_income_account)

        # Add keyword parameters
        keyword_params = [f"%{frappe.db.escape(kw)}%" for kw in dues_keywords]
        params.extend(keyword_params)

        # Format the query with conditions
        direct_payments_query = direct_payments_query.format(
            keyword_conditions=keyword_conditions, account_condition=account_condition
        )

        direct_payments_result = frappe.db.sql(direct_payments_query, tuple(params), as_dict=True)
        direct_payments = direct_payments_result[0].total if direct_payments_result else 0

        # 3. Get outstanding (unpaid) membership invoices
        outstanding_invoices_query = """
            SELECT COALESCE(SUM(si.outstanding_amount), 0) as total
            FROM `tabSales Invoice` si
            WHERE si.docstatus = 1
                AND si.posting_date BETWEEN %s AND %s
                AND si.status IN ('Unpaid', 'Overdue', 'Partly Paid')
                AND (si.is_membership_invoice = 1 OR si.member IS NOT NULL)
        """
        outstanding_invoices = frappe.db.sql(
            outstanding_invoices_query, (year_start, year_end), as_dict=True
        )[0].total

        # 4. Estimate ungenerated dues for remainder of year based on coverage gaps
        # Only estimate for current/future years - past years have all invoices already generated
        from frappe.utils import getdate, now_datetime

        current_year = now_datetime().year
        year_end_date = getdate(year_end)
        days_in_year = (year_end_date - getdate(year_start)).days + 1

        # Skip ungenerated dues estimation for past years
        if year < current_year:
            ungenerated_dues = 0
        else:
            ungenerated_dues_query = """
            SELECT
                    SUM(
                        CASE
                            -- Calculate days in year not covered by invoices
                            -- Use GREATEST to ensure we don't estimate before member joined
                            WHEN GREATEST(COALESCE(last_coverage.coverage_end, %s), COALESCE(m.member_since, %s)) < %s THEN
                            CASE
                                WHEN mds.billing_frequency = 'Monthly' THEN
                                    COALESCE(m.dues_rate, mds.suggested_amount, 0) *
                                    (12.0 * DATEDIFF(%s, GREATEST(COALESCE(last_coverage.coverage_end, %s), COALESCE(m.member_since, %s))) / %s)
                                WHEN mds.billing_frequency = 'Quarterly' THEN
                                    COALESCE(m.dues_rate, mds.suggested_amount, 0) *
                                    (4.0 * DATEDIFF(%s, GREATEST(COALESCE(last_coverage.coverage_end, %s), COALESCE(m.member_since, %s))) / %s)
                                WHEN mds.billing_frequency = 'Yearly' THEN
                                    COALESCE(m.dues_rate, mds.suggested_amount, 0) *
                                    (1.0 * DATEDIFF(%s, GREATEST(COALESCE(last_coverage.coverage_end, %s), COALESCE(m.member_since, %s))) / %s)
                                WHEN mds.billing_frequency = 'Custom' THEN
                                    -- Handle custom billing frequencies
                                    CASE
                                        WHEN mds.custom_frequency_unit = 'Month' THEN
                                            COALESCE(m.dues_rate, mds.suggested_amount, 0) *
                                            ((12.0 / NULLIF(mds.custom_frequency_number, 0)) * DATEDIFF(%s, GREATEST(COALESCE(last_coverage.coverage_end, %s), COALESCE(m.member_since, %s))) / %s)
                                        WHEN mds.custom_frequency_unit = 'Week' THEN
                                            COALESCE(m.dues_rate, mds.suggested_amount, 0) *
                                            ((52.0 / NULLIF(mds.custom_frequency_number, 0)) * DATEDIFF(%s, GREATEST(COALESCE(last_coverage.coverage_end, %s), COALESCE(m.member_since, %s))) / %s)
                                        WHEN mds.custom_frequency_unit = 'Year' THEN
                                            COALESCE(m.dues_rate, mds.suggested_amount, 0) *
                                            ((1.0 / NULLIF(mds.custom_frequency_number, 0)) * DATEDIFF(%s, GREATEST(COALESCE(last_coverage.coverage_end, %s), COALESCE(m.member_since, %s))) / %s)
                                        ELSE
                                            0
                                    END
                                ELSE
                                    0
                            END
                        ELSE
                            0
                    END
                ) as total
            FROM `tabMembership Dues Schedule` mds
            JOIN `tabMember` m ON m.name = mds.member
            LEFT JOIN (
                SELECT
                    member,
                    MAX(custom_coverage_end_date) as coverage_end
                FROM `tabSales Invoice`
                WHERE docstatus = 1
                    AND YEAR(posting_date) = %s
                GROUP BY member
            ) as last_coverage ON last_coverage.member = m.name
            WHERE mds.status = 'Active'
                AND mds.is_template = 0
                AND m.status = 'Active'
                AND (m.member_end_date IS NULL OR m.member_end_date > %s)
        """
            ungenerated_dues = (
                frappe.db.sql(
                    ungenerated_dues_query,
                    (
                        year_start,
                        year_start,
                        year_end,  # for GREATEST/COALESCE checks (coverage_end default, member_since default, year_end comparison)
                        year_end,
                        year_start,
                        year_start,
                        days_in_year,  # Monthly (year_end, coverage_end default, member_since default, days)
                        year_end,
                        year_start,
                        year_start,
                        days_in_year,  # Quarterly
                        year_end,
                        year_start,
                        year_start,
                        days_in_year,  # Yearly
                        year_end,
                        year_start,
                        year_start,
                        days_in_year,  # Custom: Month
                        year_end,
                        year_start,
                        year_start,
                        days_in_year,  # Custom: Week
                        year_end,
                        year_start,
                        year_start,
                        days_in_year,  # Custom: Year
                        year,  # for filtering invoices by year
                        year_end,  # for member_end_date check
                    ),
                    as_dict=True,
                )[0].total
                or 0
            )

        # Actual revenue = all invoiced amounts (whether paid or not) + direct payments
        actual_revenue = float(invoiced_amount) + float(direct_payments)
        # Estimated remaining = only the ungenerated portion
        estimated_remaining = float(ungenerated_dues)

        return {
            "actual_revenue": actual_revenue,
            "estimated_remaining": estimated_remaining,
            "total_estimated": actual_revenue + estimated_remaining,
            "outstanding_invoices": float(outstanding_invoices),
            "breakdown": {
                "invoiced_amount": float(invoiced_amount),
                "direct_payments": float(direct_payments),
                "outstanding_invoices": float(outstanding_invoices),
                "ungenerated_dues": float(ungenerated_dues),
            },
        }

    except Exception as e:
        frappe.log_error(
            f"Error calculating current year revenue for {year}: {str(e)}\n{frappe.get_traceback()}",
            "Membership Analytics Revenue Error",
        )
        return _get_error_response(str(e))


def _get_error_response(error_message):
    """Helper to return consistent error response structure"""
    return {
        "actual_revenue": 0,
        "estimated_remaining": 0,
        "total_estimated": 0,
        "outstanding_invoices": 0,
        "breakdown": {
            "invoiced_amount": 0,
            "direct_payments": 0,
            "outstanding_invoices": 0,
            "ungenerated_dues": 0,
        },
        "error": error_message,
    }


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_growth_trend(year, period="year", filters=None):
    """Get member growth trend data for charts"""
    filters = filters or {}
    growth_data = []

    # Ensure year is an integer
    year = int(year)

    if period == "year":
        # Monthly data for the year
        for month in range(1, 13):
            start_date = f"{year}-{month:02d}-01"
            end_date = getdate(add_months(start_date, 1)) - timedelta(days=1)

            new_members = frappe.db.count(
                "Member", filters={"member_since": ["between", [start_date, end_date]]}
            )

            # Count lost members by member_end_date to include imported terminated members
            lost_members = frappe.db.count(
                "Member",
                filters={
                    "member_end_date": ["between", [start_date, end_date]],
                    "status": ["in", ["Terminated", "Banned", "Suspended"]],
                },
            )

            growth_data.append(
                {
                    "period": datetime(year, month, 1).strftime("%B"),
                    "new_members": new_members,
                    "lost_members": lost_members,
                    "net_growth": new_members - lost_members,
                }
            )

    return growth_data


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def get_revenue_projection(year, filters=None):
    """Get revenue by membership type for a specific year

    Calculates actual revenue from invoices for the selected year,
    grouped by membership type.
    """
    filters = filters or {}

    # Ensure year is an integer
    year = int(year)
    year_start = f"{year}-01-01"
    year_end = f"{year}-12-31"

    membership_types = frappe.get_all(
        "Membership Type", filters={"is_active": 1}, fields=["name", "minimum_amount"]
    )

    revenue_data = []

    for mt in membership_types:
        # Get actual revenue from invoices for this membership type in the selected year
        result = frappe.db.sql(
            """
            SELECT
                COUNT(DISTINCT si.member) as count,
                SUM(si.grand_total) as revenue
            FROM `tabSales Invoice` si
            JOIN `tabMember` mem ON si.member = mem.name
            JOIN `tabMembership` m ON m.member = mem.name AND m.status = 'Active'
            WHERE si.docstatus = 1
                AND si.posting_date BETWEEN %s AND %s
                AND (si.is_membership_invoice = 1 OR si.member IS NOT NULL)
                AND m.membership_type = %s
        """,
            (year_start, year_end, mt.name),
            as_dict=True,
        )[0]

        revenue_data.append(
            {
                "membership_type": mt.name,
                "member_count": result.count or 0,
                "revenue": result.revenue or 0,
                "average_fee": (result.revenue / result.count) if result.count else mt.minimum_amount,
            }
        )

    return revenue_data


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_membership_breakdown(year, filters=None):
    """Get membership breakdown by type for a specific year

    Returns membership type distribution based on:
    - Members who were active at some point during the specified year
    - Members who joined before or during the year
    - Members who hadn't yet terminated before the year started
    """
    from frappe.query_builder import Case
    from frappe.query_builder.functions import Coalesce, Count, Sum

    filters = filters or {}

    # Ensure year is an integer
    year = int(year)
    year_start = f"{year}-01-01"
    year_end = f"{year}-12-31"

    Membership = frappe.qb.DocType("Membership")
    Member = frappe.qb.DocType("Member")
    MembershipType = frappe.qb.DocType("Membership Type")

    query = (
        frappe.qb.from_(Membership)
        .join(Member)
        .on(Membership.member == Member.name)
        .join(MembershipType)
        .on(Membership.membership_type == MembershipType.name)
        .select(
            Membership.membership_type,
            Count(Membership.member).distinct().as_("count"),
            Sum(Coalesce(Member.dues_rate, MembershipType.minimum_amount)).as_("revenue"),
        )
        .where(Membership.status == "Active")
        .where(Member.member_since <= year_end)
        .where((Member.member_end_date.isnull()) | (Member.member_end_date >= year_start))
        .groupby(Membership.membership_type)
    )

    breakdown = query.run(as_dict=True)
    return breakdown


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_goals_progress(year):
    """Get progress on membership goals"""

    # Ensure year is an integer
    year = int(year)
    goals = frappe.get_all(
        "Membership Goal",
        filters={"goal_year": year, "status": ["in", ["Active", "In Progress", "Achieved"]]},
        fields=[
            "name",
            "goal_name",
            "goal_type",
            "target_value",
            "current_value",
            "achievement_percentage",
            "status",
        ],
    )

    # Update achievement for each goal
    for goal in goals:
        goal_doc = frappe.get_doc("Membership Goal", goal.name)
        goal_doc.update_achievement()
        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        save_result = secure_document_operation(
            operation="save",
            doc=goal_doc,
            justification=f"Update achievement for membership goal {goal_doc.name} in analytics dashboard",
            required_permissions=["Membership Goal:write"],
        )

        if not save_result.success:
            frappe.log_error(f"Could not update goal {goal_doc.name}: Permission denied")
            continue

        goal.current_value = goal_doc.current_value
        goal.achievement_percentage = goal_doc.achievement_percentage
        goal.status = goal_doc.status

    return goals


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_top_insights(year):
    """Get AI-like insights based on data analysis"""

    # Ensure year is an integer
    year = int(year)
    insights = []

    # Get growth by chapter using Chapter Member relationship
    chapter_growth = frappe.db.sql(
        """
        SELECT
            c.name as chapter,
            COUNT(DISTINCT m.name) as new_members
        FROM `tabMember` m
        JOIN `tabChapter Member` cm ON cm.member = m.name
        JOIN `tabChapter` c ON c.name = cm.parent
        WHERE m.member_since BETWEEN %s AND %s
        AND cm.status = 'Active'
        GROUP BY c.name
        ORDER BY new_members DESC
        LIMIT 1
    """,
        (f"{year}-01-01", f"{year}-12-31"),
        as_dict=True,
    )

    if chapter_growth:
        avg_growth = frappe.db.sql(
            """
            SELECT AVG(member_count) as avg_count
            FROM (
                SELECT COUNT(DISTINCT m.name) as member_count
                FROM `tabMember` m
                JOIN `tabChapter Member` cm ON cm.member = m.name
                JOIN `tabChapter` c ON c.name = cm.parent
                WHERE m.member_since BETWEEN %s AND %s
                AND cm.status = 'Active'
                GROUP BY c.name
            ) as chapter_counts
        """,
            (f"{year}-01-01", f"{year}-12-31"),
        )[0][0]

        if avg_growth and chapter_growth[0].new_members > avg_growth * 1.15:
            growth_pct = ((chapter_growth[0].new_members - avg_growth) / avg_growth) * 100
            insights.append(
                {
                    "type": "success",
                    "message": f"Chapter {chapter_growth[0].chapter} growing {growth_pct:.0f}% faster than average",
                }
            )

    # Check retention improvements
    current_retention = calculate_retention_rate(year)
    previous_retention = calculate_retention_rate(year - 1)

    if current_retention > previous_retention:
        improvement = current_retention - previous_retention
        insights.append(
            {
                "type": "success",
                "message": f"Member retention improved by {improvement:.1f}% compared to last year",
            }
        )

    # Identify at-risk members (simplified version)
    # Note: last_activity field was removed - using last_duration_update as alternative
    at_risk_count = frappe.db.count(
        "Member", filters={"status": "Active", "last_duration_update": ["<", getdate() - timedelta(days=90)]}
    )

    if at_risk_count > 0:
        insights.append(
            {"type": "warning", "message": f"{at_risk_count} members at risk of churning (inactive >90 days)"}
        )

    return insights


def calculate_retention_rate(year):
    """Calculate retention rate for a year"""

    # Ensure year is an integer
    year = int(year)
    start_date = f"{year}-01-01"
    end_date = f"{year}-12-31"

    members_at_start = frappe.db.count(
        "Member", filters={"member_since": ["<", start_date], "status": ["!=", "Terminated"]}
    )

    if members_at_start == 0:
        return 0

    # Count terminated members by member_end_date to include all terminations
    terminated = frappe.db.count(
        "Member",
        filters={
            "member_end_date": ["between", [start_date, end_date]],
            "status": ["in", ["Terminated", "Banned", "Suspended"]],
        },
    )

    return ((members_at_start - terminated) / members_at_start) * 100


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def create_goal(goal_data):
    """Create a new membership goal"""
    if isinstance(goal_data, str):
        goal_data = json.loads(goal_data)

    goal = frappe.get_doc({"doctype": "Membership Goal", **goal_data})

    goal.insert()
    frappe.db.commit()

    return goal.name


@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def get_segmentation_data(year, period="year", filters=None):
    """Get detailed segmentation data"""
    filters = filters or {}

    # Ensure year is an integer
    year = int(year)

    # Apply filters to base query
    filter_conditions = build_filter_conditions(filters)

    segmentation = {
        "by_chapter": get_chapter_segmentation(year, filter_conditions),
        "by_region": get_region_segmentation(year, filter_conditions),
        "by_age": get_age_segmentation(year, filter_conditions),
        "by_payment_method": get_payment_method_segmentation(year, filter_conditions),
        "by_join_year": get_join_year_segmentation(year, filter_conditions),
    }

    return segmentation


def build_filter_conditions(filters):
    """Build SQL conditions from filters"""
    conditions = []

    if filters.get("chapter"):
        conditions.append(
            f"EXISTS (SELECT 1 FROM `tabChapter Member` cm JOIN `tabChapter` c ON c.name = cm.parent WHERE cm.member = m.name AND c.name = '{filters['chapter']}' AND cm.status = 'Active')"
        )

    if filters.get("membership_type"):
        conditions.append(
            f"EXISTS (SELECT 1 FROM `tabMembership` ms WHERE ms.member = m.name AND ms.membership_type = '{filters['membership_type']}' AND ms.status = 'Active')"
        )

    if filters.get("age_group"):
        age_condition = get_age_group_condition(filters["age_group"])
        if age_condition:
            conditions.append(age_condition)

    if filters.get("region"):
        conditions.append(
            f"EXISTS (SELECT 1 FROM `tabAddress` a WHERE a.name = m.primary_address AND {get_region_condition(filters['region'])})"
        )

    return " AND " + " AND ".join(conditions) if conditions else ""


def get_age_group_condition(age_group):
    """Get SQL condition for age group"""
    conditions = {
        "Under 25": "TIMESTAMPDIFF(YEAR, birth_date, CURDATE()) < 25",
        "25-34": "TIMESTAMPDIFF(YEAR, birth_date, CURDATE()) BETWEEN 25 AND 34",
        "35-44": "TIMESTAMPDIFF(YEAR, birth_date, CURDATE()) BETWEEN 35 AND 44",
        "45-54": "TIMESTAMPDIFF(YEAR, birth_date, CURDATE()) BETWEEN 45 AND 54",
        "55-64": "TIMESTAMPDIFF(YEAR, birth_date, CURDATE()) BETWEEN 55 AND 64",
        "65+": "TIMESTAMPDIFF(YEAR, birth_date, CURDATE()) >= 65",
    }
    return conditions.get(age_group)


def get_region_condition(region):
    """Get SQL condition for region based on postal code"""
    regions = {
        "Noord-Holland": "LEFT(pincode, 2) BETWEEN '10' AND '19'",
        "Zuid-Holland": "LEFT(pincode, 2) BETWEEN '20' AND '29'",
        "Utrecht": "LEFT(pincode, 2) BETWEEN '30' AND '39'",
        "Gelderland": "LEFT(pincode, 2) BETWEEN '40' AND '49'",
        "Noord-Brabant": "LEFT(pincode, 2) BETWEEN '50' AND '59'",
        "Limburg": "LEFT(pincode, 2) BETWEEN '60' AND '69'",
        "Zeeland": "LEFT(pincode, 2) BETWEEN '70' AND '79'",
        "Overijssel": "LEFT(pincode, 2) BETWEEN '80' AND '89'",
        "Groningen": "LEFT(pincode, 2) BETWEEN '90' AND '99'",
    }
    return regions.get(region, "1=1")


def get_chapter_segmentation(year, filter_conditions):
    """Get member distribution by chapter for a specific year"""
    from frappe.query_builder import Case, Criterion
    from frappe.query_builder.functions import Avg, Coalesce, Count, Sum
    from pypika import CustomFunction
    from pypika.terms import ValueWrapper

    # Ensure year is an integer
    year = int(year)
    year_start = f"{year}-01-01"
    year_end = f"{year}-12-31"

    Member = frappe.qb.DocType("Member")
    ChapterMember = frappe.qb.DocType("Chapter Member")
    Chapter = frappe.qb.DocType("Chapter")
    Membership = frappe.qb.DocType("Membership")
    MembershipType = frappe.qb.DocType("Membership Type")

    # Custom function for YEAR()
    Year = CustomFunction("YEAR", ["date"])

    # Subquery for membership type minimum amount
    mt_subquery = (
        frappe.qb.from_(Membership)
        .join(MembershipType)
        .on(Membership.membership_type == MembershipType.name)
        .select(MembershipType.minimum_amount)
        .where(Membership.member == Member.name)
        .where(Membership.status == "Active")
        .limit(1)
    )

    # Build the query without ORDER BY first
    query = (
        frappe.qb.from_(Member)
        .left_join(ChapterMember)
        .on((ChapterMember.member == Member.name) & (ChapterMember.status == "Active"))
        .left_join(Chapter)
        .on(Chapter.name == ChapterMember.parent)
        .select(
            Coalesce(Chapter.name, "No Chapter").as_("name"),
            Count(Member.name).distinct().as_("total_members"),
            Sum(Case().when(Year(Member.member_since) == year, 1).else_(0)).as_("new_members"),
            Avg(Coalesce(Member.dues_rate, mt_subquery, 0)).as_("avg_fee"),
        )
        .where(Member.member_since <= year_end)
        .where((Member.member_end_date.isnull()) | (Member.member_end_date >= year_start))
        .where(Member.status.notin(["Rejected", "Terminated", "Banned", "Deceased"]))
        .groupby(Chapter.name)
    )

    # Execute query and sort in Python instead of SQL
    # This avoids the ORDER BY alias issue with query builder
    results = query.run(as_dict=True)
    results.sort(key=lambda x: x.get("total_members", 0), reverse=True)

    return results


def get_region_segmentation(year, filter_conditions):
    """Get member distribution by region for a specific year"""
    from frappe.query_builder import Case
    from frappe.query_builder.functions import Count, Sum
    from pypika import CustomFunction

    # Ensure year is an integer
    year = int(year)
    year_start = f"{year}-01-01"
    year_end = f"{year}-12-31"

    Member = frappe.qb.DocType("Member")
    Address = frappe.qb.DocType("Address")

    # Custom functions
    Year = CustomFunction("YEAR", ["date"])
    Left = CustomFunction("LEFT", ["string", "length"])

    # Build region case statement
    postal_prefix = Left(Address.pincode, 2)
    region_case = (
        Case()
        .when(postal_prefix.between("10", "19"), "Noord-Holland")
        .when(postal_prefix.between("20", "29"), "Zuid-Holland")
        .when(postal_prefix.between("30", "39"), "Utrecht")
        .when(postal_prefix.between("40", "49"), "Gelderland")
        .when(postal_prefix.between("50", "59"), "Noord-Brabant")
        .when(postal_prefix.between("60", "69"), "Limburg")
        .when(postal_prefix.between("70", "79"), "Zeeland")
        .when(postal_prefix.between("80", "89"), "Overijssel")
        .when(postal_prefix.between("90", "99"), "Groningen")
        .else_("Other")
    )

    query = (
        frappe.qb.from_(Member)
        .left_join(Address)
        .on(Member.primary_address == Address.name)
        .select(
            region_case.as_("name"),
            Count(Member.name).distinct().as_("total_members"),
            Sum(Case().when(Year(Member.member_since) == year, 1).else_(0)).as_("new_members"),
        )
        .where(Member.member_since <= year_end)
        .where((Member.member_end_date.isnull()) | (Member.member_end_date >= year_start))
        .where(Member.status.notin(["Rejected", "Terminated", "Banned", "Deceased"]))
        .groupby(region_case)
    )

    results = query.run(as_dict=True)
    results.sort(key=lambda x: x.get("total_members", 0), reverse=True)

    return results


def get_age_segmentation(year, filter_conditions):
    """Get member distribution by age group for a specific year

    Age is calculated as of the end of the specified year.
    """
    # Ensure year is an integer
    year = int(year)
    year_start = f"{year}-01-01"
    year_end = f"{year}-12-31"

    # For age segmentation, the TIMESTAMPDIFF function is complex enough
    # that using raw SQL is cleaner than fighting with query builder
    query = f"""
        SELECT
            CASE
                WHEN TIMESTAMPDIFF(YEAR, birth_date, '{year_end}') < 25 THEN 'Under 25'
                WHEN TIMESTAMPDIFF(YEAR, birth_date, '{year_end}') BETWEEN 25 AND 34 THEN '25-34'
                WHEN TIMESTAMPDIFF(YEAR, birth_date, '{year_end}') BETWEEN 35 AND 44 THEN '35-44'
                WHEN TIMESTAMPDIFF(YEAR, birth_date, '{year_end}') BETWEEN 45 AND 54 THEN '45-54'
                WHEN TIMESTAMPDIFF(YEAR, birth_date, '{year_end}') BETWEEN 55 AND 64 THEN '55-64'
                WHEN TIMESTAMPDIFF(YEAR, birth_date, '{year_end}') >= 65 THEN '65+'
                ELSE 'Unknown'
            END as name,
            COUNT(*) as total_members,
            AVG(COALESCE(m.dues_rate,
                (SELECT minimum_amount FROM `tabMembership Type` mt
                 JOIN `tabMembership` ms ON ms.membership_type = mt.name
                 WHERE ms.member = m.name AND ms.status = 'Active'
                 LIMIT 1), 0)) as avg_fee
        FROM `tabMember` m
        WHERE m.member_since <= '{year_end}'
            AND (m.member_end_date IS NULL OR m.member_end_date >= '{year_start}')
            AND m.status NOT IN ('Rejected', 'Terminated', 'Banned', 'Deceased')
            AND birth_date IS NOT NULL {filter_conditions}
        GROUP BY
            CASE
                WHEN TIMESTAMPDIFF(YEAR, birth_date, '{year_end}') < 25 THEN 'Under 25'
                WHEN TIMESTAMPDIFF(YEAR, birth_date, '{year_end}') BETWEEN 25 AND 34 THEN '25-34'
                WHEN TIMESTAMPDIFF(YEAR, birth_date, '{year_end}') BETWEEN 35 AND 44 THEN '35-44'
                WHEN TIMESTAMPDIFF(YEAR, birth_date, '{year_end}') BETWEEN 45 AND 54 THEN '45-54'
                WHEN TIMESTAMPDIFF(YEAR, birth_date, '{year_end}') BETWEEN 55 AND 64 THEN '55-64'
                WHEN TIMESTAMPDIFF(YEAR, birth_date, '{year_end}') >= 65 THEN '65+'
                ELSE 'Unknown'
            END
    """

    results = frappe.db.sql(query, as_dict=True)

    # Sort results in the proper age order
    age_order = ["Under 25", "25-34", "35-44", "45-54", "55-64", "65+", "Unknown"]
    results.sort(key=lambda x: age_order.index(x["name"]) if x["name"] in age_order else len(age_order))

    return results


def get_payment_method_segmentation(year, filter_conditions):
    """Get member distribution by payment method for a specific year"""
    from frappe.query_builder import Case
    from frappe.query_builder.functions import Coalesce, Count, Sum
    from pypika import CustomFunction

    # Ensure year is an integer
    year = int(year)
    year_start = f"{year}-01-01"
    year_end = f"{year}-12-31"

    Member = frappe.qb.DocType("Member")

    # Custom function for YEAR()
    Year = CustomFunction("YEAR", ["date"])

    query = (
        frappe.qb.from_(Member)
        .select(
            Coalesce(Member.payment_method, "Not Set").as_("name"),
            Count("*").as_("total_members"),
            Sum(Case().when(Year(Member.member_since) == year, 1).else_(0)).as_("new_members"),
        )
        .where(Member.member_since <= year_end)
        .where((Member.member_end_date.isnull()) | (Member.member_end_date >= year_start))
        .where(Member.status.notin(["Rejected", "Terminated", "Banned", "Deceased"]))
        .groupby(Member.payment_method)
    )

    results = query.run(as_dict=True)
    results.sort(key=lambda x: x.get("total_members", 0), reverse=True)

    return results


def get_join_year_segmentation(year, filter_conditions):
    """Get member distribution by join year for a specific year

    Shows historical join years for members who were active during the specified year.
    """
    from frappe.query_builder.functions import Avg, Coalesce, Count
    from pypika import CustomFunction

    # Ensure year is an integer
    year = int(year)
    year_start = f"{year}-01-01"
    year_end = f"{year}-12-31"

    Member = frappe.qb.DocType("Member")
    Membership = frappe.qb.DocType("Membership")
    MembershipType = frappe.qb.DocType("Membership Type")

    # Custom function for YEAR()
    Year = CustomFunction("YEAR", ["date"])

    # Subquery for membership type minimum amount
    mt_subquery = (
        frappe.qb.from_(Membership)
        .join(MembershipType)
        .on(Membership.membership_type == MembershipType.name)
        .select(MembershipType.minimum_amount)
        .where(Membership.member == Member.name)
        .where(Membership.status == "Active")
        .limit(1)
    )

    join_year = Year(Member.member_since)

    query = (
        frappe.qb.from_(Member)
        .select(
            join_year.as_("name"),
            Count("*").as_("total_members"),
            Avg(Member.total_membership_days).as_("avg_tenure_days"),
            Avg(Coalesce(Member.dues_rate, mt_subquery, 0)).as_("avg_fee"),
        )
        .where(Member.member_since <= year_end)
        .where((Member.member_end_date.isnull()) | (Member.member_end_date >= year_start))
        .where(Member.status.notin(["Rejected", "Terminated", "Banned", "Deceased"]))
        .where(Member.member_since.isnotnull())
        .groupby(join_year)
    )

    results = query.run(as_dict=True)
    # Sort by join year descending and limit to 10
    results.sort(key=lambda x: x.get("name", 0), reverse=True)

    return results[:10]


@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def get_cohort_analysis(year=None, cohort_interval="monthly"):
    """Get cohort retention analysis

    Args:
        year: Ignored - kept for API compatibility
        cohort_interval: 'monthly' or 'yearly' cohort grouping
    """
    cohorts = []

    # Get the earliest member_since date
    earliest_date = frappe.db.sql(
        """
        SELECT MIN(member_since) as earliest
        FROM `tabMember`
        WHERE member_since IS NOT NULL
        AND status != 'Rejected'
        """,
        as_dict=True,
    )[0].earliest

    if not earliest_date:
        return []

    # Determine cohort periods based on interval
    if cohort_interval == "yearly":
        return _get_yearly_cohorts(earliest_date)
    else:
        return _get_monthly_cohorts(earliest_date)


def _get_monthly_cohorts(earliest_date):
    """Generate monthly cohorts from earliest_date to now"""
    cohorts = []
    current_date = datetime.now()
    cohort_date = datetime(earliest_date.year, earliest_date.month, 1)

    while cohort_date <= current_date:
        # Get initial cohort size
        initial_count = frappe.db.sql(
            """
            SELECT COUNT(*)
            FROM `tabMember`
            WHERE DATE_FORMAT(member_since, '%%Y-%%m') = %s
            AND status != 'Rejected'
            """,
            cohort_date.strftime("%Y-%m"),
        )[0][0]

        if initial_count > 0:
            cohort_data = {
                "cohort": cohort_date.strftime("%b %Y"),
                "initial": initial_count,
                "retention": [],
            }

            # Calculate retention for each subsequent month up to now
            months_since_cohort = (
                (current_date.year - cohort_date.year) * 12 + current_date.month - cohort_date.month
            )

            for month_offset in range(0, min(months_since_cohort + 1, 36)):  # Cap at 36 months
                check_date = add_months(cohort_date, month_offset)

                retained = frappe.db.sql(
                    """
                    SELECT COUNT(*)
                    FROM `tabMember` m
                    WHERE DATE_FORMAT(member_since, '%%Y-%%m') = %s
                    AND (member_end_date IS NULL OR member_end_date > %s)
                    """,
                    (cohort_date.strftime("%Y-%m"), check_date),
                )[0][0]

                retention_rate = (retained / initial_count) * 100 if initial_count > 0 else 0
                cohort_data["retention"].append(
                    {"month": month_offset, "rate": retention_rate, "count": retained}
                )

            cohorts.append(cohort_data)

        # Move to next month
        cohort_date = add_months(cohort_date, 1)

    return cohorts


def _get_yearly_cohorts(earliest_date):
    """Generate yearly cohorts from earliest_date to now"""
    cohorts = []
    current_date = datetime.now()
    cohort_year = earliest_date.year

    while cohort_year <= current_date.year:
        # Get initial cohort size for the year
        initial_count = frappe.db.sql(
            """
            SELECT COUNT(*)
            FROM `tabMember`
            WHERE YEAR(member_since) = %s
            AND status != 'Rejected'
            """,
            cohort_year,
        )[0][0]

        if initial_count > 0:
            cohort_data = {
                "cohort": str(cohort_year),
                "initial": initial_count,
                "retention": [],
            }

            # Calculate retention for each subsequent year
            years_since_cohort = current_date.year - cohort_year

            for year_offset in range(0, min(years_since_cohort + 1, 10)):  # Cap at 10 years
                check_year = cohort_year + year_offset
                end_of_check_year = f"{check_year}-12-31"

                retained = frappe.db.sql(
                    """
                    SELECT COUNT(*)
                    FROM `tabMember` m
                    WHERE YEAR(member_since) = %s
                    AND (member_end_date IS NULL OR member_end_date > %s)
                    """,
                    (cohort_year, end_of_check_year),
                )[0][0]

                retention_rate = (retained / initial_count) * 100 if initial_count > 0 else 0
                cohort_data["retention"].append(
                    {"year": year_offset, "rate": retention_rate, "count": retained}
                )

            cohorts.append(cohort_data)

        cohort_year += 1

    return cohorts


@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def export_dashboard_data(year=None, period="year", format="excel"):
    """Export dashboard data in various formats"""
    data = get_dashboard_data(year, period)

    if format == "excel":
        return export_to_excel(data)
    elif format == "pdf":
        return export_to_pdf(data)
    elif format == "csv":
        return export_to_csv(data)
    else:
        return data


def export_to_excel(data):
    """Export data to Excel format"""
    from frappe.utils.xlsxutils import make_xlsx

    # Prepare data for Excel
    sheets = {
        "Summary": prepare_summary_sheet(data),
        "Growth Trend": prepare_growth_sheet(data),
        "Segmentation": prepare_segmentation_sheet(data),
        "Cohort Analysis": prepare_cohort_sheet(data),
    }

    xlsx_data = make_xlsx(sheets, "Membership Analytics")

    frappe.response["filename"] = f"membership_analytics_{frappe.utils.today()}.xlsx"
    frappe.response["filecontent"] = xlsx_data.getvalue()
    frappe.response["type"] = "binary"


def export_to_pdf(data):
    """Export data to PDF format"""
    # For now, return a message that PDF export is under development
    # In a full implementation, you would use reportlab or similar
    frappe.throw("PDF export is under development")


def export_to_csv(data):
    """Export summary data to CSV format"""
    import csv
    from io import StringIO

    output = StringIO()
    writer = csv.writer(output)

    # Write summary data
    writer.writerow(["Membership Analytics Summary"])
    writer.writerow(["Generated on", frappe.utils.now()])
    writer.writerow([])

    summary = data.get("summary", {})
    writer.writerow(["Metric", "Value"])
    writer.writerow(["Total Members", summary.get("total_members", 0)])
    writer.writerow(["New Members", summary.get("new_members", 0)])
    writer.writerow(["Lost Members", summary.get("lost_members", 0)])
    writer.writerow(["Net Growth", summary.get("net_growth", 0)])
    writer.writerow(["Growth Rate", f"{summary.get('growth_rate', 0):.1f}%"])
    writer.writerow(["Projected Revenue", summary.get("projected_revenue", 0)])
    writer.writerow([])

    # Growth trend
    writer.writerow(["Growth Trend"])
    writer.writerow(["Period", "New Members", "Lost Members", "Net Growth"])
    for item in data.get("growth_trend", []):
        writer.writerow(
            [
                item.get("period"),
                item.get("new_members", 0),
                item.get("lost_members", 0),
                item.get("net_growth", 0),
            ]
        )

    frappe.response["filename"] = f"membership_analytics_{frappe.utils.today()}.csv"
    frappe.response["filecontent"] = output.getvalue()
    frappe.response["type"] = "download"


def prepare_summary_sheet(data):
    """Prepare summary data for Excel export"""
    summary = data.get("summary", {})
    return [
        ["Metric", "Value"],
        ["Total Members", summary.get("total_members", 0)],
        ["New Members", summary.get("new_members", 0)],
        ["Lost Members", summary.get("lost_members", 0)],
        ["Net Growth", summary.get("net_growth", 0)],
        ["Growth Rate", f"{summary.get('growth_rate', 0):.1f}%"],
        ["Projected Revenue", summary.get("projected_revenue", 0)],
    ]


def prepare_growth_sheet(data):
    """Prepare growth trend data for Excel export"""
    growth = data.get("growth_trend", [])
    headers = ["Period", "New Members", "Lost Members", "Net Growth"]
    rows = [headers]

    for item in growth:
        rows.append(
            [
                item.get("period"),
                item.get("new_members", 0),
                item.get("lost_members", 0),
                item.get("net_growth", 0),
            ]
        )

    return rows


def prepare_segmentation_sheet(data):
    """Prepare segmentation data for Excel export"""
    seg = data.get("segmentation", {})
    rows = [["Segmentation Analysis"]]

    # By Chapter
    rows.extend([[], ["By Chapter"], ["Chapter", "Total Members", "New Members", "Avg Fee"]])
    for item in seg.get("by_chapter", []):
        rows.append(
            [
                item.get("name"),
                item.get("total_members", 0),
                item.get("new_members", 0),
                item.get("avg_fee", 0),
            ]
        )

    # By Region
    rows.extend([[], ["By Region"], ["Region", "Total Members", "New Members"]])
    for item in seg.get("by_region", []):
        rows.append([item.get("name"), item.get("total_members", 0), item.get("new_members", 0)])

    return rows


def prepare_cohort_sheet(data):
    """Prepare cohort data for Excel export"""
    cohorts = data.get("cohort_analysis", [])
    if not cohorts:
        return [["No cohort data available"]]

    # Create header row
    max_months = max(len(c.get("retention", [])) for c in cohorts)
    headers = ["Cohort", "Initial Count"] + [f"Month {i}" for i in range(max_months)]
    rows = [headers]

    # Add cohort data
    for cohort in cohorts:
        row = [cohort.get("cohort"), cohort.get("initial", 0)]
        for ret in cohort.get("retention", []):
            row.append(f"{ret.get('rate', 0):.1f}%")
        rows.append(row)

    return rows
