#!/usr/bin/env python3
"""
Run a clean import test with proper error tracking
"""

import frappe
from frappe.utils import now_datetime


@frappe.whitelist()
def run_clean_import_test():
    """Run a clean import of recent transactions"""

    print("Starting clean import test...")

    # First, clean up any test data from today
    print("\n1. Cleaning up test data...")
    cleanup_result = cleanup_test_data()
    print(f"   Cleaned up {cleanup_result['total']} documents")

    # Create new migration
    print("\n2. Creating new migration...")
    migration = frappe.new_doc("E-Boekhouden Migration")
    migration.migration_name = "Clean Test - {now_datetime()}"
    migration.migration_type = "Recent Transactions"
    migration.status = "In Progress"
    migration.import_method = "REST API"
    migration.mutation_limit = 100  # Process 100 most recent
    migration.save()
    print(f"   Created: {migration.name}")

    # Run the import
    print("\n3. Running import...")
    from verenigingen.utils.eboekhouden_rest_full_migration import start_full_rest_import

    try:
        # result = start_full_rest_import(migration.name)
        start_full_rest_import(migration.name)
        print("   Import completed")
    except Exception as e:
        print(f"   Import failed: {str(e)}")
        # result = {"error": str(e)}
        pass

    # Check results
    print("\n4. Checking results...")
    migration.reload()

    print(f"   Status: {migration.migration_status}")

    # Count created documents
    created = frappe.db.sql(
        """
        SELECT
            'Journal Entry' as doctype,
            COUNT(*) as count
        FROM `tabJournal Entry`
        WHERE creation > %s

        UNION ALL

        SELECT
            'Sales Invoice' as doctype,
            COUNT(*) as count
        FROM `tabSales Invoice`
        WHERE creation > %s

        UNION ALL

        SELECT
            'Purchase Invoice' as doctype,
            COUNT(*) as count
        FROM `tabPurchase Invoice`
        WHERE creation > %s

        UNION ALL

        SELECT
            'Payment Entry' as doctype,
            COUNT(*) as count
        FROM `tabPayment Entry`
        WHERE creation > %s
    """,
        (migration.creation, migration.creation, migration.creation, migration.creation),
        as_dict=True,
    )

    print("\n   Documents created:")
    total_created = 0
    for doc in created:
        if doc.count > 0:
            print(f"   - {doc.doctype}: {doc.count}")
            total_created += doc.count

    if total_created == 0:
        print("   - None")

    # Check errors
    print("\n5. Checking errors...")
    errors = frappe.db.sql(
        """
        SELECT error
        FROM `tabError Log`
        WHERE creation > %s
        AND (error LIKE '%%mutation%%' OR error LIKE '%%mapping%%' OR error LIKE '%%account%%')
        LIMIT 10
    """,
        migration.creation,
        as_dict=True,
    )

    if errors:
        print(f"\n   Found {len(errors)} errors:")

        # Analyze error patterns
        error_patterns = {
            "bank_account": 0,
            "receivable_account": 0,
            "payable_account": 0,
            "ledger_mapping": 0,
            "customer": 0,
            "supplier": 0,
            "other": 0,
        }

        for err in errors:
            error_text = str(err.error).lower()
            categorized = False

            if "bank account" in error_text:
                error_patterns["bank_account"] += 1
                categorized = True
            if "receivable account" in error_text:
                error_patterns["receivable_account"] += 1
                categorized = True
            if "payable account" in error_text:
                error_patterns["payable_account"] += 1
                categorized = True
            if "ledger" in error_text and "mapping" in error_text:
                error_patterns["ledger_mapping"] += 1
                categorized = True
            if "customer" in error_text:
                error_patterns["customer"] += 1
                categorized = True
            if "supplier" in error_text:
                error_patterns["supplier"] += 1
                categorized = True
            if not categorized:
                error_patterns["other"] += 1

        print("\n   Error breakdown:")
        for pattern, count in error_patterns.items():
            if count > 0:
                print(f"   - {pattern}: {count}")

        # Show first error as example
        if errors:
            print("\n   Example error:")
            example = str(errors[0].error)
            if len(example) > 500:
                example = example[:500] + "..."
            print(f"   {example}")
    else:
        print("   No errors found")

    # Summary
    print("\n=== SUMMARY ===")
    print(f"Migration: {migration.name}")
    print(f"Status: {migration.migration_status}")
    print(f"Documents created: {total_created}")
    print(f"Errors found: {len(errors) if errors else 0}")

    if len(errors) > 0 and total_created == 0:
        print("\nResult: FAILED - No documents imported due to mapping errors")
        print("\nNext steps:")
        print("1. Add missing ledger mappings")
        print("2. Ensure customers/suppliers exist or can be created")
        print("3. Check account type configurations")
    elif total_created > 0:
        print(f"\nResult: PARTIAL SUCCESS - {total_created} documents imported")
    else:
        print("\nResult: NO DATA - Check if there are mutations to import")

    return {
        "migration": migration.name,
        "status": migration.migration_status,
        "documents_created": total_created,
        "errors": len(errors) if errors else 0,
    }


def cleanup_test_data():
    """Clean up test data from today"""

    today = frappe.utils.today()
    company = "Ned Ver Vegan"

    counts = {}

    # Delete Payment Entries
    # pe_count = frappe.db.sql(
    frappe.db.sql(
        """
        DELETE FROM `tabPayment Entry`
        WHERE company = %s
        AND DATE(creation) = %s
    """,
        (company, today),
    )
    counts["payment_entries"] = frappe.db._cursor.rowcount

    # Delete Journal Entries
    # je_count = frappe.db.sql(
    frappe.db.sql(
        """
        DELETE FROM `tabJournal Entry`
        WHERE company = %s
        AND DATE(creation) = %s
    """,
        (company, today),
    )
    counts["journal_entries"] = frappe.db._cursor.rowcount

    # Delete Sales Invoices
    # si_count = frappe.db.sql(
    frappe.db.sql(
        """
        DELETE FROM `tabSales Invoice`
        WHERE company = %s
        AND DATE(creation) = %s
    """,
        (company, today),
    )
    counts["sales_invoices"] = frappe.db._cursor.rowcount

    # Delete Purchase Invoices
    # pi_count = frappe.db.sql(
    frappe.db.sql(
        """
        DELETE FROM `tabPurchase Invoice`
        WHERE company = %s
        AND DATE(creation) = %s
    """,
        (company, today),
    )
    counts["purchase_invoices"] = frappe.db._cursor.rowcount

    frappe.db.commit()

    counts["total"] = sum(counts.values())
    return counts


if __name__ == "__main__":
    print("Run clean import test")
