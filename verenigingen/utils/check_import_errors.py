#!/usr/bin/env python3
"""
Check errors from recent import
"""

import frappe


@frappe.whitelist()
def check_import_errors():
    """Check for recent import errors"""

    # Get the most recent migration
    migration_name = "EBMIG-2025-00065"
    migration = frappe.get_doc("E-Boekhouden Migration", migration_name)

    print(f"\n=== CHECKING MIGRATION: {migration_name} ===")
    print(f"Status: {migration.migration_status}")

    # Check for recent documents
    recent_docs = frappe.db.sql(
        """
        SELECT
            'Journal Entry' as doctype,
            COUNT(*) as count,
            MAX(creation) as latest
        FROM `tabJournal Entry`
        WHERE creation > DATE_SUB(NOW(), INTERVAL 10 MINUTE)

        UNION ALL

        SELECT
            'Sales Invoice' as doctype,
            COUNT(*) as count,
            MAX(creation) as latest
        FROM `tabSales Invoice`
        WHERE creation > DATE_SUB(NOW(), INTERVAL 10 MINUTE)

        UNION ALL

        SELECT
            'Purchase Invoice' as doctype,
            COUNT(*) as count,
            MAX(creation) as latest
        FROM `tabPurchase Invoice`
        WHERE creation > DATE_SUB(NOW(), INTERVAL 10 MINUTE)

        UNION ALL

        SELECT
            'Payment Entry' as doctype,
            COUNT(*) as count,
            MAX(creation) as latest
        FROM `tabPayment Entry`
        WHERE creation > DATE_SUB(NOW(), INTERVAL 10 MINUTE)
    """,
        as_dict=True,
    )

    print("\nRecent documents (last 10 minutes):")
    total = 0
    for doc in recent_docs:
        if doc.count > 0:
            print(f"  {doc.doctype}: {doc.count} (latest: {doc.latest})")
            total += doc.count

    if total == 0:
        print("  No documents created in the last 10 minutes")

    # Check error log
    error_logs = frappe.get_all(
        "Error Log",
        filters={"creation": [">", frappe.utils.add_to_date(frappe.utils.now(), minutes=-10)]},
        fields=["method", "error", "creation"],
        order_by="creation desc",
        limit=10,
    )

    if error_logs:
        print(f"\nRecent errors ({len(error_logs)}):")
        for i, log in enumerate(error_logs[:5]):
            print(f"\n{i + 1}. {log.creation}")
            print(f"   Method: {log.method}")
            error_preview = str(log.error)[:200] + "..." if len(str(log.error)) > 200 else str(log.error)
            print(f"   Error: {error_preview}")

            # Look for specific error patterns
            if "account mapping" in str(log.error).lower():
                print("   Type: Missing account mapping")
            elif "customer" in str(log.error).lower() or "supplier" in str(log.error).lower():
                print("   Type: Missing party (customer/supplier)")
            elif "ledger" in str(log.error).lower():
                print("   Type: Missing ledger mapping")
    else:
        print("\nNo recent errors found")

    # Try to get a sample failed mutation
    print("\n=== CHECKING FOR FAILED MUTATIONS ===")

    # Look for recent failed journal entries in error log
    failed_mutations = frappe.db.sql(
        """
        SELECT error
        FROM `tabError Log`
        WHERE error LIKE '%eboekhouden%'
        AND error LIKE '%mutation%'
        AND creation > DATE_SUB(NOW(), INTERVAL 30 MINUTE)
        LIMIT 5
    """,
        as_dict=True,
    )

    if failed_mutations:
        print(f"\nFound {len(failed_mutations)} failed mutation errors:")
        for i, err in enumerate(failed_mutations):
            # Extract mutation ID from error
            error_text = str(err.error)
            if "mutation" in error_text.lower():
                print(f"\n{i + 1}. {error_text[:300]}...")

    return {
        "migration": migration_name,
        "status": migration.migration_status,
        "recent_docs": total,
        "recent_errors": len(error_logs),
    }


if __name__ == "__main__":
    print("Check import errors")
