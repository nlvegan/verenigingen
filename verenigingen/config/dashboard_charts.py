"""Custom Dashboard Chart Sources for Verenigingen"""

import frappe
from frappe import _
from frappe.utils import date_diff, today


@frappe.whitelist()
def get_member_age_distribution(chart_name=None, filters=None):
    """
    Get member age distribution in 5-year groups
    This is a custom chart source for dashboard charts
    """
    # Query members with birth dates and status
    members = frappe.db.sql(
        """
        SELECT birth_date, status
        FROM `tabMember`
        WHERE birth_date IS NOT NULL
        AND status IN ('Active', 'Pending')
    """,
        as_dict=True,
    )

    # Age group mapping
    age_groups = {
        "Under 18": 0,
        "18-22": 0,
        "23-27": 0,
        "28-32": 0,
        "33-37": 0,
        "38-42": 0,
        "43-47": 0,
        "48-52": 0,
        "53-57": 0,
        "58-62": 0,
        "63-67": 0,
        "68+": 0,
        "Unknown": 0,
    }

    # Calculate age and group for each member
    for member in members:
        if not member.birth_date:
            age_groups["Unknown"] += 1
            continue

        try:
            age = int(date_diff(today(), member.birth_date) / 365.25)

            if age < 18:
                age_groups["Under 18"] += 1
            elif age <= 22:
                age_groups["18-22"] += 1
            elif age <= 27:
                age_groups["23-27"] += 1
            elif age <= 32:
                age_groups["28-32"] += 1
            elif age <= 37:
                age_groups["33-37"] += 1
            elif age <= 42:
                age_groups["38-42"] += 1
            elif age <= 47:
                age_groups["43-47"] += 1
            elif age <= 52:
                age_groups["48-52"] += 1
            elif age <= 57:
                age_groups["53-57"] += 1
            elif age <= 62:
                age_groups["58-62"] += 1
            elif age <= 67:
                age_groups["63-67"] += 1
            else:
                age_groups["68+"] += 1

        except (ValueError, TypeError):
            age_groups["Unknown"] += 1

    # Filter out empty groups
    filtered_groups = {k: v for k, v in age_groups.items() if v > 0}

    # Format for chart
    labels = list(filtered_groups.keys())
    values = list(filtered_groups.values())

    return {"labels": labels, "datasets": [{"name": "Members", "values": values}]}
