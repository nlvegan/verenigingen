#!/usr/bin/env python3
"""
Fast cleanup of financial data using direct SQL
"""

import frappe
from frappe.utils import now_datetime


@frappe.whitelist()
def nuke_financial_data_fast(confirm="NO"):
    """
    Fast deletion of all financial data using direct SQL

    Args:
        confirm: Must be "YES_DELETE_ALL" to proceed
    """

    if confirm != "YES_DELETE_ALL":
        return {"error": "Safety check failed", "message": "To proceed, call with confirm='YES_DELETE_ALL'"}

    company = "Ned Ver Vegan"
    print(f"\n{'=' * 60}")
    print("FAST FINANCIAL DATA CLEANUP")
    print(f"{'=' * 60}")
    print(f"Started at: {now_datetime()}\n")

    try:
        # Disable foreign key checks
        frappe.db.sql("SET foreign_key_checks = 0")

        # 1. Direct delete GL entries
        print("1. Deleting GL Entries...")
        gl_count = frappe.db.sql("SELECT COUNT(*) FROM `tabGL Entry` WHERE company = %s", company)[0][0]
        frappe.db.sql("DELETE FROM `tabGL Entry` WHERE company = %s", company)
        print(f"   ✓ Deleted {gl_count} GL Entries")

        # 2. Direct delete Payment Ledger entries
        print("\n2. Deleting Payment Ledger Entries...")
        ple_count = frappe.db.sql(
            "SELECT COUNT(*) FROM `tabPayment Ledger Entry` WHERE company = %s", company
        )[0][0]
        frappe.db.sql("DELETE FROM `tabPayment Ledger Entry` WHERE company = %s", company)
        print(f"   ✓ Deleted {ple_count} Payment Ledger Entries")

        # 3. Direct delete Stock Ledger entries
        print("\n3. Deleting Stock Ledger Entries...")
        sle_count = frappe.db.sql("SELECT COUNT(*) FROM `tabStock Ledger Entry` WHERE company = %s", company)[
            0
        ][0]
        frappe.db.sql("DELETE FROM `tabStock Ledger Entry` WHERE company = %s", company)
        print(f"   ✓ Deleted {sle_count} Stock Ledger Entries")

        # 4. Cancel submitted documents before deletion
        print("\n4. Cancelling submitted documents...")

        # Cancel in reverse order of dependencies
        for doctype in ["Payment Entry", "Sales Invoice", "Purchase Invoice", "Journal Entry"]:
            print(f"\n   Processing {doctype}...")

            # Get submitted docs
            submitted = frappe.db.sql(
                f"""
                SELECT name FROM `tab{doctype}`
                WHERE company = %s AND docstatus = 1
                LIMIT 100
            """,
                company,
            )

            cancelled = 0
            while submitted:
                for (name,) in submitted:
                    try:
                        frappe.db.sql(f"UPDATE `tab{doctype}` SET docstatus = 2 WHERE name = %s", name)
                        cancelled += 1
                    except:
                        pass

                # Get next batch
                submitted = frappe.db.sql(
                    f"""
                    SELECT name FROM `tab{doctype}`
                    WHERE company = %s AND docstatus = 1
                    LIMIT 100
                """,
                    company,
                )

            print(f"      Cancelled {cancelled} {doctype}s")

            # Now delete all
            total = frappe.db.sql(f"SELECT COUNT(*) FROM `tab{doctype}` WHERE company = %s", company)[0][0]
            frappe.db.sql(f"DELETE FROM `tab{doctype}` WHERE company = %s", company)
            print(f"      Deleted {total} {doctype}s")

        # 5. Reset cache tables if they exist
        print("\n5. Resetting cache tables...")
        try:
            frappe.db.sql("UPDATE `tabEBoekhouden REST Mutation Cache` SET processed = 0 WHERE processed = 1")
            print("   ✓ Reset mutation cache")
        except:
            print("   - Mutation cache table not found")

        # Re-enable foreign key checks
        frappe.db.sql("SET foreign_key_checks = 1")

        # Commit changes
        frappe.db.commit()
        frappe.clear_cache()

        print(f"\n{'=' * 60}")
        print("✓ CLEANUP COMPLETED SUCCESSFULLY")
        print(f"{'=' * 60}")
        print("\nAll financial data has been deleted.")
        print("You can now run a fresh import.")

        return {"success": True, "message": "All financial data deleted"}

    except Exception as e:
        frappe.db.sql("SET foreign_key_checks = 1")
        frappe.db.rollback()

        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


if __name__ == "__main__":
    print("Fast financial data cleanup")
