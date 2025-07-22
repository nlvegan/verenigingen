#!/usr/bin/env python3

from datetime import datetime

import frappe


def debug_orphaned_member():
    """Debug the orphaned member issue by recreating the scenario"""

    # Initialize frappe
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    member_name = "Assoc-Member-2025-07-2897"

    print("=== DEBUGGING ORPHANED MEMBER ===")
    print(f"Member: {member_name}")

    # Get member details
    member = frappe.get_doc("Member", member_name)
    print(f"Full Name: {member.full_name}")
    print(f"Email: {member.email}")
    print(f"Creation: {member.creation}")

    # Get dues schedule
    schedules = frappe.get_all(
        "Membership Dues Schedule",
        filters={"member": member_name},
        fields=["name", "membership", "creation", "schedule_name", "billing_frequency", "dues_rate"],
    )

    print(f"\n=== DUES SCHEDULES ({len(schedules)}) ===")
    for schedule in schedules:
        print(f"Schedule: {schedule.name}")
        print(f"  Schedule Name: {schedule.schedule_name}")
        print(f"  Linked Membership: {schedule.membership}")
        print(f"  Billing Frequency: {schedule.billing_frequency}")
        print(f"  Dues Rate: {schedule.dues_rate}")
        print(f"  Creation: {schedule.creation}")

    # Try to understand what caused this by looking at recent test runs
    print(f"\n=== ANALYSIS ===")

    # Check if there are any memberships that should be linked
    all_memberships = frappe.get_all(
        "Membership", filters={"member": member_name}, fields=["name", "status", "creation", "docstatus"]
    )

    print(f"Memberships for this member: {len(all_memberships)}")
    for membership in all_memberships:
        print(f"  {membership.name}: {membership.status} (docstatus: {membership.docstatus})")

    # Check what might have created a dues schedule without membership
    # Look for recent test runs around the creation time
    creation_time = member.creation
    print(f"\nMember created at: {creation_time}")

    # Check other test members created around same time
    similar_time_range = frappe.db.sql(
        """
        SELECT name, full_name, email, creation
        FROM `tabMember`
        WHERE creation BETWEEN %s AND %s
        AND name != %s
        ORDER BY creation
    """,
        [
            (creation_time - frappe.utils.datetime.timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S"),
            (creation_time + frappe.utils.datetime.timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S"),
            member_name,
        ],
        as_dict=True,
    )

    print(f"\n=== OTHER MEMBERS CREATED AROUND SAME TIME ===")
    for similar_member in similar_time_range:
        print(
            f"  {similar_member.name}: {similar_member.full_name} ({similar_member.email}) - {similar_member.creation}"
        )

    # Check what test might create "Coverage Test" named members
    print(f"\n=== HYPOTHESIS ===")
    print("1. Member was created by some test framework")
    print("2. Test created dues schedule but failed to create/link membership")
    print("3. Email pattern 'coverage.test.timestamp@verenigingen.example' suggests coverage testing")
    print("4. Schedule name pattern 'Schedule-Member-Name-Daglid-001' suggests Dutch daily membership")

    # Try to reproduce the issue
    print(f"\n=== REPRODUCTION ATTEMPT ===")
    print("Looking for test patterns that might create similar data...")

    # This would be the pattern that might have created it
    timestamp = int(datetime.now().timestamp())
    test_email = f"coverage.test.{timestamp}@verenigingen.example"

    print(f"Simulated email pattern: {test_email}")
    print("This suggests a test framework that:")
    print("- Uses 'coverage' as prefix")
    print("- Uses 'Test' as last name")
    print("- Uses timestamp for uniqueness")
    print("- Uses 'verenigingen.example' domain")
    print("- Creates dues schedules independently of memberships")

    return {
        "member": member,
        "schedules": schedules,
        "analysis": "Member has dues schedule but no membership - likely test data creation bug",
    }


if __name__ == "__main__":
    result = debug_orphaned_member()
    print("\n=== CONCLUSION ===")
    print("This appears to be caused by a test that:")
    print("1. Creates a member")
    print("2. Creates a dues schedule")
    print("3. Fails to create or link the membership")
    print("4. Test framework doesn't clean up properly")
    print("\nRecommendation: Find and fix the test that creates this scenario")
