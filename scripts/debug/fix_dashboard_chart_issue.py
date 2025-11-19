#!/usr/bin/env python3

import frappe


@frappe.whitelist()
def fix_dashboard_chart_issue():
    """Fix the dashboard chart issue causing page navigation errors"""

    try:
        # Get the dashboard
        dashboard = frappe.get_doc("Dashboard", "Chapter Board Dashboard")

        # Remove the problematic chart from dashboard
        charts_to_remove = []
        for chart_link in dashboard.charts:
            if chart_link.chart == "Chapter Members Count":
                charts_to_remove.append(chart_link)

        for chart_link in charts_to_remove:
            dashboard.remove(chart_link)

        dashboard.save()

        # Now delete the problematic chart
        if frappe.db.exists("Dashboard Chart", "Chapter Members Count"):
            frappe.delete_doc("Dashboard Chart", "Chapter Members Count")

        # Create a simpler, working chart
        if not frappe.db.exists("Dashboard Chart", "Simple Chapter Count"):
            new_chart = frappe.get_doc(
                {
                    "doctype": "Dashboard Chart",
                    "name": "Simple Chapter Count",
                    "chart_name": "Simple Chapter Count",
                    "chart_type": "Count",
                    "document_type": "Chapter",
                    "based_on": "name",
                    "is_public": 1,
                    "timeseries": 0,
                    "number_of_groups": 5,
                    "filters_json": "[]",
                    "module": "Verenigingen",
                }
            )
            new_chart.insert()

            # Add the new chart to dashboard
            dashboard.append("charts", {"chart": "Simple Chapter Count", "width": "Half"})
            dashboard.save()

        return {
            "success": True,
            "message": "Fixed dashboard chart issue",
            "actions": [
                "Removed problematic chart from dashboard",
                "Deleted problematic chart",
                "Created simple working chart",
                "Added new chart to dashboard",
            ],
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    result = fix_dashboard_chart_issue()
    print("Fix result:", result)
