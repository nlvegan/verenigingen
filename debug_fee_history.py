#!/usr/bin/env python3

import frappe


@frappe.whitelist()
def debug_fee_history():
    """Debug fee change history tracking issue"""

    # Get the member record
    member = frappe.get_doc("Member", "Assoc-Member-2025-07-0025")

    print(f"\n=== Member: {member.name} ===")
    print(f"Full name: {member.get('full_name', 'N/A')}")
    print(f"Current dues rate: {member.get('dues_rate', 'N/A')}")
    print(f"Current billing frequency: {member.get('billing_frequency', 'N/A')}")

    # Check fee change history
    print(f"\n=== Fee Change History ({len(member.get('fee_change_history', []))}) ===")
    for idx, history in enumerate(member.get("fee_change_history", [])):
        print(f"{idx+1}. Date: {history.get('date')}")
        print(f"   Change type: {history.get('change_type')}")
        print(f"   Old value: {history.get('old_value')}")
        print(f"   New value: {history.get('new_value')}")
        print(f"   Reason: {history.get('reason', 'N/A')}")
        print()

    # Get the dues schedule
    dues_schedule_name = f"Auto-{member.name}-xehYos"
    try:
        dues_schedule = frappe.get_doc("Subscription", dues_schedule_name)
        print(f"\n=== Dues Schedule: {dues_schedule.name} ===")
        print(f"Status: {dues_schedule.get('status')}")
        print(f"Modified: {dues_schedule.modified}")
        print(f"Modified by: {dues_schedule.modified_by}")

        # Check subscription plans
        print(f"\nPlans ({len(dues_schedule.get('plans', []))}):")
        for plan in dues_schedule.get("plans", []):
            print(f"- Plan: {plan.get('plan')}")
            print(f"  Qty: {plan.get('qty')}")

    except frappe.DoesNotExistError:
        print(f"Dues schedule {dues_schedule_name} not found")

    return {
        "member": member.as_dict(),
        "dues_schedule": dues_schedule.as_dict() if "dues_schedule" in locals() else None,
    }


if __name__ == "__main__":
    frappe.init()
    frappe.connect()
    result = debug_fee_history()
