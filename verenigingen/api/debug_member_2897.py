import frappe


@frappe.whitelist()
def investigate_member_2897():
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

    # Check for chapter membership - need to check if Chapter Member table exists and correct field names
    chapter_memberships = []
    try:
        # First check what fields exist in Chapter doctype members table
        chapter_docs = frappe.get_all("Chapter", fields=["name"])
        for chapter in chapter_docs:
            chapter_doc = frappe.get_doc("Chapter", chapter.name)
            if hasattr(chapter_doc, "members") and chapter_doc.members:
                for member_row in chapter_doc.members:
                    if member_row.member == member_name:
                        chapter_memberships.append(
                            {
                                "chapter": chapter.name,
                                "status": getattr(member_row, "status", "Unknown"),
                                "chapter_join_date": getattr(member_row, "chapter_join_date", "Unknown"),
                            }
                        )
    except Exception as e:
        chapter_memberships = [{"error": str(e)}]

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
