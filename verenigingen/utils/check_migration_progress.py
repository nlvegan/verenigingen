#!/usr/bin/env python3
"""
Check progress of current migration
"""

import frappe


@frappe.whitelist()
def check_migration_progress():
    """Check the progress of the most recent migration"""

    # Get the most recent migration
    migrations = frappe.get_all(
        "E-Boekhouden Migration",
        filters={"migration_status": "In Progress"},
        fields=["name", "migration_name", "creation"],
        order_by="creation desc",
        limit=1,
    )

    if not migrations:
        print("No migration in progress")
        return

    migration_name = migrations[0]["name"]
    migration = frappe.get_doc("E-Boekhouden Migration", migration_name)

    print(f"\n=== MIGRATION PROGRESS: {migration_name} ===")
    print(f"Name: {migration.migration_name}")
    print(f"Status: {migration.migration_status}")
    print(f"Started: {migration.creation}")

    # Check for mutation cache count
    cache_count = frappe.db.count("EBoekhouden REST Mutation Cache")
    print(f"\nMutations in cache: {cache_count}")

    # Check for processed transactions
    if hasattr(migration, "total_mutations_fetched"):
        print(f"Total fetched: {migration.total_mutations_fetched}")
    if hasattr(migration, "mutations_imported"):
        print(f"Successfully imported: {migration.mutations_imported}")
    if hasattr(migration, "mutations_failed"):
        print(f"Failed: {migration.mutations_failed}")

    # Check recent debug log entries
    if hasattr(migration, "debug_log") and migration.debug_log:
        lines = migration.debug_log.split("\n")
        print(f"\nDebug log entries: {len(lines)}")

        # Show last 10 lines
        print("\nLast 10 log entries:")
        for line in lines[-10:]:
            print(f"  {line}")

        # Count errors
        error_count = sum(1 for line in lines if "ERROR" in line or "Failed" in line)
        if error_count > 0:
            print(f"\nTotal errors found: {error_count}")

            # Show first few errors
            print("\nFirst 5 errors:")
            error_lines = [line for line in lines if "ERROR" in line or "Failed" in line]
            for i, error_line in enumerate(error_lines[:5]):
                print(f"  {i + 1}. {error_line}")

    # Check recent GL/Journal entries
    recent_je = frappe.db.sql(
        """
        SELECT COUNT(*) as count
        FROM `tabJournal Entry`
        WHERE creation > %s
    """,
        (migration.creation,),
    )[0][0]

    recent_si = frappe.db.sql(
        """
        SELECT COUNT(*) as count
        FROM `tabSales Invoice`
        WHERE creation > %s
    """,
        (migration.creation,),
    )[0][0]

    recent_pi = frappe.db.sql(
        """
        SELECT COUNT(*) as count
        FROM `tabPurchase Invoice`
        WHERE creation > %s
    """,
        (migration.creation,),
    )[0][0]

    recent_pe = frappe.db.sql(
        """
        SELECT COUNT(*) as count
        FROM `tabPayment Entry`
        WHERE creation > %s
    """,
        (migration.creation,),
    )[0][0]

    print("\nDocuments created since migration start:")
    print(f"  Journal Entries: {recent_je}")
    print(f"  Sales Invoices: {recent_si}")
    print(f"  Purchase Invoices: {recent_pi}")
    print(f"  Payment Entries: {recent_pe}")
    print(f"  Total: {recent_je + recent_si + recent_pi + recent_pe}")

    return {
        "migration_name": migration_name,
        "status": migration.migration_status,
        "cache_count": cache_count,
        "documents_created": recent_je + recent_si + recent_pi + recent_pe,
    }


if __name__ == "__main__":
    print("Check migration progress")
