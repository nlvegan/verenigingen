#!/usr/bin/env python3
"""Direct cleanup script that bypasses API security framework"""

import os
import sys

# Change to bench directory
os.chdir("/home/frappe/frappe-bench")
sys.path.insert(0, "/home/frappe/frappe-bench/apps")

import frappe
from frappe.utils import getdate


def direct_cleanup(max_cleanup=20):
    """
    Direct database cleanup bypassing all validation and security checks.
    Only use in development for testing/maintenance.
    """
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    frappe.set_user("Administrator")

    results = {"orphaned_schedules": [], "orphaned_amendments": [], "errors": []}

    try:
        # Find orphaned schedules
        orphaned_schedules = frappe.db.sql(
            """
            SELECT mds.name, mds.member, mds.status
            FROM `tabMembership Dues Schedule` mds
            LEFT JOIN `tabMember` m ON mds.member = m.name
            WHERE mds.is_template = 0
                AND mds.member IS NOT NULL
                AND m.name IS NULL
            LIMIT %s
        """,
            (max_cleanup,),
            as_dict=True,
        )

        print(f"\nFound {len(orphaned_schedules)} orphaned schedules")

        for schedule in orphaned_schedules:
            try:
                frappe.db.delete("Membership Dues Schedule", {"name": schedule.name})
                results["orphaned_schedules"].append(schedule.name)
                print(f"  ✓ Deleted schedule: {schedule.name}")
            except Exception as e:
                error_msg = f"Failed to delete {schedule.name}: {str(e)}"
                results["errors"].append(error_msg)
                print(f"  ✗ {error_msg}")

        # Find orphaned amendments
        orphaned_amendments = frappe.db.sql(
            """
            SELECT ar.name, ar.member, ar.status
            FROM `tabContribution Amendment Request` ar
            LEFT JOIN `tabMember` m ON ar.member = m.name
            WHERE m.name IS NULL
                AND ar.member IS NOT NULL
            LIMIT %s
        """,
            (max_cleanup,),
            as_dict=True,
        )

        print(f"\nFound {len(orphaned_amendments)} orphaned amendments")

        for amendment in orphaned_amendments:
            try:
                frappe.db.delete("Contribution Amendment Request", {"name": amendment.name})
                results["orphaned_amendments"].append(amendment.name)
                print(f"  ✓ Deleted amendment: {amendment.name}")
            except Exception as e:
                error_msg = f"Failed to delete {amendment.name}: {str(e)}"
                results["errors"].append(error_msg)
                print(f"  ✗ {error_msg}")

        # Commit the changes
        frappe.db.commit()

        print(f"\n✓ Cleanup complete:")
        print(f"  - Deleted {len(results['orphaned_schedules'])} schedules")
        print(f"  - Deleted {len(results['orphaned_amendments'])} amendments")
        print(f"  - {len(results['errors'])} errors")

    except Exception as e:
        frappe.db.rollback()
        print(f"\n✗ Cleanup failed: {str(e)}")
        import traceback

        traceback.print_exc()
    finally:
        frappe.destroy()


if __name__ == "__main__":
    direct_cleanup(max_cleanup=50)
