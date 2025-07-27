# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

import json
from datetime import datetime, timedelta

import frappe
from frappe.model.document import Document
from frappe.utils import add_days, add_months, flt, getdate, today


class MembershipAnalyticsSnapshot(Document):
    pass


@frappe.whitelist()
def create_snapshot(snapshot_type="Daily", specific_date=None):
    """Create analytics snapshot for the specified type and date"""
    snapshot_date = getdate(specific_date) if specific_date else today()

    # Check if snapshot already exists
    existing = frappe.db.exists(
        "Membership Analytics Snapshot", {"snapshot_date": snapshot_date, "snapshot_type": snapshot_type}
    )

    if existing:
        frappe.throw(f"Snapshot for {snapshot_date} ({snapshot_type}) already exists")

    # Calculate period based on snapshot type
    period = calculate_period(snapshot_type, snapshot_date)

    # Create snapshot document
    snapshot = frappe.get_doc(
        {
            "doctype": "Membership Analytics Snapshot",
            "snapshot_date": snapshot_date,
            "snapshot_type": snapshot_type,
            "period": period["label"],
        }
    )

    # Calculate and store metrics
    calculate_member_metrics(snapshot, period)
    calculate_financial_metrics(snapshot, period)
    calculate_segmentation_data(snapshot, period)
    calculate_cohort_data(snapshot, period)

    snapshot.insert(ignore_permissions=True)
    frappe.db.commit()

    return snapshot.name


def calculate_period(snapshot_type, snapshot_date):
    """Calculate period start and end dates based on snapshot type"""
    if snapshot_type == "Daily":
        start_date = snapshot_date
        end_date = snapshot_date
        label = snapshot_date.strftime("%Y-%m-%d")
    elif snapshot_type == "Weekly":
        # Week starts on Monday
        start_date = snapshot_date - timedelta(days=snapshot_date.weekday())
        end_date = start_date + timedelta(days=6)
        label = f"Week {start_date.strftime('%Y-%W')}"
    elif snapshot_type == "Monthly":
        start_date = snapshot_date.replace(day=1)
        end_date = add_months(start_date, 1) - timedelta(days=1)
        label = snapshot_date.strftime("%B %Y")
    elif snapshot_type == "Quarterly":
        quarter = (snapshot_date.month - 1) // 3 + 1
        start_month = (quarter - 1) * 3 + 1
        start_date = snapshot_date.replace(month=start_month, day=1)
        end_date = add_months(start_date, 3) - timedelta(days=1)
        label = f"Q{quarter} {snapshot_date.year}"
    else:  # Yearly
        start_date = snapshot_date.replace(month=1, day=1)
        end_date = snapshot_date.replace(month=12, day=31)
        label = str(snapshot_date.year)

    return {"start_date": start_date, "end_date": end_date, "label": label}


def calculate_member_metrics(snapshot, period):
    """Calculate member-related metrics"""
    # Total and active members
    snapshot.total_members = frappe.db.count("Member")
    snapshot.active_members = frappe.db.count("Member", filters={"status": "Active"})

    # New members in period
    snapshot.new_members = frappe.db.count(
        "Member",
        filters={
            "member_since": ["between", [period["start_date"], period["end_date"]]],
            "status": ["!=", "Rejected"],
        },
    )

    # Lost members in period
    snapshot.lost_members = frappe.db.count(
        "Membership Termination Request",
        filters={
            "termination_date": ["between", [period["start_date"], period["end_date"]]],
            "status": "Completed",
        },
    )

    # Net growth
    snapshot.net_growth = snapshot.new_members - snapshot.lost_members

    # Growth rate
    members_at_start = frappe.db.count(
        "Member", filters={"member_since": ["<", period["start_date"]], "status": "Active"}
    )

    if members_at_start > 0:
        snapshot.growth_rate = (snapshot.net_growth / members_at_start) * 100
    else:
        snapshot.growth_rate = 0

    # Churn rate
    if snapshot.active_members > 0:
        snapshot.churn_rate = (snapshot.lost_members / snapshot.active_members) * 100
    else:
        snapshot.churn_rate = 0

    # Retention rate
    snapshot.retention_rate = 100 - snapshot.churn_rate


def calculate_financial_metrics(snapshot, period):
    """Calculate financial metrics"""
    # Get all active memberships with fees
    revenue_data = frappe.db.sql(
        """
        SELECT
            SUM(COALESCE(mem.dues_rate, mt.minimum_amount, 0)) as total_revenue,
            COUNT(DISTINCT m.member) as member_count
        FROM `tabMembership` m
        JOIN `tabMember` mem ON m.member = mem.name
        JOIN `tabMembership Type` mt ON m.membership_type = mt.name
        WHERE m.status = 'Active'
    """,
        as_dict=True,
    )[0]

    snapshot.total_revenue = revenue_data.total_revenue or 0

    # Average member value
    if revenue_data.member_count > 0:
        snapshot.average_member_value = snapshot.total_revenue / revenue_data.member_count
    else:
        snapshot.average_member_value = 0

    # Projected annual revenue (based on current active members)
    snapshot.projected_annual_revenue = snapshot.total_revenue


