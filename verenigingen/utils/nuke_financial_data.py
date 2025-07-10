#!/usr/bin/env python3
"""
Safely remove all financial transaction data for a clean re-import
WARNING: This will delete ALL financial data - use with extreme caution!
"""

import frappe
from frappe.utils import now_datetime


@frappe.whitelist()
def nuke_all_financial_data(confirm="NO"):
    """
    Delete all financial transactions, GL entries, and related data

    Args:
        confirm: Must be "YES_DELETE_ALL_FINANCIAL_DATA" to proceed
    """

    if confirm != "YES_DELETE_ALL_FINANCIAL_DATA":
        return {
            "error": "Safety check failed",
            "message": "To proceed, call with confirm='YES_DELETE_ALL_FINANCIAL_DATA'",
            "warning": "This will permanently delete ALL financial data!",
        }

    company = "Ned Ver Vegan"
    deleted_counts = {}
    errors = []

    print("\n" + "=" * 60)
    print("STARTING FINANCIAL DATA CLEANUP")
    print("=" * 60)
    print(f"Company: {company}")
    print(f"Started at: {now_datetime()}")
    print("=" * 60 + "\n")

    try:
        # Disable foreign key checks temporarily
        frappe.db.sql("SET foreign_key_checks = 0")

        # 1. Delete Payment Ledger Entries
        print("1. Deleting Payment Ledger Entries...")
        ple_count = frappe.db.sql(
            """
            SELECT COUNT(*) FROM `tabPayment Ledger Entry`
            WHERE company = %s
        """,
            company,
        )[0][0]

        if ple_count > 0:
            frappe.db.sql(
                """
                DELETE FROM `tabPayment Ledger Entry`
                WHERE company = %s
            """,
                company,
            )
            deleted_counts["Payment Ledger Entries"] = ple_count
            print(f"   ✓ Deleted {ple_count} Payment Ledger Entries")
        else:
            print("   - No Payment Ledger Entries found")

        # 2. Delete GL Entries
        print("\n2. Deleting General Ledger Entries...")
        gl_count = frappe.db.sql(
            """
            SELECT COUNT(*) FROM `tabGL Entry`
            WHERE company = %s
        """,
            company,
        )[0][0]

        if gl_count > 0:
            frappe.db.sql(
                """
                DELETE FROM `tabGL Entry`
                WHERE company = %s
            """,
                company,
            )
            deleted_counts["GL Entries"] = gl_count
            print(f"   ✓ Deleted {gl_count} GL Entries")
        else:
            print("   - No GL Entries found")

        # 3. Delete Stock Ledger Entries (if any)
        print("\n3. Deleting Stock Ledger Entries...")
        sle_count = frappe.db.sql(
            """
            SELECT COUNT(*) FROM `tabStock Ledger Entry`
            WHERE company = %s
        """,
            company,
        )[0][0]

        if sle_count > 0:
            frappe.db.sql(
                """
                DELETE FROM `tabStock Ledger Entry`
                WHERE company = %s
            """,
                company,
            )
            deleted_counts["Stock Ledger Entries"] = sle_count
            print(f"   ✓ Deleted {sle_count} Stock Ledger Entries")
        else:
            print("   - No Stock Ledger Entries found")

        # 4. Cancel and delete Journal Entries
        print("\n4. Processing Journal Entries...")
        je_list = frappe.db.sql(
            """
            SELECT name, docstatus
            FROM `tabJournal Entry`
            WHERE company = %s
            ORDER BY creation DESC
        """,
            company,
            as_dict=True,
        )

        je_cancelled = 0
        je_deleted = 0

        for je in je_list:
            try:
                doc = frappe.get_doc("Journal Entry", je.name)
                if doc.docstatus == 1:
                    doc.cancel()
                    je_cancelled += 1
                frappe.delete_doc("Journal Entry", je.name, force=True)
                je_deleted += 1
            except Exception as e:
                errors.append(f"Journal Entry {je.name}: {str(e)}")

        deleted_counts["Journal Entries"] = je_deleted
        print(f"   ✓ Cancelled {je_cancelled} and deleted {je_deleted} Journal Entries")

        # 5. Cancel and delete Payment Entries
        print("\n5. Processing Payment Entries...")
        pe_list = frappe.db.sql(
            """
            SELECT name, docstatus
            FROM `tabPayment Entry`
            WHERE company = %s
            ORDER BY creation DESC
        """,
            company,
            as_dict=True,
        )

        pe_cancelled = 0
        pe_deleted = 0

        for pe in pe_list:
            try:
                doc = frappe.get_doc("Payment Entry", pe.name)
                if doc.docstatus == 1:
                    doc.cancel()
                    pe_cancelled += 1
                frappe.delete_doc("Payment Entry", pe.name, force=True)
                pe_deleted += 1
            except Exception as e:
                errors.append(f"Payment Entry {pe.name}: {str(e)}")

        deleted_counts["Payment Entries"] = pe_deleted
        print(f"   ✓ Cancelled {pe_cancelled} and deleted {pe_deleted} Payment Entries")

        # 6. Cancel and delete Sales Invoices
        print("\n6. Processing Sales Invoices...")
        si_list = frappe.db.sql(
            """
            SELECT name, docstatus
            FROM `tabSales Invoice`
            WHERE company = %s
            ORDER BY creation DESC
        """,
            company,
            as_dict=True,
        )

        si_cancelled = 0
        si_deleted = 0

        for si in si_list:
            try:
                doc = frappe.get_doc("Sales Invoice", si.name)
                if doc.docstatus == 1:
                    doc.cancel()
                    si_cancelled += 1
                frappe.delete_doc("Sales Invoice", si.name, force=True)
                si_deleted += 1
            except Exception as e:
                errors.append(f"Sales Invoice {si.name}: {str(e)}")

        deleted_counts["Sales Invoices"] = si_deleted
        print(f"   ✓ Cancelled {si_cancelled} and deleted {si_deleted} Sales Invoices")

        # 7. Cancel and delete Purchase Invoices
        print("\n7. Processing Purchase Invoices...")
        pi_list = frappe.db.sql(
            """
            SELECT name, docstatus
            FROM `tabPurchase Invoice`
            WHERE company = %s
            ORDER BY creation DESC
        """,
            company,
            as_dict=True,
        )

        pi_cancelled = 0
        pi_deleted = 0

        for pi in pi_list:
            try:
                doc = frappe.get_doc("Purchase Invoice", pi.name)
                if doc.docstatus == 1:
                    doc.cancel()
                    pi_cancelled += 1
                frappe.delete_doc("Purchase Invoice", pi.name, force=True)
                pi_deleted += 1
            except Exception as e:
                errors.append(f"Purchase Invoice {pi.name}: {str(e)}")

        deleted_counts["Purchase Invoices"] = pi_deleted
        print(f"   ✓ Cancelled {pi_cancelled} and deleted {pi_deleted} Purchase Invoices")

        # 8. Delete eBoekhouden Import Records
        print("\n8. Deleting eBoekhouden Import Records...")
        try:
            eb_count = frappe.db.sql(
                """
                SELECT COUNT(*) FROM `tabEBoekhouden Import`
            """
            )[0][0]

            if eb_count > 0:
                frappe.db.sql("DELETE FROM `tabEBoekhouden Import`")
                deleted_counts["eBoekhouden Import Records"] = eb_count
                print(f"   ✓ Deleted {eb_count} eBoekhouden Import Records")
            else:
                print("   - No eBoekhouden Import Records found")
        except Exception as e:
            if "doesn't exist" in str(e):
                print("   - Table doesn't exist (skipping)")
            else:
                raise

        # 9. Reset eBoekhouden mutation cache processed flags
        print("\n9. Resetting eBoekhouden Mutation Cache...")
        # cache_count = frappe.db.sql(
        frappe.db.sql(
            """
            UPDATE `tabEBoekhouden REST Mutation Cache`
            SET processed = 0
            WHERE processed = 1
        """
        )
        print(
            f"   ✓ Reset {frappe.db.get_value('EBoekhouden REST Mutation Cache', {'processed': 0}, 'count(*)')} mutation cache entries"
        )

        # Re-enable foreign key checks
        frappe.db.sql("SET foreign_key_checks = 1")

        # Commit all changes
        frappe.db.commit()

        # Clear all caches
        frappe.clear_cache()

        print("\n" + "=" * 60)
        print("CLEANUP COMPLETED SUCCESSFULLY")
        print("=" * 60)
        print("\nSummary of deleted records:")
        for doctype, count in deleted_counts.items():
            print(f"  - {doctype}: {count}")

        if errors:
            print(f"\nEncountered {len(errors)} errors:")
            for error in errors[:10]:  # Show first 10 errors
                print(f"  - {error}")
            if len(errors) > 10:
                print(f"  ... and {len(errors) - 10} more")

        print("\n✓ All financial data has been cleared.")
        print("✓ You can now run a fresh import.")

        return {
            "success": True,
            "deleted": deleted_counts,
            "errors": errors,
            "message": "All financial data has been deleted. Ready for fresh import.",
        }

    except Exception as e:
        # Re-enable foreign key checks in case of error
        frappe.db.sql("SET foreign_key_checks = 1")
        frappe.db.rollback()

        import traceback

        error_details = traceback.format_exc()

        print(f"\n❌ ERROR: {str(e)}")
        print(error_details)

        return {"success": False, "error": str(e), "traceback": error_details}


