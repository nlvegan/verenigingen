"""Dashboard Chart Sources for Verenigingen"""

import frappe


def get_age_distribution_data():
    """Get member age distribution in 5-year groups"""
    from verenigingen.verenigingen.report.member_age_groups.member_age_groups import execute

    columns, data = execute()

    if not data:
        return {"labels": [], "datasets": []}

    # Format data for chart
    labels = [row.get("age_group", "Unknown") for row in data]
    values = [row.get("count", 0) for row in data]

    return {"labels": labels, "datasets": [{"name": "Members", "values": values}]}
