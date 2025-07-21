#!/usr/bin/env python3

import frappe
from frappe.utils import flt, now_datetime


@frappe.whitelist()
def test_fee_change_tracking():
    """Test that fee change history tracking is working after the fix"""

    member_name = "Assoc-Member-2025-07-0025"
    schedule_name = f"Auto-{member_name}-xehYos"

    try:
        # Get current state
        schedule_doc = frappe.get_doc("Membership Dues Schedule", schedule_name)
        current_dues_rate = schedule_doc.dues_rate

        # Record initial history count
        member_doc = frappe.get_doc("Member", member_name)
        initial_history_count = len(member_doc.get("fee_change_history", []))

        # Make a small change to test tracking
        new_dues_rate = current_dues_rate + 0.01  # Add 1 cent

        schedule_doc.dues_rate = new_dues_rate
        schedule_doc.save()

        # Reload member doc and check if new history entry was created
        member_doc.reload()
        final_history_count = len(member_doc.get("fee_change_history", []))

        # Check if history was added
        history_added = final_history_count > initial_history_count

        if history_added:
            # Get the latest entry
            latest_entry = member_doc.fee_change_history[-1]
            result = {
                "success": True,
                "message": "Fee change tracking is working!",
                "initial_history_count": initial_history_count,
                "final_history_count": final_history_count,
                "latest_entry": {
                    "change_date": str(latest_entry.change_date),
                    "change_type": latest_entry.change_type,
                    "old_dues_rate": flt(latest_entry.old_dues_rate, 2),
                    "new_dues_rate": flt(latest_entry.new_dues_rate, 2),
                    "reason": latest_entry.reason,
                    "changed_by": latest_entry.changed_by,
                },
            }

            # Revert the change
            schedule_doc.dues_rate = current_dues_rate
            schedule_doc.save()

        else:
            result = {
                "success": False,
                "message": "Fee change tracking is still not working",
                "initial_history_count": initial_history_count,
                "final_history_count": final_history_count,
                "current_dues_rate": current_dues_rate,
                "new_dues_rate": new_dues_rate,
            }

            # Revert the change anyway
            schedule_doc.dues_rate = current_dues_rate
            schedule_doc.save()

        return result

    except Exception as e:
        frappe.log_error(f"Error in test_fee_change_tracking: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_billing_frequency_tracking():
    """Test that billing frequency change tracking is working"""

    member_name = "Assoc-Member-2025-07-0025"
    schedule_name = f"Auto-{member_name}-xehYos"

    try:
        # Get current state
        schedule_doc = frappe.get_doc("Membership Dues Schedule", schedule_name)
        current_frequency = schedule_doc.billing_frequency

        # Record initial history count
        member_doc = frappe.get_doc("Member", member_name)
        initial_history_count = len(member_doc.get("fee_change_history", []))

        # Change billing frequency
        new_frequency = "Monthly" if current_frequency != "Monthly" else "Annual"

        schedule_doc.billing_frequency = new_frequency
        schedule_doc.save()

        # Reload member doc and check if new history entry was created
        member_doc.reload()
        final_history_count = len(member_doc.get("fee_change_history", []))

        # Check if history was added
        history_added = final_history_count > initial_history_count

        result = {
            "success": history_added,
            "message": "Billing frequency tracking working!"
            if history_added
            else "Billing frequency tracking not working",
            "initial_history_count": initial_history_count,
            "final_history_count": final_history_count,
            "old_frequency": current_frequency,
            "new_frequency": new_frequency,
        }

        if history_added:
            latest_entry = member_doc.fee_change_history[-1]
            result["latest_entry"] = {
                "change_type": latest_entry.change_type,
                "billing_frequency": latest_entry.billing_frequency,
                "change_date": str(latest_entry.change_date),
            }

        # Revert the change
        schedule_doc.billing_frequency = current_frequency
        schedule_doc.save()

        return result

    except Exception as e:
        frappe.log_error(f"Error in test_billing_frequency_tracking: {str(e)}")
        return {"success": False, "error": str(e)}
