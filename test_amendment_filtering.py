#!/usr/bin/env python3

import frappe

from verenigingen.verenigingen.doctype.contribution_amendment_request.contribution_amendment_request import (
    get_member_pending_contribution_amendments,
)


def test_amendment_filtering():
    """Test the amendment filtering functionality"""

    # Test member that should have no outdated amendments showing
    member_name = "Assoc-Member-2025-07-0030"
    print(f"Testing amendment filtering for member: {member_name}")

    # Get filtered amendments (should exclude past effective dates)
    amendments = get_member_pending_contribution_amendments(member_name)
    print(f"Found {len(amendments)} pending amendments after filtering:")
    for i, amendment in enumerate(amendments, 1):
        print(
            f"  {i}. {amendment.get('name', 'N/A')} - Status: {amendment.get('status', 'N/A')} - Effective: {amendment.get('effective_date', 'N/A')}"
        )

    print("\nRAW query for comparison (no date filtering):")
    raw_amendments = frappe.get_all(
        "Contribution Amendment Request",
        filters={"member": member_name, "status": ["in", ["Draft", "Pending Approval", "Approved"]]},
        fields=["name", "status", "effective_date"],
        order_by="creation desc",
    )
    print(f"Raw query returned {len(raw_amendments)} amendments:")
    for i, amendment in enumerate(raw_amendments, 1):
        print(
            f"  {i}. {amendment.get('name', 'N/A')} - Status: {amendment.get('status', 'N/A')} - Effective: {amendment.get('effective_date', 'N/A')}"
        )

    # Show the difference
    filtered_out = len(raw_amendments) - len(amendments)
    print(f"\nFiltering removed {filtered_out} amendments that were past their effective date")

    return {
        "member": member_name,
        "filtered_count": len(amendments),
        "raw_count": len(raw_amendments),
        "filtered_out_count": filtered_out,
        "success": True,
    }


def test_fee_change_history():
    """Test the fee change history functionality"""

    # Test member that should have proper fee change history
    member_name = "Assoc-Member-2025-07-0017"
    print(f"\n=== Testing fee change history for member: {member_name} ===")

    # Get member data
    try:
        member = frappe.get_doc("Member", member_name)
        print(f"Member found: {member.full_name}")

        # Check current fee change history
        history_count = len(member.fee_change_history or [])
        print(f"Current fee change history entries: {history_count}")

        if history_count > 0:
            print("Recent entries:")
            for i, entry in enumerate(member.fee_change_history[-5:], 1):  # Show last 5
                print(f"  {i}. {entry.change_date} - {entry.change_type} - Rate: €{entry.new_dues_rate}")

        # Get dues schedules for comparison
        dues_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name},
            fields=["name", "schedule_name", "dues_rate", "status", "creation"],
            order_by="creation desc",
        )

        print(f"\nDues schedules for this member: {len(dues_schedules)}")
        for i, schedule in enumerate(dues_schedules, 1):
            print(f"  {i}. {schedule.name} - Rate: €{schedule.dues_rate} - Status: {schedule.status}")

        return {
            "member": member_name,
            "history_entries": history_count,
            "dues_schedules": len(dues_schedules),
            "success": True,
        }

    except Exception as e:
        print(f"Error testing fee change history: {e}")
        return {"member": member_name, "error": str(e), "success": False}


if __name__ == "__main__":
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    # Test amendment filtering
    result1 = test_amendment_filtering()

    # Test fee change history
    result2 = test_fee_change_history()

    print(f"\n=== Test Results ===")
    print(f"Amendment filtering: {'PASS' if result1['success'] else 'FAIL'}")
    print(f"Fee change history: {'PASS' if result2['success'] else 'FAIL'}")
