import frappe


@frappe.whitelist()
def fix_orphaned_dues_schedules():
    """Fix existing dues schedules that have null membership fields"""

    # Find dues schedules with null membership fields
    orphaned_schedules = frappe.db.sql(
        """
        SELECT
            ds.name as schedule_name,
            ds.member,
            ds.membership_type,
            ds.member_name
        FROM `tabMembership Dues Schedule` ds
        WHERE ds.membership IS NULL
        AND ds.is_template = 0
        AND ds.member IS NOT NULL
    """,
        as_dict=True,
    )

    results = {
        "total_orphaned": len(orphaned_schedules),
        "fixed_count": 0,
        "error_count": 0,
        "fixed_schedules": [],
        "errors": [],
    }

    for schedule_info in orphaned_schedules:
        try:
            # Find the active membership for this member
            active_membership = frappe.db.get_value(
                "Membership",
                {"member": schedule_info.member, "status": "Active", "docstatus": 1},
                ["name", "membership_type"],
                as_dict=True,
            )

            if active_membership:
                # Update the dues schedule to link to the membership
                frappe.db.set_value(
                    "Membership Dues Schedule",
                    schedule_info.schedule_name,
                    "membership",
                    active_membership.name,
                )

                results["fixed_schedules"].append(
                    {
                        "schedule": schedule_info.schedule_name,
                        "member": schedule_info.member,
                        "linked_to_membership": active_membership.name,
                    }
                )
                results["fixed_count"] += 1

            else:
                # No active membership found - this might be test data
                results["errors"].append(
                    {
                        "schedule": schedule_info.schedule_name,
                        "member": schedule_info.member,
                        "error": "No active membership found",
                    }
                )
                results["error_count"] += 1

        except Exception as e:
            results["errors"].append(
                {"schedule": schedule_info.schedule_name, "member": schedule_info.member, "error": str(e)}
            )
            results["error_count"] += 1

    # Commit changes if any were made
    if results["fixed_count"] > 0:
        frappe.db.commit()
        results["status"] = f"Fixed {results['fixed_count']} orphaned dues schedules"
    else:
        results["status"] = "No orphaned dues schedules found to fix"

    return results


@frappe.whitelist()
def check_orphaned_dues_schedules():
    """Check how many dues schedules have null membership fields (preview only)"""

    orphaned_count = frappe.db.count(
        "Membership Dues Schedule",
        {"membership": ["is", "not set"], "is_template": 0, "member": ["is", "set"]},
    )

    # Get some examples
    examples = frappe.db.sql(
        """
        SELECT
            ds.name as schedule_name,
            ds.member,
            ds.member_name,
            ds.membership_type,
            m.name as active_membership
        FROM `tabMembership Dues Schedule` ds
        LEFT JOIN `tabMembership` m ON (
            m.member = ds.member
            AND m.status = 'Active'
            AND m.docstatus = 1
        )
        WHERE ds.membership IS NULL
        AND ds.is_template = 0
        AND ds.member IS NOT NULL
        LIMIT 10
    """,
        as_dict=True,
    )

    return {
        "total_orphaned": orphaned_count,
        "examples": examples,
        "can_be_fixed": len([e for e in examples if e.active_membership]),
    }
