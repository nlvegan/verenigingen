#!/usr/bin/env python3

import frappe


def debug_member_dues_schedule():
    """Debug why the member with dues schedule is not appearing"""

    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    # Check specific member
    target_member = "Assoc-Member-2025-07-1943"

    print(f"=== Debugging member: {target_member} ===")

    # 1. Check if member exists and has customer
    member = frappe.db.get_value(
        "Member", target_member, ["name", "full_name", "status", "customer"], as_dict=True
    )
    print(f"Member data: {member}")

    if not member or not member.customer:
        print("❌ Member not found or has no customer")
        return

    # 2. Check if member has dues schedule
    schedules = frappe.get_all(
        "Membership Dues Schedule",
        filters={"member": target_member, "status": "Active"},
        fields=[
            "name",
            "next_invoice_date",
            "last_invoice_date",
            "billing_frequency",
            "dues_rate",
            "auto_generate",
        ],
        order_by="modified desc",
        limit=1,
    )
    print(f"Schedules found: {schedules}")

    # 3. Test the filtering logic from the report
    member_filters = {"docstatus": ["!=", 2]}
    # Apply standard filters (same as report)
    member_filters["status"] = ["!=", "Terminated"]
    member_filters["status"] = ["not in", ["Terminated", "Suspended"]]

    print(f"Filters: {member_filters}")

    # 4. Get members using same logic as report
    members = frappe.get_all(
        "Member",
        filters=member_filters,
        fields=["name", "full_name", "email", "status", "customer", "member_since"],
        order_by="member_since desc",
    )

    # Find our target member
    target_found = [m for m in members if m.name == target_member]
    print(f"Target member found in query: {len(target_found) > 0}")
    if target_found:
        print(f"Target member data: {target_found[0]}")

    # 5. Check total members returned
    print(f"Total members returned: {len(members)}")

    # 6. Check members with schedules
    members_with_schedules = []
    for member in members[:10]:  # Check first 10 to see pattern
        schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member.name, "status": "Active"},
            fields=["name"],
            limit=1,
        )
        if schedules:
            members_with_schedules.append(member.name)

    print(f"Members with schedules in first 10: {members_with_schedules}")

    frappe.db.close()


if __name__ == "__main__":
    debug_member_dues_schedule()
