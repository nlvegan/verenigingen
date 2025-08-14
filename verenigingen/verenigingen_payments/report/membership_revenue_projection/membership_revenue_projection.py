from datetime import datetime, timedelta

import frappe
from dateutil.relativedelta import relativedelta


def execute(filters=None):
    """Generate membership revenue projection for the next 12 months"""
    columns = get_columns()
    data = get_data(filters)
    chart = get_chart_config(data)

    return columns, data, None, chart


def get_filters():
    """Define filters for the report"""
    return [
        {
            "fieldname": "projection_months",
            "label": "Projection Months",
            "fieldtype": "Int",
            "default": 12,
            "reqd": 0,
        }
    ]


def get_columns():
    """Define report columns"""
    return [
        {"fieldname": "month", "label": "Month", "fieldtype": "Data", "width": 120},
        {
            "fieldname": "projected_revenue",
            "label": "Projected Revenue (EUR)",
            "fieldtype": "Currency",
            "width": 150,
        },
        {"fieldname": "active_memberships", "label": "Active Memberships", "fieldtype": "Int", "width": 120},
        {
            "fieldname": "average_amount",
            "label": "Average Amount (EUR)",
            "fieldtype": "Currency",
            "width": 130,
        },
    ]


def get_data(filters):
    """Calculate projected revenue for specified number of months"""
    data = []
    current_date = datetime.now().replace(day=1)  # Start of current month

    # Get projection months from filters, default to 12
    projection_months = 12
    if filters and filters.get("projection_months"):
        projection_months = max(1, min(24, int(filters.get("projection_months"))))

    # Get active membership dues schedules
    active_schedules = frappe.db.sql(
        """
        SELECT
            mds.name,
            mds.dues_rate,
            mds.billing_frequency,
            mds.currency,
            mds.status,
            mds.membership_type,
            mds.end_date
        FROM `tabMembership Dues Schedule` mds
        WHERE mds.status = 'Active'
        AND mds.is_template = 0
        AND mds.dues_rate > 0
        ORDER BY mds.dues_rate DESC
    """,
        as_dict=True,
    )

    # Calculate projections for specified number of months
    for month_offset in range(projection_months):
        projection_date = current_date + relativedelta(months=month_offset)
        month_str = projection_date.strftime("%Y-%m")

        monthly_revenue = 0
        active_count = 0

        for schedule in active_schedules:
            # Check if membership will still be active in this projection month
            if schedule.end_date and schedule.end_date < projection_date.date():
                continue

            # Calculate monthly revenue based on billing frequency
            monthly_contribution = calculate_monthly_revenue(
                schedule.dues_rate, schedule.billing_frequency, projection_date
            )

            if monthly_contribution > 0:
                monthly_revenue += monthly_contribution
                active_count += 1

        average_amount = monthly_revenue / active_count if active_count > 0 else 0

        data.append(
            {
                "month": month_str,
                "projected_revenue": monthly_revenue,
                "active_memberships": active_count,
                "average_amount": average_amount,
            }
        )

    return data


def calculate_monthly_revenue(dues_rate, billing_frequency, projection_date):
    """Calculate monthly revenue contribution based on billing frequency"""
    if billing_frequency == "Monthly":
        return dues_rate
    elif billing_frequency == "Quarterly":
        # Quarterly payments contribute 1/3 of the amount per month
        return dues_rate / 3
    elif billing_frequency == "Annual":
        # Annual payments contribute 1/12 of the amount per month
        return dues_rate / 12
    elif billing_frequency == "Semi-Annual":
        # Semi-annual payments contribute 1/6 of the amount per month
        return dues_rate / 6
    else:
        # Default to monthly for unknown frequencies
        return dues_rate


def get_chart_config(data):
    """Generate chart configuration for the report"""
    return {
        "data": {"x": "month", "y": [{"name": "projected_revenue", "type": "line"}]},
        "chart_type": "line",
        "height": 300,
        "colors": ["#28A745"],
    }
