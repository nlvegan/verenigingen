#!/usr/bin/env python3

import frappe


@frappe.whitelist()
def debug_member_07_0030():
    """Debug member 07-0030 data and dues history issues"""
    try:
        member = frappe.get_doc("Member", "Assoc-Member-2025-07-0030")
        result = {}

        # Basic member data
        result["member_data"] = {
            "name": member.name,
            "next_invoice_date": member.next_invoice_date,
            "current_dues_schedule": member.current_dues_schedule,
            "dues_rate": member.dues_rate,
            "current_membership_details": member.current_membership_details,
        }

        # Current dues schedule data
        if member.current_dues_schedule:
            schedule = frappe.get_doc("Membership Dues Schedule", member.current_dues_schedule)
            result["current_schedule"] = {
                "name": schedule.name,
                "next_invoice_date": schedule.next_invoice_date,
                "last_invoice_date": schedule.last_invoice_date,
                "billing_frequency": schedule.billing_frequency,
                "dues_rate": schedule.dues_rate,
            }

        # All memberships
        memberships = frappe.get_all(
            "Membership",
            filters={"member": member.name},
            fields=["name", "membership_type", "start_date", "renewal_date", "status"],
            order_by="start_date",
        )
        result["all_memberships"] = memberships

        # All dues schedules
        schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member.name},
            fields=[
                "name",
                "dues_rate",
                "billing_frequency",
                "next_invoice_date",
                "last_invoice_date",
                "membership",
            ],
            order_by="creation",
        )
        result["all_schedules"] = schedules

        # Current fee change history
        if hasattr(member, "fee_change_history") and member.fee_change_history:
            result["current_fee_history"] = [
                {
                    "change_date": row.change_date,
                    "old_rate": row.old_dues_rate,
                    "new_rate": row.new_dues_rate,
                    "reason": row.reason,
                }
                for row in member.fee_change_history
            ]
        else:
            result["current_fee_history"] = []

        return result

    except Exception as e:
        frappe.log_error(f"Error debugging member 07-0030: {str(e)}")
        return {"error": str(e)}
