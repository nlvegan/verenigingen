# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

import json
from datetime import datetime, timedelta

import frappe
from frappe.utils import add_months, flt, fmt_money, getdate, now_datetime


@frappe.whitelist()
def get_dashboard_data(year=None, period="year", compare_previous=False, filters=None):
    """Get all dashboard data for membership analytics"""
    if not year:
        year = datetime.now().year

    if filters and isinstance(filters, str):
        filters = json.loads(filters)
    else:
        filters = filters or {}

    data = {
        "summary": get_summary_metrics(year, period, filters),
        "growth_trend": get_growth_trend(year, period, filters),
        "revenue_projection": get_revenue_projection(year, filters),
        "membership_breakdown": get_membership_breakdown(year, filters),
        "goals": get_goals_progress(year),
        "insights": get_top_insights(year),
        "segmentation": get_segmentation_data(year, period, filters),
        "cohort_analysis": get_cohort_analysis(year),
        "last_updated": now_datetime(),
    }

    if compare_previous:
        data["previous_period"] = get_summary_metrics(year - 1, period, filters)

    return data


@frappe.whitelist()
def get_summary_metrics(year, period="year", filters=None):
    """Get summary metrics for the dashboard header"""
    filters = filters or {}

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

    # Total active members
    total_members = frappe.db.count("Member", filters={"status": "Active"})

    # New members in period
    new_members = frappe.db.count(
        "Member", filters={"member_since": ["between", [start_date, end_date]], "status": ["!=", "Rejected"]}
    )

    # Lost members in period
    lost_members = frappe.db.count(
        "Membership Termination Request",
        filters={"termination_date": ["between", [start_date, end_date]], "status": "Completed"},
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
    """Calculate projected revenue for the year"""
    # Get all active memberships
    active_memberships = frappe.get_all(
        "Membership", filters={"status": "Active"}, fields=["name", "member", "membership_type"]
    )

    total_revenue = 0
    for membership in active_memberships:
        # Check for fee override
        member_doc = frappe.get_doc("Member", membership.member)
        if member_doc.dues_rate:
            annual_fee = member_doc.dues_rate
        else:
            # Get standard fee from template
            membership_type = frappe.get_doc("Membership Type", membership.membership_type)
            if membership_type.dues_schedule_template:
                template = frappe.get_doc("Membership Dues Schedule", membership_type.dues_schedule_template)
                annual_fee = template.suggested_amount or 0
            else:
                annual_fee = 0

        total_revenue += annual_fee

    return total_revenue


@frappe.whitelist()
def get_growth_trend(year, period="year", filters=None):
    """Get member growth trend data for charts"""
    filters = filters or {}
    growth_data = []

    if period == "year":
        # Monthly data for the year
        for month in range(1, 13):
            start_date = f"{year}-{month:02d}-01"
            end_date = getdate(add_months(start_date, 1)) - timedelta(days=1)

            new_members = frappe.db.count(
                "Member", filters={"member_since": ["between", [start_date, end_date]]}
            )

            lost_members = frappe.db.count(
                "Membership Termination Request",
                filters={"termination_date": ["between", [start_date, end_date]], "status": "Completed"},
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
def get_revenue_projection(year, filters=None):
    """Get revenue projection by membership type"""
    filters = filters or {}
    membership_types = frappe.get_all(
        "Membership Type", filters={"is_active": 1}, fields=["name", "minimum_amount"]
    )

    revenue_data = []

    for mt in membership_types:
        # Count active members of this type
        member_count = frappe.db.sql(
            """
            SELECT COUNT(DISTINCT m.member) as count,
                   SUM(COALESCE(mem.dues_rate, mt.minimum_amount)) as revenue
            FROM `tabMembership` m
            JOIN `tabMember` mem ON m.member = mem.name
            JOIN `tabMembership Type` mt ON m.membership_type = mt.name
            WHERE m.status = 'Active'
            AND m.membership_type = %s
        """,
            mt.name,
            as_dict=True,
        )[0]

        revenue_data.append(
            {
                "membership_type": mt.name,
                "member_count": member_count.count or 0,
                "revenue": member_count.revenue or 0,
                "average_fee": mt.minimum_amount,
            }
        )

    return revenue_data


@frappe.whitelist()
def get_membership_breakdown(year, filters=None):
    """Get membership breakdown by type"""
    filters = filters or {}
    breakdown = frappe.db.sql(
        """
        SELECT
            m.membership_type,
            COUNT(DISTINCT m.member) as count,
            SUM(COALESCE(mem.dues_rate, mt.minimum_amount)) as revenue
        FROM `tabMembership` m
        JOIN `tabMember` mem ON m.member = mem.name
        JOIN `tabMembership Type` mt ON m.membership_type = mt.name
        WHERE m.status = 'Active'
        GROUP BY m.membership_type
    """,
        as_dict=True,
    )

    return breakdown


@frappe.whitelist()
def get_goals_progress(year):
    """Get progress on membership goals"""
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
        goal_doc.save(ignore_permissions=True)

        goal.current_value = goal_doc.current_value
        goal.achievement_percentage = goal_doc.achievement_percentage
        goal.status = goal_doc.status

    return goals


@frappe.whitelist()
def get_top_insights(year):
    """Get AI-like insights based on data analysis"""
    insights = []

    # Get growth by chapter
    chapter_growth = frappe.db.sql(
        """
        SELECT
            current_chapter_display as chapter,
            COUNT(*) as new_members
        FROM `tabMember`
        WHERE member_since BETWEEN %s AND %s
        AND current_chapter_display IS NOT NULL
        GROUP BY current_chapter_display
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
                SELECT COUNT(*) as member_count
                FROM `tabMember`
                WHERE member_since BETWEEN %s AND %s
                GROUP BY current_chapter_display
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
    at_risk_count = frappe.db.count(
        "Member", filters={"status": "Active", "last_activity": ["<", getdate() - timedelta(days=90)]}
    )

    if at_risk_count > 0:
        insights.append(
            {"type": "warning", "message": f"{at_risk_count} members at risk of churning (inactive >90 days)"}
        )

    return insights


def calculate_retention_rate(year):
    """Calculate retention rate for a year"""
    start_date = f"{year}-01-01"
    end_date = f"{year}-12-31"

    members_at_start = frappe.db.count(
        "Member", filters={"member_since": ["<", start_date], "status": ["!=", "Terminated"]}
    )

    if members_at_start == 0:
        return 0

    terminated = frappe.db.count(
        "Membership Termination Request",
        filters={"termination_date": ["between", [start_date, end_date]], "status": "Completed"},
    )

    return ((members_at_start - terminated) / members_at_start) * 100


@frappe.whitelist()
def create_goal(goal_data):
    """Create a new membership goal"""
    if isinstance(goal_data, str):
        goal_data = json.loads(goal_data)

    goal = frappe.get_doc({"doctype": "Membership Goal", **goal_data})

    goal.insert()
    frappe.db.commit()

    return goal.name


@frappe.whitelist()
def get_segmentation_data(year, period="year", filters=None):
    """Get detailed segmentation data"""
    filters = filters or {}

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
        conditions.append(f"current_chapter_display = '{filters['chapter']}'")

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
    """Get member distribution by chapter"""
    query = f"""
        SELECT
            COALESCE(current_chapter_display, 'No Chapter') as name,
            COUNT(*) as total_members,
            SUM(CASE WHEN YEAR(member_since) = {year} THEN 1 ELSE 0 END) as new_members,
            AVG(COALESCE(dues_rate,
                (SELECT minimum_amount FROM `tabMembership Type` mt
                 JOIN `tabMembership` ms ON ms.membership_type = mt.name
                 WHERE ms.member = m.name AND ms.status = 'Active'
                 LIMIT 1), 0)) as avg_fee
        FROM `tabMember` m
        WHERE status = 'Active' {filter_conditions}
        GROUP BY current_chapter_display
        ORDER BY total_members DESC
    """

    return frappe.db.sql(query, as_dict=True)


def get_region_segmentation(year, filter_conditions):
    """Get member distribution by region"""
    query = f"""
        SELECT
            CASE
                WHEN LEFT(a.pincode, 2) BETWEEN '10' AND '19' THEN 'Noord-Holland'
                WHEN LEFT(a.pincode, 2) BETWEEN '20' AND '29' THEN 'Zuid-Holland'
                WHEN LEFT(a.pincode, 2) BETWEEN '30' AND '39' THEN 'Utrecht'
                WHEN LEFT(a.pincode, 2) BETWEEN '40' AND '49' THEN 'Gelderland'
                WHEN LEFT(a.pincode, 2) BETWEEN '50' AND '59' THEN 'Noord-Brabant'
                WHEN LEFT(a.pincode, 2) BETWEEN '60' AND '69' THEN 'Limburg'
                WHEN LEFT(a.pincode, 2) BETWEEN '70' AND '79' THEN 'Zeeland'
                WHEN LEFT(a.pincode, 2) BETWEEN '80' AND '89' THEN 'Overijssel'
                WHEN LEFT(a.pincode, 2) BETWEEN '90' AND '99' THEN 'Groningen'
                ELSE 'Other'
            END as name,
            COUNT(DISTINCT m.name) as total_members,
            SUM(CASE WHEN YEAR(m.member_since) = {year} THEN 1 ELSE 0 END) as new_members
        FROM `tabMember` m
        LEFT JOIN `tabAddress` a ON m.primary_address = a.name
        WHERE m.status = 'Active' {filter_conditions}
        GROUP BY name
        ORDER BY total_members DESC
    """

    return frappe.db.sql(query, as_dict=True)


def get_age_segmentation(year, filter_conditions):
    """Get member distribution by age group"""
    query = f"""
        SELECT
            CASE
                WHEN TIMESTAMPDIFF(YEAR, birth_date, CURDATE()) < 25 THEN 'Under 25'
                WHEN TIMESTAMPDIFF(YEAR, birth_date, CURDATE()) BETWEEN 25 AND 34 THEN '25-34'
                WHEN TIMESTAMPDIFF(YEAR, birth_date, CURDATE()) BETWEEN 35 AND 44 THEN '35-44'
                WHEN TIMESTAMPDIFF(YEAR, birth_date, CURDATE()) BETWEEN 45 AND 54 THEN '45-54'
                WHEN TIMESTAMPDIFF(YEAR, birth_date, CURDATE()) BETWEEN 55 AND 64 THEN '55-64'
                WHEN TIMESTAMPDIFF(YEAR, birth_date, CURDATE()) >= 65 THEN '65+'
                ELSE 'Unknown'
            END as name,
            COUNT(*) as total_members,
            AVG(COALESCE(dues_rate,
                (SELECT minimum_amount FROM `tabMembership Type` mt
                 JOIN `tabMembership` ms ON ms.membership_type = mt.name
                 WHERE ms.member = m.name AND ms.status = 'Active'
                 LIMIT 1), 0)) as avg_fee
        FROM `tabMember` m
        WHERE status = 'Active' AND birth_date IS NOT NULL {filter_conditions}
        GROUP BY name
        ORDER BY FIELD(name, 'Under 25', '25-34', '35-44', '45-54', '55-64', '65+', 'Unknown')
    """

    return frappe.db.sql(query, as_dict=True)


def get_payment_method_segmentation(year, filter_conditions):
    """Get member distribution by payment method"""
    query = f"""
        SELECT
            COALESCE(payment_method, 'Not Set') as name,
            COUNT(*) as total_members,
            SUM(CASE WHEN YEAR(member_since) = {year} THEN 1 ELSE 0 END) as new_members
        FROM `tabMember` m
        WHERE status = 'Active' {filter_conditions}
        GROUP BY payment_method
        ORDER BY total_members DESC
    """

    return frappe.db.sql(query, as_dict=True)


def get_join_year_segmentation(year, filter_conditions):
    """Get member distribution by join year"""
    query = f"""
        SELECT
            YEAR(member_since) as name,
            COUNT(*) as total_members,
            AVG(total_membership_days) as avg_tenure_days,
            AVG(COALESCE(dues_rate,
                (SELECT minimum_amount FROM `tabMembership Type` mt
                 JOIN `tabMembership` ms ON ms.membership_type = mt.name
                 WHERE ms.member = m.name AND ms.status = 'Active'
                 LIMIT 1), 0)) as avg_fee
        FROM `tabMember` m
        WHERE status = 'Active' AND member_since IS NOT NULL {filter_conditions}
        GROUP BY YEAR(member_since)
        ORDER BY name DESC
        LIMIT 10
    """

    return frappe.db.sql(query, as_dict=True)


@frappe.whitelist()
def get_cohort_analysis(year):
    """Get cohort retention analysis"""
    # Get last 12 months of cohorts
    cohorts = []
    end_date = datetime(year, 12, 31)

    for months_back in range(12):
        cohort_date = add_months(end_date, -months_back)
        cohort_month = cohort_date.replace(day=1)

        # Get initial cohort size
        initial_count = frappe.db.sql(
            """
            SELECT COUNT(*)
            FROM `tabMember`
            WHERE DATE_FORMAT(member_since, '%%Y-%%m') = %s
            AND status != 'Rejected'
        """,
            cohort_month.strftime("%Y-%m"),
        )[0][0]

        if initial_count > 0:
            cohort_data = {
                "cohort": cohort_month.strftime("%b %Y"),
                "initial": initial_count,
                "retention": [],
            }

            # Calculate retention for each subsequent month
            for month_offset in range(0, min(months_back + 1, 13)):
                check_date = add_months(cohort_month, month_offset)

                retained = frappe.db.sql(
                    """
                    SELECT COUNT(*)
                    FROM `tabMember` m
                    WHERE DATE_FORMAT(member_since, '%%Y-%%m') = %s
                    AND status = 'Active'
                    AND NOT EXISTS (
                        SELECT 1 FROM `tabMembership Termination Request` t
                        WHERE t.member = m.name
                        AND t.status = 'Completed'
                        AND t.termination_date < %s
                    )
                """,
                    (cohort_month.strftime("%Y-%m"), check_date),
                )[0][0]

                retention_rate = (retained / initial_count) * 100
                cohort_data["retention"].append(
                    {"month": month_offset, "rate": retention_rate, "count": retained}
                )

            cohorts.append(cohort_data)

    return cohorts


@frappe.whitelist()
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