def calculate_segmentation_data(snapshot, period):
    """Calculate segmentation breakdowns"""
    # By Chapter
    chapter_data = frappe.db.sql(
        """
        SELECT
            COALESCE(current_chapter_display, 'No Chapter') as chapter,
            COUNT(*) as member_count,
            SUM(CASE WHEN member_since BETWEEN %s AND %s THEN 1 ELSE 0 END) as new_members
        FROM `tabMember`
        WHERE status = 'Active'
        GROUP BY current_chapter_display
    """,
        (period["start_date"], period["end_date"]),
        as_dict=True,
    )

    snapshot.by_chapter = json.dumps(chapter_data)

    # By Region (derived from postal codes)
    region_data = frappe.db.sql(
        """
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
            END as region,
            COUNT(DISTINCT m.name) as member_count
        FROM `tabMember` m
        LEFT JOIN `tabAddress` a ON m.primary_address = a.name
        WHERE m.status = 'Active'
        GROUP BY region
    """,
        as_dict=True,
    )

    snapshot.by_region = json.dumps(region_data)

    # By Membership Type
    type_data = frappe.db.sql(
        """
        SELECT
            ms.membership_type,
            COUNT(DISTINCT ms.member) as member_count,
            SUM(COALESCE(m.dues_rate, mt.minimum_amount, 0)) as revenue
        FROM `tabMembership` ms
        JOIN `tabMember` m ON ms.member = m.name
        JOIN `tabMembership Type` mt ON ms.membership_type = mt.name
        WHERE ms.status = 'Active'
        GROUP BY ms.membership_type
    """,
        as_dict=True,
    )

    snapshot.by_membership_type = json.dumps(type_data)

    # By Payment Method
    payment_data = frappe.db.sql(
        """
        SELECT
            COALESCE(payment_method, 'Not Set') as payment_method,
            COUNT(*) as member_count
        FROM `tabMember`
        WHERE status = 'Active'
        GROUP BY payment_method
    """,
        as_dict=True,
    )

    snapshot.by_payment_method = json.dumps(payment_data)

    # By Age Group
    age_data = frappe.db.sql(
        """
        SELECT
            CASE
                WHEN TIMESTAMPDIFF(YEAR, birth_date, CURDATE()) < 25 THEN 'Under 25'
                WHEN TIMESTAMPDIFF(YEAR, birth_date, CURDATE()) BETWEEN 25 AND 34 THEN '25-34'
                WHEN TIMESTAMPDIFF(YEAR, birth_date, CURDATE()) BETWEEN 35 AND 44 THEN '35-44'
                WHEN TIMESTAMPDIFF(YEAR, birth_date, CURDATE()) BETWEEN 45 AND 54 THEN '45-54'
                WHEN TIMESTAMPDIFF(YEAR, birth_date, CURDATE()) BETWEEN 55 AND 64 THEN '55-64'
                WHEN TIMESTAMPDIFF(YEAR, birth_date, CURDATE()) >= 65 THEN '65+'
                ELSE 'Unknown'
            END as age_group,
            COUNT(*) as member_count
        FROM `tabMember`
        WHERE status = 'Active' AND birth_date IS NOT NULL
        GROUP BY age_group
    """,
        as_dict=True,
    )

    snapshot.by_age_group = json.dumps(age_data)

    # By Join Year
    join_year_data = frappe.db.sql(
        """
        SELECT
            YEAR(member_since) as join_year,
            COUNT(*) as member_count,
            AVG(COALESCE(dues_rate,
                (SELECT minimum_amount FROM `tabMembership Type` mt
                 JOIN `tabMembership` ms ON ms.membership_type = mt.name
                 WHERE ms.member = m.name AND ms.status = 'Active'
                 LIMIT 1), 0)) as avg_fee
        FROM `tabMember` m
        WHERE status = 'Active' AND member_since IS NOT NULL
        GROUP BY join_year
        ORDER BY join_year DESC
        LIMIT 10
    """,
        as_dict=True,
    )

    snapshot.by_join_year = json.dumps(join_year_data)


def calculate_cohort_data(snapshot, period):
    """Calculate cohort retention data"""
    # Get cohorts for the last 12 months
    cohort_data = []

    for months_back in range(12):
        cohort_date = add_months(period["end_date"], -months_back)
        cohort_month = cohort_date.replace(day=1)

        # Get members who joined in this cohort
        cohort_members = frappe.db.sql(
            """
            SELECT COUNT(*) as initial_count
            FROM `tabMember`
            WHERE DATE_FORMAT(member_since, '%%Y-%%m') = %s
            AND status != 'Rejected'
        """,
            cohort_month.strftime("%Y-%m"),
        )[0][0]

        if cohort_members > 0:
            # Calculate retention for each subsequent month
            retention_data = {"cohort": cohort_month.strftime("%Y-%m"), "initial": cohort_members}

            for month_offset in range(1, min(months_back + 1, 13)):
                check_date = add_months(cohort_month, month_offset)

                # Count how many are still active
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

                retention_data[f"month_{month_offset}"] = {
                    "count": retained,
                    "percentage": (retained / cohort_members) * 100,
                }

            cohort_data.append(retention_data)

    snapshot.cohort_data = json.dumps(cohort_data)


def create_scheduled_snapshots():
    """Create snapshots based on schedule (called by scheduler)"""
    today_date = today()

    # Daily snapshot
    create_snapshot("Daily", today_date)

    # Weekly snapshot (on Sundays)
    if today_date.weekday() == 6:
        create_snapshot("Weekly", today_date)

    # Monthly snapshot (on first day of month)
    if today_date.day == 1:
        create_snapshot("Monthly", today_date)

        # Quarterly snapshot (on first day of quarter)
        if today_date.month in [1, 4, 7, 10]:
            create_snapshot("Quarterly", today_date)

        # Yearly snapshot (on January 1st)
        if today_date.month == 1:
            create_snapshot("Yearly", today_date)

    frappe.db.commit()
