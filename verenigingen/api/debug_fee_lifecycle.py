#!/usr/bin/env python3

import frappe
from frappe.utils import flt


@frappe.whitelist()
def debug_document_lifecycle():
    """Debug the document save lifecycle to understand when old values are captured"""

    member_name = "Assoc-Member-2025-07-0025"
    schedule_name = f"Auto-{member_name}-xehYos"

    try:
        # Get the document
        schedule_doc = frappe.get_doc("Membership Dues Schedule", schedule_name)

        # Show current state
        result = {
            "current_dues_rate": schedule_doc.dues_rate,
            "has_old_dues_rate": hasattr(schedule_doc, "_old_dues_rate"),
            "old_dues_rate": getattr(schedule_doc, "_old_dues_rate", "Not set"),
        }

        # Let's check what happens when we retrieve the doc from DB separately
        db_doc = frappe.get_doc("Membership Dues Schedule", schedule_name)
        result["db_doc_dues_rate"] = db_doc.dues_rate
        result["same_as_current"] = db_doc.dues_rate == schedule_doc.dues_rate

        # Check if the issue is with has_value_changed
        result["has_value_changed_dues_rate"] = schedule_doc.has_value_changed("dues_rate")
        result["has_value_changed_status"] = schedule_doc.has_value_changed("status")

        # Check if doc is loaded from database
        result["is_new"] = schedule_doc.is_new()

        # Try to see the _doc_before_save if it exists
        result["has_doc_before_save"] = hasattr(schedule_doc, "_doc_before_save")

        return result

    except Exception as e:
        frappe.log_error(f"Error in debug_document_lifecycle: {str(e)}")
        return {"error": str(e)}
