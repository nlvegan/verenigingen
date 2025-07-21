#!/usr/bin/env python3

import frappe
from frappe.utils import now_datetime


@frappe.whitelist()
def debug_member_fee_history():
    """Debug fee change history for member Assoc-Member-2025-07-0025"""

    member_name = "Assoc-Member-2025-07-0025"

    try:
        # Get member document
        member_doc = frappe.get_doc("Member", member_name)

        result = {
            "member_name": member_name,
            "current_dues_rate": member_doc.get("dues_rate"),
            "fee_change_history_count": len(member_doc.get("fee_change_history", [])),
            "fee_change_history": [],
        }

        # Get fee change history
        for history in member_doc.get("fee_change_history", []):
            result["fee_change_history"].append(
                {
                    "change_date": str(history.get("change_date")),
                    "change_type": history.get("change_type"),
                    "old_dues_rate": history.get("old_dues_rate"),
                    "new_dues_rate": history.get("new_dues_rate"),
                    "reason": history.get("reason"),
                    "changed_by": history.get("changed_by"),
                    "dues_schedule": history.get("dues_schedule"),
                }
            )

        # Find dues schedules for this member
        dues_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name},
            fields=["name", "status", "dues_rate", "billing_frequency", "modified", "modified_by"],
        )

        result["dues_schedules"] = dues_schedules

        # Check the specific schedule mentioned
        schedule_name = f"Auto-{member_name}-xehYos"
        try:
            schedule_doc = frappe.get_doc("Membership Dues Schedule", schedule_name)
            result["target_schedule"] = {
                "name": schedule_doc.name,
                "status": schedule_doc.status,
                "dues_rate": schedule_doc.dues_rate,
                "billing_frequency": schedule_doc.billing_frequency,
                "modified": str(schedule_doc.modified),
                "modified_by": schedule_doc.modified_by,
                "is_template": schedule_doc.get("is_template", False),
                "member": schedule_doc.get("member"),
            }
        except frappe.DoesNotExistError:
            result["target_schedule"] = f"Schedule {schedule_name} not found"

        return result

    except Exception as e:
        frappe.log_error(f"Error in debug_member_fee_history: {str(e)}")
        return {"error": str(e)}


@frappe.whitelist()
def test_fee_history_tracking():
    """Test the fee change history tracking mechanism"""

    member_name = "Assoc-Member-2025-07-0025"
    schedule_name = f"Auto-{member_name}-xehYos"

    try:
        # Get the schedule
        schedule_doc = frappe.get_doc("Membership Dues Schedule", schedule_name)

        # Check if tracking should work
        result = {
            "schedule_exists": True,
            "schedule_name": schedule_doc.name,
            "is_template": schedule_doc.get("is_template", False),
            "has_member": bool(schedule_doc.get("member")),
            "member_value": schedule_doc.get("member"),
            "current_dues_rate": schedule_doc.dues_rate,
        }

        # Check if after_save method exists
        result["has_after_save_method"] = hasattr(schedule_doc, "after_save")
        result["has_add_billing_history_method"] = hasattr(schedule_doc, "add_billing_history_entry")

        return result

    except frappe.DoesNotExistError:
        return {"error": f"Schedule {schedule_name} does not exist"}
    except Exception as e:
        frappe.log_error(f"Error in test_fee_history_tracking: {str(e)}")
        return {"error": str(e)}
