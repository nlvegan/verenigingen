#!/usr/bin/env python3

import frappe


@frappe.whitelist()
def create_simple_dashboard():
    """Create a simple test dashboard"""

    try:
        # Create a simple dashboard without custom cards first
        if frappe.db.exists("Dashboard", "Chapter Board Dashboard"):
            frappe.delete_doc("Dashboard", "Chapter Board Dashboard")

        dashboard = frappe.get_doc(
            {
                "doctype": "Dashboard",
                "dashboard_name": "Chapter Board Dashboard",
                "is_standard": 0,
                "module": "Verenigingen",
            }
        )
        dashboard.insert()

        return {
            "success": True,
            "message": "Simple dashboard created successfully",
            "dashboard_url": f"/app/dashboard-view/Chapter%20Board%20Dashboard",
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    result = create_simple_dashboard()
    print("Result:", result)
