#!/usr/bin/env python3

import frappe
from frappe.utils import flt


@frappe.whitelist()
def debug_change_detection():
    """Debug Frappe's change detection mechanism"""

    member_name = "Assoc-Member-2025-07-0025"
    schedule_name = f"Auto-{member_name}-xehYos"

    try:
        # Get the document
        schedule_doc = frappe.get_doc("Membership Dues Schedule", schedule_name)
        current_dues_rate = schedule_doc.dues_rate

        # Make a change
        new_dues_rate = current_dues_rate + 0.01
        schedule_doc.dues_rate = new_dues_rate

        # Check change detection before save
        result = {
            "before_save": {
                "has_value_changed": schedule_doc.has_value_changed("dues_rate"),
                "get_db_value": schedule_doc.get_db_value("dues_rate"),
                "current_dues_rate": schedule_doc.dues_rate,
                "is_new": schedule_doc.is_new(),
            }
        }

        # Save and check after_save detection
        # Add a flag to track if after_save is called
        original_after_save = schedule_doc.after_save
        after_save_called = []

        def debug_after_save():
            after_save_called.append(
                {
                    "has_value_changed": schedule_doc.has_value_changed("dues_rate"),
                    "get_db_value": schedule_doc.get_db_value("dues_rate"),
                    "current_dues_rate": schedule_doc.dues_rate,
                }
            )
            return original_after_save()

        schedule_doc.after_save = debug_after_save
        schedule_doc.save()

        result["after_save"] = after_save_called[0] if after_save_called else "after_save not called"

        # Revert the change
        schedule_doc.dues_rate = current_dues_rate
        schedule_doc.save()

        return result

    except Exception as e:
        frappe.log_error(f"Error in debug_change_detection: {str(e)}")
        return {"error": str(e)}
