#!/usr/bin/env python3

import frappe


@frappe.whitelist()
def create_chapter_dashboard():
    """Create proper Frappe dashboard for chapter management"""

    try:
        # 1. Create Number Cards for chapter metrics
        cards_created = create_chapter_number_cards()

        # 2. Create Charts for chapter visualizations
        charts_created = create_chapter_charts()

        # 3. Create Dashboard that combines them
        dashboard_created = create_chapter_dashboard_doc()

        return {
            "success": True,
            "cards_created": cards_created,
            "charts_created": charts_created,
            "dashboard_created": dashboard_created,
            "dashboard_url": "/app/dashboard-view/Chapter%20Board%20Dashboard",
        }

    except Exception as e:
        frappe.log_error(f"Error creating chapter dashboard: {str(e)}", "Chapter Dashboard Creation")
        return {"success": False, "error": str(e)}


def create_chapter_number_cards():
    """Create number cards for chapter metrics"""
    cards = []

    # Card 1: Active Members
    if not frappe.db.exists("Number Card", "Active Chapter Members"):
        card1 = frappe.get_doc(
            {
                "doctype": "Number Card",
                "name": "Active Chapter Members",
                "label": "Active Members",
                "type": "Custom",
                "method": "verenigingen.api.chapter_dashboard_api.get_active_members_count",
                "is_public": 1,
                "show_percentage_stats": 1,
                "stats_time_interval": "Monthly",
                "color": "#29CD42",
                "filters_config": """[{
                fieldname: "chapter",
                label: __("Chapter"),
                fieldtype: "Link",
                options: "Chapter",
                reqd: 1
            }]""",
                "module": "Verenigingen",
            }
        )
        card1.insert()
        cards.append("Active Chapter Members")

    # Card 2: Pending Applications
    if not frappe.db.exists("Number Card", "Pending Member Applications"):
        card2 = frappe.get_doc(
            {
                "doctype": "Number Card",
                "name": "Pending Member Applications",
                "label": "Pending Applications",
                "type": "Custom",
                "method": "verenigingen.api.chapter_dashboard_api.get_pending_applications_count",
                "is_public": 1,
                "show_percentage_stats": 1,
                "stats_time_interval": "Daily",
                "color": "#FF9800",
                "filters_config": """[{
                fieldname: "chapter",
                label: __("Chapter"),
                fieldtype: "Link",
                options: "Chapter",
                reqd: 1
            }]""",
                "module": "Verenigingen",
            }
        )
        card2.insert()
        cards.append("Pending Member Applications")

    # Card 3: Board Members
    if not frappe.db.exists("Number Card", "Active Board Members"):
        card3 = frappe.get_doc(
            {
                "doctype": "Number Card",
                "name": "Active Board Members",
                "label": "Board Members",
                "type": "Custom",
                "method": "verenigingen.api.chapter_dashboard_api.get_board_members_count",
                "is_public": 1,
                "show_percentage_stats": 0,
                "stats_time_interval": "Monthly",
                "color": "#2196F3",
                "filters_config": """[{
                fieldname: "chapter",
                label: __("Chapter"),
                fieldtype: "Link",
                options: "Chapter",
                reqd: 1
            }]""",
                "module": "Verenigingen",
            }
        )
        card3.insert()
        cards.append("Active Board Members")

    # Card 4: New Members This Month
    if not frappe.db.exists("Number Card", "New Members This Month"):
        card4 = frappe.get_doc(
            {
                "doctype": "Number Card",
                "name": "New Members This Month",
                "label": "New Members (This Month)",
                "type": "Custom",
                "method": "verenigingen.api.chapter_dashboard_api.get_new_members_count",
                "is_public": 1,
                "show_percentage_stats": 1,
                "stats_time_interval": "Monthly",
                "color": "#4CAF50",
                "filters_config": """[{
                fieldname: "chapter",
                label: __("Chapter"),
                fieldtype: "Link",
                options: "Chapter",
                reqd: 1
            }]""",
                "module": "Verenigingen",
            }
        )
        card4.insert()
        cards.append("New Members This Month")

    return cards


def create_chapter_charts():
    """Create charts for chapter dashboard"""
    charts = []

    # Chart 1: Member Status Distribution
    if not frappe.db.exists("Dashboard Chart", "Chapter Member Status"):
        chart1 = frappe.get_doc(
            {
                "doctype": "Dashboard Chart",
                "name": "Chapter Member Status",
                "chart_name": "Chapter Member Status",
                "chart_type": "Donut",
                "document_type": "Chapter Member",
                "based_on": "status",
                "value_based_on": "",
                "number_of_groups": 0,
                "is_public": 1,
                "timeseries": 0,
                "filters_json": "[]",
                "module": "Verenigingen",
            }
        )
        chart1.insert()
        charts.append("Chapter Member Status")

    # Chart 2: Member Joining Trend
    if not frappe.db.exists("Dashboard Chart", "Member Joining Trend"):
        chart2 = frappe.get_doc(
            {
                "doctype": "Dashboard Chart",
                "name": "Member Joining Trend",
                "chart_name": "Member Joining Trend",
                "chart_type": "Line",
                "document_type": "Chapter Member",
                "based_on": "chapter_join_date",
                "value_based_on": "",
                "number_of_groups": 0,
                "is_public": 1,
                "timeseries": 1,
                "time_interval": "Monthly",
                "timespan": "Last Year",
                "filters_json": "[]",
                "module": "Verenigingen",
            }
        )
        chart2.insert()
        charts.append("Member Joining Trend")

    return charts


def create_chapter_dashboard_doc():
    """Create the main dashboard document"""

    if frappe.db.exists("Dashboard", "Chapter Board Dashboard"):
        return "Chapter Board Dashboard (already exists)"

    dashboard = frappe.get_doc(
        {
            "doctype": "Dashboard",
            "dashboard_name": "Chapter Board Dashboard",
            "is_standard": 0,
            "module": "Verenigingen",
            "cards": [
                {"card": "Active Chapter Members", "width": "Half"},
                {"card": "Pending Member Applications", "width": "Half"},
                {"card": "Active Board Members", "width": "Half"},
                {"card": "New Members This Month", "width": "Half"},
            ],
            "charts": [
                {"chart": "Chapter Member Status", "width": "Half"},
                {"chart": "Member Joining Trend", "width": "Full"},
            ],
        }
    )
    dashboard.insert()

    return "Chapter Board Dashboard"


if __name__ == "__main__":
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    result = create_chapter_dashboard()
    print("Result:", result)
