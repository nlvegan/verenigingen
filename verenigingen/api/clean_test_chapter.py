import frappe

from verenigingen.utils.security.api_security_framework import OperationType, critical_api


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def clean_billing_test_chapter():
    """Clean up the Billing Test Chapter to remove invalid member references"""

    chapter_name = "Billing Test Chapter"

    if not frappe.db.exists("Chapter", chapter_name):
        return {"message": "Billing Test Chapter does not exist"}

    # Get the chapter
    chapter = frappe.get_doc("Chapter", chapter_name)

    # Track current member links
    original_members = len(chapter.members) if chapter.members else 0

    # Filter out members that no longer exist
    valid_members = []
    removed_members = []

    if chapter.members:
        for member_row in chapter.members:
            if frappe.db.exists("Member", member_row.member):
                valid_members.append(member_row)
            else:
                removed_members.append(member_row.member)

    # Clear the members table and rebuild with valid members only
    chapter.members = []
    for valid_member in valid_members:
        chapter.append("members", valid_member.as_dict())

    # Save the chapter
    chapter.save()

    return {
        "success": True,
        "original_member_count": original_members,
        "valid_member_count": len(valid_members),
        "removed_member_count": len(removed_members),
        "removed_members": removed_members[:10],  # Show first 10 for debugging
    }


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def delete_orphaned_test_members():
    """Delete test members that have no memberships or schedules"""

    # Get all test members (identified by last names used in tests)
    test_last_names = [
        "MonthlyToAnnual",
        "AnnualToQuarterly",
        "QuarterlyToMonthly",
        "DailyToAnnual",
        "SwitchyMcSwitchface",
        "Backdated",
    ]

    orphaned_members = []
    kept_members = []

    for last_name in test_last_names:
        members = frappe.get_all(
            "Member", filters={"last_name": last_name}, fields=["name", "first_name", "last_name"]
        )

        for member in members:
            # Check if member has any memberships or schedules
            memberships = frappe.get_all("Membership", filters={"member": member.name})
            schedules = frappe.get_all("Membership Dues Schedule", filters={"member": member.name})

            if not memberships and not schedules:
                # Safe to delete - no dependencies
                try:
                    frappe.delete_doc("Member", member.name, force=True)
                    orphaned_members.append(member.name)
                except Exception as e:
                    kept_members.append(f"{member.name}: {str(e)}")
            else:
                kept_members.append(
                    f"{member.name}: has {len(memberships)} memberships, {len(schedules)} schedules"
                )

    return {
        "deleted_count": len(orphaned_members),
        "kept_count": len(kept_members),
        "deleted_members": orphaned_members[:10],
        "kept_members": kept_members[:10],
    }
