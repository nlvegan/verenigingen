"""
Orphaned Child Table Records Report

Identifies child table records whose parent documents have been deleted.
This data integrity report helps maintain database health and prevent
LinkExistsError issues when deleting documents.
"""

import frappe
from frappe import _


def execute(filters=None):
    """
    Execute the Orphaned Child Table Records report.

    Returns:
        tuple: (columns, data) for Frappe report display
    """
    columns = get_columns()
    data = get_data(filters)

    return columns, data


def get_columns():
    """Define report columns."""
    return [
        {"fieldname": "child_table", "label": _("Child Table"), "fieldtype": "Data", "width": 250},
        {
            "fieldname": "parent_doctype",
            "label": _("Parent DocType"),
            "fieldtype": "Link",
            "options": "DocType",
            "width": 200,
        },
        {"fieldname": "orphaned_count", "label": _("Orphaned Records"), "fieldtype": "Int", "width": 130},
        {"fieldname": "sample_parent", "label": _("Sample Parent ID"), "fieldtype": "Data", "width": 200},
        {"fieldname": "module", "label": _("Module"), "fieldtype": "Data", "width": 150},
    ]


def get_data(filters=None):
    """
    Fetch orphaned child table records data.

    Uses the orphaned_child_table_cleanup utility for consistency.
    """
    from verenigingen.utils.orphaned_child_table_cleanup import detect_orphaned_child_tables

    # Get orphaned records detection results
    results = detect_orphaned_child_tables()

    if not results.get("success"):
        frappe.msgprint(
            _("Error detecting orphaned records: {0}").format(results.get("error")), indicator="red"
        )
        return []

    # Transform results into report data
    data = []
    for detail in results.get("details", []):
        sample_parent = ""
        if detail.get("sample_parents"):
            sample_parent = detail["sample_parents"][0]

        data.append(
            {
                "child_table": detail.get("child_table"),
                "parent_doctype": detail.get("parent_doctype"),
                "orphaned_count": detail.get("orphaned_count"),
                "sample_parent": sample_parent,
                "module": detail.get("module"),
            }
        )

    # Add summary row if there are orphans
    if data:
        frappe.msgprint(
            _("Found {0} orphaned records across {1} child tables. Use Admin Tools to clean up.").format(
                results.get("total_orphaned"), results.get("tables_affected")
            ),
            indicator="orange",
            title=_("Orphaned Records Detected"),
        )
    else:
        frappe.msgprint(
            _("No orphaned records found. Database is clean!"),
            indicator="green",
            title=_("Data Integrity Check"),
        )

    return data
