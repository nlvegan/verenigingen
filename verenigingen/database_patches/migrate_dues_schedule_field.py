#!/usr/bin/env python3
"""
Data migration script to consolidate dues_schedule into current_dues_schedule
"""
import frappe


def execute():
    """
    Migrate data from dues_schedule to current_dues_schedule where missing
    """
    print("Starting dues_schedule field consolidation...")

    # Step 1: Copy dues_schedule to current_dues_schedule where current is NULL
    print("\n1. Backfilling missing current_dues_schedule values...")
    frappe.db.sql(
        """
        UPDATE `tabMember`
        SET current_dues_schedule = dues_schedule
        WHERE current_dues_schedule IS NULL
        AND dues_schedule IS NOT NULL
    """
    )
    frappe.db.commit()

    # Get count of updated records
    updated_count = frappe.db.sql(
        """
        SELECT COUNT(*) FROM `tabMember`
        WHERE current_dues_schedule IS NOT NULL
        AND dues_schedule IS NOT NULL
        AND current_dues_schedule = dues_schedule
    """
    )[0][0]

    print(f"   ✓ Backfilled {updated_count} member records")

    # Step 2: Report on any remaining mismatches
    print("\n2. Checking for mismatches...")
    mismatches = frappe.db.sql(
        """
        SELECT
            m.name,
            m.full_name,
            m.current_dues_schedule,
            m.dues_schedule,
            cds.status as current_status,
            ds.status as dues_status
        FROM `tabMember` m
        LEFT JOIN `tabMembership Dues Schedule` cds ON m.current_dues_schedule = cds.name
        LEFT JOIN `tabMembership Dues Schedule` ds ON m.dues_schedule = ds.name
        WHERE m.current_dues_schedule IS NOT NULL
        AND m.dues_schedule IS NOT NULL
        AND m.current_dues_schedule != m.dues_schedule
    """,
        as_dict=True,
    )

    if mismatches:
        print(f"   ⚠ Found {len(mismatches)} members with different values:")
        for mismatch in mismatches[:5]:  # Show first 5
            print(
                f"      {mismatch.name}: current={mismatch.current_dues_schedule} ({mismatch.current_status}), "
                f"dues={mismatch.dues_schedule} ({mismatch.dues_status})"
            )
        if len(mismatches) > 5:
            print(f"      ... and {len(mismatches) - 5} more")
        print("   Note: These will use current_dues_schedule (which is actively maintained)")
    else:
        print("   ✓ No mismatches found")

    # Step 3: Summary statistics
    print("\n3. Final statistics:")
    stats = frappe.db.sql(
        """
        SELECT
            COUNT(*) as total_members,
            SUM(CASE WHEN current_dues_schedule IS NOT NULL THEN 1 ELSE 0 END) as has_current,
            SUM(CASE WHEN dues_schedule IS NOT NULL THEN 1 ELSE 0 END) as has_dues,
            SUM(CASE WHEN current_dues_schedule IS NOT NULL AND dues_schedule IS NOT NULL
                AND current_dues_schedule = dues_schedule THEN 1 ELSE 0 END) as matching
        FROM `tabMember`
    """,
        as_dict=True,
    )[0]

    print(f"   Total members: {stats.total_members}")
    print(f"   Members with current_dues_schedule: {stats.has_current}")
    print(f"   Members with dues_schedule: {stats.has_dues}")
    print(f"   Members with matching values: {stats.matching}")

    print("\n✅ Data migration completed successfully")
    print("\nNext steps:")
    print("   1. Review any mismatches above")
    print("   2. Remove 'dues_schedule' field from member.json")
    print("   3. Run: bench migrate")


if __name__ == "__main__":
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    execute()