@frappe.whitelist()
def nuke_gl_entries_older_than(minutes=30):
    """
    Delete GL entries older than specified minutes

    Args:
        minutes: Number of minutes to keep (default 30)
    """

    from frappe.utils import add_to_date, now_datetime

    cutoff_time = add_to_date(now_datetime(), minutes=-int(minutes))

    print(f"\n=== DELETING GL ENTRIES OLDER THAN {minutes} MINUTES ===")
    print(f"Cutoff time: {cutoff_time}")

    try:
        # Check count first
        count = frappe.db.sql(
            """
            SELECT COUNT(*) FROM `tabGL Entry`
            WHERE creation < %s
        """,
            cutoff_time,
        )[0][0]

        if count == 0:
            print("No GL entries older than cutoff time found")
            return {"success": True, "deleted": 0, "message": "No old GL entries to delete"}

        print(f"Found {count} GL entries to delete...")

        # Delete in batches to avoid locks
        batch_size = 1000
        total_deleted = 0

        while count > 0:
            # Disable foreign key checks temporarily
            frappe.db.sql("SET foreign_key_checks = 0")

            # Delete batch
            frappe.db.sql(
                """
                DELETE FROM `tabGL Entry`
                WHERE creation < %s
                LIMIT %s
            """,
                (cutoff_time, batch_size),
            )

            # Re-enable foreign key checks
            frappe.db.sql("SET foreign_key_checks = 1")

            # Check how many records remain
            remaining = frappe.db.sql(
                """
                SELECT COUNT(*) FROM `tabGL Entry`
                WHERE creation < %s
            """,
                cutoff_time,
            )[0][0]

            deleted_this_batch = count - remaining
            if deleted_this_batch == 0:
                break

            total_deleted += deleted_this_batch
            count = remaining

            print(f"Deleted {deleted_this_batch} GL entries (remaining: {remaining})")

            # Small pause to avoid overwhelming the database
            import time

            time.sleep(0.1)

        frappe.db.commit()

        print(f"\n✓ Successfully deleted {total_deleted} GL entries older than {minutes} minutes")

        return {
            "success": True,
            "deleted": total_deleted,
            "cutoff_time": str(cutoff_time),
            "message": "Deleted {total_deleted} GL entries older than {minutes} minutes",
        }

    except Exception as e:
        frappe.db.rollback()
        print(f"\n❌ Error deleting GL entries: {str(e)}")
        return {"success": False, "error": str(e), "deleted": 0}


