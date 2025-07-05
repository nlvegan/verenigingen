#!/usr/bin/env python3

import frappe


@frappe.whitelist()
def add_chapter_specific_chart():
    """Add a chapter-specific chart to the dashboard"""

    try:
        # Create a simple custom chart for chapter member count
        if not frappe.db.exists("Dashboard Chart", "Chapter Members Count"):
            chart = frappe.get_doc(
                {
                    "doctype": "Dashboard Chart",
                    "name": "Chapter Members Count",
                    "chart_name": "Chapter Members Count",
                    "chart_type": "Count",
                    "document_type": "Chapter Member",
                    "based_on": "parent",
                    "is_public": 1,
                    "timeseries": 0,
                    "number_of_groups": 10,
                    "filters_json": "[]",
                    "module": "Verenigingen",
                }
            )
            chart.insert()

        # Update the dashboard to include this chart
        dashboard = frappe.get_doc("Dashboard", "Chapter Board Dashboard")

        # Add the new chart
        dashboard.append("charts", {"chart": "Chapter Members Count", "width": "Half"})

        dashboard.save()

        return {
            "success": True,
            "message": "Added chapter-specific chart to dashboard",
            "chart_name": "Chapter Members Count",
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    result = add_chapter_specific_chart()
    print("Result:", result)
