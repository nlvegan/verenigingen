"""
Setup required Frappe test fixtures before running tests.

This script creates the _Test Role records that Frappe's test framework expects.
Run this before running the full test suite:

    bench --site dev.veganisme.net execute scripts.testing.setup_test_fixtures.setup

Or use the helper command:

    python scripts/testing/setup_test_fixtures.py
"""

import frappe


def setup():
    """Create all required test fixtures for the Frappe test framework."""
    print("Setting up Frappe test fixtures...")

    # Create test roles required by Frappe's core test_records.json
    test_roles = [
        {"role_name": "_Test Role", "desk_access": 1},
        {"role_name": "_Test Role 2", "desk_access": 1},
        {"role_name": "_Test Role 3", "desk_access": 1},
        {"role_name": "_Test Role 4", "desk_access": 0},
    ]

    created = 0
    skipped = 0

    for role_data in test_roles:
        role_name = role_data["role_name"]
        if not frappe.db.exists("Role", role_name):
            doc = frappe.get_doc({
                "doctype": "Role",
                **role_data
            })
            doc.insert(ignore_permissions=True)
            print(f"  Created: {role_name}")
            created += 1
        else:
            print(f"  Exists: {role_name}")
            skipped += 1

    frappe.db.commit()
    print(f"\nTest fixtures setup complete: {created} created, {skipped} already existed")
    return created


def cleanup():
    """Remove test fixtures (use after testing or for cleanup)."""
    print("Cleaning up test fixtures...")

    test_roles = ["_Test Role", "_Test Role 2", "_Test Role 3", "_Test Role 4"]

    deleted = 0
    for role_name in test_roles:
        if frappe.db.exists("Role", role_name):
            # First remove from Has Role table (user assignments)
            frappe.db.delete("Has Role", {"role": role_name})
            # Then delete the role itself
            frappe.delete_doc("Role", role_name, force=True, ignore_permissions=True)
            print(f"  Deleted: {role_name}")
            deleted += 1

    frappe.db.commit()
    print(f"\nCleanup complete: {deleted} roles removed")
    return deleted


if __name__ == "__main__":
    # When run directly, just print instructions
    print(__doc__)
