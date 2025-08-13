"""API endpoints for dashboard charts"""

import frappe
from frappe import _
from frappe.utils import date_diff, today


@frappe.whitelist(allow_guest=False)
def get_member_age_distribution_chart():
    """
    Get member age distribution data formatted for dashboard charts
    Can be called directly from JavaScript
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

    # Age group mapping with proper ordering
    age_groups_order = [
        "Under 18",
        "18-22",
        "23-27",
        "28-32",
        "33-37",
        "38-42",
        "43-47",
        "48-52",
        "53-57",
        "58-62",
        "63-67",
        "68+",
        "Unknown",
    ]

    age_groups = {group: 0 for group in age_groups_order}

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

    # Filter out empty groups and maintain order
    labels = []
    values = []

    for group in age_groups_order:
        if age_groups[group] > 0:
            labels.append(group)
            values.append(age_groups[group])

    return {"labels": labels, "datasets": [{"name": "Members", "values": values}], "type": "bar"}
