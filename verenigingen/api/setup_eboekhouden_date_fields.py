"""
Setup date range fields for E-Boekhouden Settings
"""

import frappe


@frappe.whitelist()
def setup_date_range_fields():
    """Add custom fields to E-Boekhouden Settings to store date range"""

    fields_added = []

    # Add data_earliest_date field
    if not frappe.db.has_column("E-Boekhouden Settings", "data_earliest_date"):
        frappe.get_doc(
            {
                "doctype": "Custom Field",
                "dt": "E-Boekhouden Settings",
                "fieldname": "data_earliest_date",
                "fieldtype": "Date",
                "label": "Data Earliest Date",
                "read_only": 1,
                "insert_after": "default_fiscal_year",
                "description": "Earliest transaction date in E-Boekhouden (auto-detected)",
            }
        ).insert(ignore_permissions=True)
        fields_added.append("data_earliest_date")

    # Add data_latest_date field
    if not frappe.db.has_column("E-Boekhouden Settings", "data_latest_date"):
        frappe.get_doc(
            {
                "doctype": "Custom Field",
                "dt": "E-Boekhouden Settings",
                "fieldname": "data_latest_date",
                "fieldtype": "Date",
                "label": "Data Latest Date",
                "read_only": 1,
                "insert_after": "data_earliest_date",
                "description": "Latest transaction date in E-Boekhouden (auto-detected)",
            }
        ).insert(ignore_permissions=True)
        fields_added.append("data_latest_date")

    # Add date_range_last_updated field
    if not frappe.db.has_column("E-Boekhouden Settings", "date_range_last_updated"):
        frappe.get_doc(
            {
                "doctype": "Custom Field",
                "dt": "E-Boekhouden Settings",
                "fieldname": "date_range_last_updated",
                "fieldtype": "Datetime",
                "label": "Date Range Last Updated",
                "read_only": 1,
                "insert_after": "data_latest_date",
                "description": "When the date range was last analyzed",
            }
        ).insert(ignore_permissions=True)
        fields_added.append("date_range_last_updated")

    # Add section for data information
    if not frappe.db.has_column("E-Boekhouden Settings", "data_info_section"):
        frappe.get_doc(
            {
                "doctype": "Custom Field",
                "dt": "E-Boekhouden Settings",
                "fieldname": "data_info_section",
                "fieldtype": "Section Break",
                "label": "E-Boekhouden Data Information",
                "insert_after": "default_cost_center",
            }
        ).insert(ignore_permissions=True)
        fields_added.append("data_info_section")

    return {
        "success": True,
        "fields_added": fields_added,
        "message": f"Added {len(fields_added)} fields to E-Boekhouden Settings",
    }