@frappe.whitelist()
def check_financial_data_status():
    """Check current status of financial data before deletion"""

    company = "Ned Ver Vegan"

    counts = {}

    # Check each table with error handling
    tables_to_check = [
        ("GL Entries", "GL Entry", {"company": company}),
        ("Payment Ledger Entries", "Payment Ledger Entry", {"company": company}),
        ("Journal Entries", "Journal Entry", {"company": company}),
        ("Payment Entries", "Payment Entry", {"company": company}),
        ("Sales Invoices", "Sales Invoice", {"company": company}),
        ("Purchase Invoices", "Purchase Invoice", {"company": company}),
        ("Stock Ledger Entries", "Stock Ledger Entry", {"company": company}),
        ("eBoekhouden Imports", "EBoekhouden Import", {}),
        ("eBoekhouden Cache (Total)", "EBoekhouden REST Mutation Cache", {}),
        ("eBoekhouden Cache (Processed)", "EBoekhouden REST Mutation Cache", {"processed": 1}),
    ]

    for label, doctype, filters in tables_to_check:
        try:
            counts[label] = frappe.db.count(doctype, filters)
        except Exception as e:
            if "doesn't exist" in str(e):
                counts[label] = 0
            else:
                counts[label] = f"Error: {str(e)}"

    print("\n=== CURRENT FINANCIAL DATA STATUS ===")
    print(f"Company: {company}\n")

    total_records = 0
    for doctype, count in counts.items():
        print(f"{doctype}: {count:,}")
        if doctype not in ["eBoekhouden Cache (Total)", "eBoekhouden Cache (Processed)"]:
            total_records += count

    print(f"\nTotal financial records to be deleted: {total_records:,}")
    print("\n⚠️  WARNING: Running nuke_all_financial_data will delete ALL of the above data!")

    return counts


if __name__ == "__main__":
    print("Financial data cleanup utility")
