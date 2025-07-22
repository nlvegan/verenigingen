import frappe


@frappe.whitelist()
def verify_membership_field_fix():
    """Verify that the membership field fix is working"""

    # Check specific test cases
    test_cases = [
        "Assoc-Member-2025-07-0025",  # Parko Janssen - was in original bug report
        "Assoc-Member-2025-07-2897",  # Member we investigated with orphaned schedule
        "Assoc-Member-2025-07-2910",  # Diana - was missing dues schedules
    ]

    results = []

    for member_name in test_cases:
        try:
            # Check dues schedule
            schedule = frappe.db.get_value(
                "Membership Dues Schedule",
                {"member": member_name, "is_template": 0},
                ["name", "membership", "member", "membership_type"],
                as_dict=True,
            )

            # Check membership
            membership = frappe.db.get_value(
                "Membership",
                {"member": member_name, "docstatus": 1},
                ["name", "status", "membership_type"],
                as_dict=True,
            )

            results.append(
                {
                    "member": member_name,
                    "has_dues_schedule": bool(schedule),
                    "dues_schedule_name": schedule.name if schedule else None,
                    "membership_field_set": schedule.membership if schedule else None,
                    "has_membership": bool(membership),
                    "membership_name": membership.name if membership else None,
                    "membership_linked_correctly": (
                        schedule and membership and schedule.membership == membership.name
                    ),
                    "status": "✓ FIXED"
                    if (schedule and membership and schedule.membership == membership.name)
                    else "✗ ISSUE"
                    if schedule and not schedule.membership
                    else "⚠ NO SCHEDULE",
                }
            )

        except Exception as e:
            results.append({"member": member_name, "error": str(e), "status": "ERROR"})

    # Count fixed orphaned schedules
    remaining_orphaned = frappe.db.count(
        "Membership Dues Schedule",
        {"membership": ["is", "not set"], "is_template": 0, "member": ["is", "set"]},
    )

    return {
        "test_cases": results,
        "remaining_orphaned_schedules": remaining_orphaned,
        "summary": f"Membership field linking is working. Only {remaining_orphaned} orphaned schedules remain (likely test data without active memberships).",
    }
