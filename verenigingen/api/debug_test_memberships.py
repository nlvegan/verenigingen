#!/usr/bin/env python3

import frappe


@frappe.whitelist()
def check_test_memberships():
    """Check the status of test memberships"""
    print("=== Test Membership Status Analysis ===")

    # Get recent test memberships
    memberships = frappe.get_all(
        "Membership",
        filters={"member": ["like", "%Assoc-Member%"]},
        fields=["name", "member", "status", "docstatus", "start_date", "renewal_date"],
        limit=10,
        order_by="creation desc",
    )

    print(f"Found {len(memberships)} test memberships:")
    for m in memberships:
        print(f"  • {m.name}: Member={m.member}, Status={m.status}, DocStatus={m.docstatus}")
        print(f"    Start: {m.start_date}, Renewal: {m.renewal_date}")

    # Check for any active memberships
    active_memberships = frappe.get_all(
        "Membership",
        filters={"status": "Active", "docstatus": 1},
        fields=["name", "member", "start_date", "renewal_date"],
        limit=5,
    )

    print(f"\nFound {len(active_memberships)} active memberships:")
    for m in active_memberships:
        print(f"  • {m.name}: Member={m.member}")
        print(f"    Start: {m.start_date}, Renewal: {m.renewal_date}")

    return {"memberships": len(memberships), "active": len(active_memberships)}
