#!/usr/bin/env python3
"""
Test import of non-opening-balance mutations
"""

import frappe
from frappe.utils import now_datetime


@frappe.whitelist()
def test_non_opening_mutations():
    """Test import excluding opening balance mutations"""

    print("Testing import of non-opening-balance mutations...")

    try:
        # Create a test migration
        migration = frappe.new_doc("E-Boekhouden Migration")
        migration.migration_name = "Test Non-Opening - {now_datetime()}"
        migration.migration_type = "Recent Transactions"
        migration.status = "In Progress"
        migration.import_method = "REST API"
        migration.mutation_limit = 50  # Small batch
        migration.save()

        print(f"Created migration: {migration.name}")

        # Import directly with specific types (exclude type 0)
        from verenigingen.utils.eboekhouden_rest_full_migration import (
            _get_cost_center,
            _get_default_company,
            _import_batch_rest,
        )

        company = _get_default_company()
        cost_center = _get_cost_center(company)

        # Fetch recent mutations excluding type 0
        from verenigingen.api.e_boekhouden import get_eboekhouden_client

        client = get_eboekhouden_client()

        # Get mutations of specific types
        mutations = []
        for mutation_type in [1, 2, 3, 4, 5, 6, 7]:  # Exclude type 0
            try:
                type_mutations = client.get_mutaties(
                    mutatie_soort=mutation_type, aantal=10  # 10 of each type
                )
                if type_mutations:
                    mutations.extend(type_mutations)
                    print(f"Found {len(type_mutations)} mutations of type {mutation_type}")
            except Exception as e:
                print(f"Error fetching type {mutation_type}: {str(e)}")

        print(f"\nTotal mutations to process: {len(mutations)}")

        if not mutations:
            print("No mutations found!")
            return {"success": False, "error": "No mutations found"}

        # Process the mutations
        debug_info = []
        result = _import_batch_rest(
            mutations=mutations[:20],  # Process max 20
            company=company,
            cost_center=cost_center,
            migration_name=migration.name,
            debug_info=debug_info,
        )

        print("\nImport result:")
        print(f"  Imported: {result.get('imported', 0)}")
        print(f"  Failed: {result.get('failed', 0)}")

        # Show debug info
        if debug_info:
            print("\nDebug info (first 20 lines):")
            for line in debug_info[:20]:
                if "ERROR" in line or "Failed" in line:
                    print(f"  ERROR: {line}")
                else:
                    print(f"  {line}")

        # Check for specific errors
        errors = [line for line in debug_info if "ERROR" in line or "Failed" in line]
        if errors:
            print(f"\nTotal errors: {len(errors)}")

            # Categorize errors
            error_types = {}
            for error in errors:
                if "bank account" in error.lower():
                    error_types["bank_account"] = error_types.get("bank_account", 0) + 1
                elif "receivable account" in error.lower():
                    error_types["receivable_account"] = error_types.get("receivable_account", 0) + 1
                elif "payable account" in error.lower():
                    error_types["payable_account"] = error_types.get("payable_account", 0) + 1
                elif "customer" in error.lower():
                    error_types["customer"] = error_types.get("customer", 0) + 1
                elif "supplier" in error.lower():
                    error_types["supplier"] = error_types.get("supplier", 0) + 1
                elif "ledger" in error.lower():
                    error_types["ledger"] = error_types.get("ledger", 0) + 1
                else:
                    error_types["other"] = error_types.get("other", 0) + 1

            print("\nError breakdown:")
            for error_type, count in error_types.items():
                print(f"  {error_type}: {count}")

        return {
            "success": True,
            "migration": migration.name,
            "total_mutations": len(mutations),
            "processed": min(20, len(mutations)),
            "imported": result.get("imported", 0),
            "failed": result.get("failed", 0),
            "errors": len(errors),
        }

    except Exception as e:
        import traceback

        print(f"\nERROR: {str(e)}")
        print(traceback.format_exc())
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


if __name__ == "__main__":
    print("Test non-opening mutations")
