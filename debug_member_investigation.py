#!/usr/bin/env python3

import frappe


@frappe.whitelist()
def investigate_test_member():
    """Investigate member Assoc-Member-2025-07-2897"""

    member_name = "Assoc-Member-2025-07-2897"

    # Check if member exists
    if not frappe.db.exists("Member", member_name):
        return {"error": f"Member {member_name} does not exist"}

    # Get member details
    member = frappe.get_doc("Member", member_name)

    # Get all memberships for this member
    memberships = frappe.get_all(
        "Membership",
        filters={"member": member_name},
        fields=["name", "membership_type", "start_date", "status", "docstatus"],
    )

    # Get all dues schedules for this member
    dues_schedules = frappe.get_all(
        "Membership Dues Schedule",
        filters={"member": member_name},
        fields=["name", "membership", "billing_frequency", "status", "dues_rate", "creation"],
    )

    # Look for any test data patterns in member name/email
    test_patterns = []
    if "test" in member.email.lower():
        test_patterns.append("test email")
    if any(name in member.last_name for name in ["Test", "Mock", "Demo"]):
        test_patterns.append("test last name")
    if any(name in member.first_name for name in ["Test", "Mock", "Demo"]):
        test_patterns.append("test first name")

    # Check for chapter membership
    chapter_memberships = frappe.get_all(
        "Chapter Member", filters={"member": member_name}, fields=["chapter", "status", "chapter_join_date"]
    )

    # Look for contribution amendment requests
    amendment_requests = frappe.get_all(
        "Contribution Amendment Request",
        filters={"member": member_name},
        fields=["name", "amendment_type", "status", "creation"],
    )

    return {
        "member_details": {
            "name": member.name,
            "full_name": member.full_name,
            "email": member.email,
            "status": member.status,
            "creation": str(member.creation),
            "primary_chapter": getattr(member, "primary_chapter", None),
        },
        "memberships": memberships,
        "dues_schedules": dues_schedules,
        "chapter_memberships": chapter_memberships,
        "amendment_requests": amendment_requests,
        "test_patterns": test_patterns,
        "analysis": {
            "has_membership": len(memberships) > 0,
            "has_dues_schedule": len(dues_schedules) > 0,
            "membership_count": len(memberships),
            "dues_schedule_count": len(dues_schedules),
        },
    }


if __name__ == "__main__":
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    result = investigate_test_member()

    print("=== MEMBER INVESTIGATION RESULTS ===")
    print(f"Member: {result['member_details']['name']}")
    print(f"Full Name: {result['member_details']['full_name']}")
    print(f"Email: {result['member_details']['email']}")
    print(f"Status: {result['member_details']['status']}")
    print(f"Created: {result['member_details']['creation']}")
    print(f"Primary Chapter: {result['member_details']['primary_chapter']}")

    print(f"\n=== ANALYSIS ===")
    print(f"Has Membership: {result['analysis']['has_membership']}")
    print(f"Has Dues Schedule: {result['analysis']['has_dues_schedule']}")
    print(f"Membership Count: {result['analysis']['membership_count']}")
    print(f"Dues Schedule Count: {result['analysis']['dues_schedule_count']}")

    if result["test_patterns"]:
        print(f"Test Patterns: {', '.join(result['test_patterns'])}")

    print(f"\n=== MEMBERSHIPS ({len(result['memberships'])}) ===")
    for membership in result["memberships"]:
        print(
            f"  {membership['name']}: {membership['membership_type']} - {membership['status']} (docstatus: {membership['docstatus']})"
        )

    print(f"\n=== DUES SCHEDULES ({len(result['dues_schedules'])}) ===")
    for schedule in result["dues_schedules"]:
        print(
            f"  {schedule['name']}: {schedule['billing_frequency']} - {schedule['status']} (€{schedule['dues_rate']}) - Linked Membership: {schedule.get('membership', 'None')}"
        )
        print(f"    Created: {schedule['creation']}")

    print(f"\n=== CHAPTER MEMBERSHIPS ({len(result['chapter_memberships'])}) ===")
    for chapter_membership in result["chapter_memberships"]:
        print(
            f"  Chapter: {chapter_membership['chapter']} - Status: {chapter_membership['status']} - Join Date: {chapter_membership['chapter_join_date']}"
        )

    print(f"\n=== AMENDMENT REQUESTS ({len(result['amendment_requests'])}) ===")
    for request in result["amendment_requests"]:
        print(
            f"  {request['name']}: {request['amendment_type']} - {request['status']} - Created: {request['creation']}"
        )
