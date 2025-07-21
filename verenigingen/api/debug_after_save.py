#!/usr/bin/env python3

import frappe
from frappe.utils import flt


@frappe.whitelist()
def test_after_save_execution():
    """Test if after_save is being called and debug any issues"""

    member_name = "Assoc-Member-2025-07-0025"
    schedule_name = f"Auto-{member_name}-xehYos"

    try:
        # Get the document
        schedule_doc = frappe.get_doc("Membership Dues Schedule", schedule_name)

        # Check if after_save method exists
        result = {
            "has_after_save_method": hasattr(schedule_doc, "after_save"),
            "after_save_is_callable": callable(getattr(schedule_doc, "after_save", None)),
        }

        # Try calling after_save directly to see if there are any errors
        try:
            # Simulate the conditions of after_save
            schedule_doc.after_save()
            result["direct_after_save_call"] = "SUCCESS"
        except Exception as e:
            result["direct_after_save_call"] = f"ERROR: {str(e)}"

        return result

    except Exception as e:
        frappe.log_error(f"Error in test_after_save_execution: {str(e)}")
        return {"error": str(e)}
