"""
E-Boekhouden Cleanup Utilities

Conservative refactor: These functions were moved from the main migration file
to improve organization. All original logic is preserved exactly as-is.
"""

import json

import frappe

from verenigingen.e_boekhouden.utils.security_helper import migration_context


@frappe.whitelist()
def cleanup_chart_of_accounts(company, delete_all_accounts=0):
    """Clean up chart of accounts imported from E-Boekhouden"""
    try:
        # Check permissions upfront
        if not frappe.has_permission("Account", "delete"):
            frappe.throw("Insufficient permissions to delete accounts")

        # Use migration context for cleanup operations
        with migration_context("account_creation"):
            delete_all = int(delete_all_accounts)

            cleanup_results = {"accounts_deleted": 0, "accounts_skipped": 0, "errors": []}

            if delete_all:
                # Get all accounts for the company
                accounts = frappe.get_all(
                    "Account",
                    filters={"company": company},
                    fields=["name", "account_name", "is_group", "lft", "rgt"],
                    order_by="lft desc",  # Delete leaf accounts first
                )
            else:
                # Only get accounts that were imported from E-Boekhouden
                accounts = frappe.get_all(
                    "Account",
                    filters={"company": company, "eboekhouden_grootboek_nummer": ["!=", ""]},
                    fields=["name", "account_name", "is_group", "lft", "rgt"],
                    order_by="lft desc",  # Delete leaf accounts first
                )

            frappe.logger().info(f"Found {len(accounts)} accounts to clean up")

            for account in accounts:
                try:
                    # Check if account has any transactions
                    has_gl_entries = frappe.db.exists("GL Entry", {"account": account.name})

                    if has_gl_entries:
                        cleanup_results["accounts_skipped"] += 1
                        cleanup_results["errors"].append(
                            f"Account {account.account_name} has GL entries, skipped"
                        )
                        continue

                    # Check if it's a system account (Asset, Liability, Income, Expense root accounts)
                    if account.account_name in ["Asset", "Liability", "Income", "Expense", "Equity"]:
                        cleanup_results["accounts_skipped"] += 1
                        cleanup_results["errors"].append(f"System account {account.account_name} skipped")
                        continue

                    # Try to delete the account with proper permissions
                    # Note: frappe.delete_doc requires ignore_permissions for system cleanup
                    # This is a special case where we need to keep it
                    frappe.delete_doc("Account", account.name, ignore_permissions=True)
                    cleanup_results["accounts_deleted"] += 1
                    frappe.logger().info(f"Deleted account: {account.account_name}")

                except Exception as e:
                    cleanup_results["accounts_skipped"] += 1
                    cleanup_results["errors"].append(f"Failed to delete {account.account_name}: {str(e)}")
                    frappe.logger().error(f"Failed to delete account {account.account_name}: {str(e)}")

            frappe.db.commit()

            return {
                "success": True,
                "message": f"Cleanup completed. Deleted: {cleanup_results['accounts_deleted']}, Skipped: {cleanup_results['accounts_skipped']}",
                "results": cleanup_results,
            }

    except Exception as e:
        frappe.db.rollback()
        frappe.logger().error(f"Chart of accounts cleanup failed: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_cleanup_small_batch():
    """Test cleanup on a small batch of documents to verify fix"""
    try:
        if not frappe.has_permission("System Manager"):
            frappe.throw("Only System Managers can perform cleanup testing")

        results = {"sales_invoices": 0, "errors": [], "test_completed": True}

        # Test with just a few Sales Invoices
        records = frappe.get_all(
            "Sales Invoice",
            filters={"eboekhouden_invoice_number": ["!=", ""]},
            fields=["name", "docstatus"],
            limit=3,
        )

        frappe.logger().info(f"Testing cleanup with {len(records)} Sales Invoice records")

        for record in records:
            try:
                doc = frappe.get_doc("Sales Invoice", record.name)

                if doc.docstatus == 1:
                    frappe.logger().info(f"Cancelling submitted Sales Invoice {record.name}")
                    doc.cancel()

                frappe.delete_doc("Sales Invoice", record.name, force=True, ignore_permissions=True)
                results["sales_invoices"] += 1
                frappe.logger().info(f"Successfully deleted Sales Invoice {record.name}")

            except Exception as e:
                error_msg = f"Failed to delete Sales Invoice {record.name}: {str(e)}"
                results["errors"].append(error_msg)
                frappe.logger().error(error_msg)

        frappe.db.commit()
        return {
            "success": True,
            "message": f"Test completed: {results['sales_invoices']} invoices deleted",
            "results": results,
        }

    except Exception as e:
        frappe.db.rollback()
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def nuclear_cleanup_all_imported_data():
    """WARNING: Nuclear option - deletes ALL imported data from E-Boekhouden"""
    try:
        if not frappe.has_permission("System Manager"):
            frappe.throw("Only System Managers can perform nuclear cleanup")

        frappe.msgprint(
            "⚠️ WARNING: This will delete ALL imported data from E-Boekhouden. This cannot be undone!",
            title="Nuclear Cleanup Warning",
            indicator="red",
        )

        results = {
            "sales_invoices": 0,
            "purchase_invoices": 0,
            "payment_entries": 0,
            "journal_entries": 0,
            "customers": 0,
            "suppliers": 0,
            "accounts": 0,
            "orphaned_gl_entries": 0,
            "errors": [],
        }

        # Delete E-Boekhouden imported documents
        doctypes_to_clean = [
            ("Sales Invoice", "eboekhouden_invoice_number"),
            ("Purchase Invoice", "eboekhouden_invoice_number"),
            ("Payment Entry", "eboekhouden_mutation_nr"),
            ("Journal Entry", "eboekhouden_mutation_nr"),
        ]

        for doctype, field in doctypes_to_clean:
            try:
                # Get records with docstatus information
                records = frappe.get_all(doctype, filters={field: ["!=", ""]}, fields=["name", "docstatus"])
                total_records = len(records)
                frappe.logger().info(f"Found {total_records} {doctype} records to clean")

                # Process in batches for better performance and progress tracking
                batch_size = 50
                for i in range(0, total_records, batch_size):
                    batch = records[i : i + batch_size]
                    frappe.logger().info(
                        f"Processing {doctype} batch {i //batch_size + 1}/{(total_records + batch_size - 1) //batch_size}"
                    )

                    for record in batch:
                        try:
                            # Load the document to check its state
                            doc = frappe.get_doc(doctype, record.name)

                            # Cancel the document if it's submitted (docstatus = 1)
                            if doc.docstatus == 1:
                                doc.cancel()

                            # Now delete the document (whether it was draft, cancelled, or just cancelled above)
                            frappe.delete_doc(doctype, record.name, force=True, ignore_permissions=True)
                            results[doctype.lower().replace(" ", "_") + "s"] += 1

                        except Exception as e:
                            error_msg = f"Failed to delete {doctype} {record.name}: {str(e)}"
                            results["errors"].append(error_msg)
                            frappe.logger().error(error_msg)

                    # Commit after each batch to prevent timeout issues
                    if i % (batch_size * 4) == 0:  # Commit every 200 records
                        frappe.db.commit()

            except Exception as e:
                error_msg = f"Failed to clean {doctype}: {str(e)}"
                results["errors"].append(error_msg)
                frappe.logger().error(error_msg)

        # Delete provisional parties
        provisional_customers = frappe.get_all(
            "Customer", filters={"customer_name": ["like", "Provisional Customer%"]}, fields=["name"]
        )
        for customer in provisional_customers:
            try:
                frappe.delete_doc("Customer", customer.name, ignore_permissions=True)
                results["customers"] += 1
            except Exception as e:
                results["errors"].append(f"Failed to delete customer {customer.name}: {str(e)}")

        provisional_suppliers = frappe.get_all(
            "Supplier", filters={"supplier_name": ["like", "Provisional Supplier%"]}, fields=["name"]
        )
        for supplier in provisional_suppliers:
            try:
                frappe.delete_doc("Supplier", supplier.name, ignore_permissions=True)
                results["suppliers"] += 1
            except Exception as e:
                results["errors"].append(f"Failed to delete supplier {supplier.name}: {str(e)}")

        # Clean up orphaned GL Entries
        frappe.logger().info("Cleaning up orphaned GL Entries...")
        gl_cleanup_results = cleanup_orphaned_gl_entries()
        if gl_cleanup_results["success"]:
            results["orphaned_gl_entries"] = gl_cleanup_results["deleted_entries"]
            frappe.logger().info(f"Cleaned up {gl_cleanup_results['deleted_entries']} orphaned GL Entries")
        else:
            results["errors"].append(f"GL Entry cleanup failed: {gl_cleanup_results['error']}")

        frappe.db.commit()

        return {"success": True, "message": "Nuclear cleanup completed", "results": results}

    except Exception as e:
        frappe.db.rollback()
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def cleanup_orphaned_gl_entries():
    """Clean up GL entries, Payment Entry References, and Payment Ledger Entries that reference deleted documents"""
    try:
        results = {
            "success": True,
            "deleted_gl_entries": 0,
            "deleted_payment_references": 0,
            "deleted_payment_ledger_entries": 0,
            "errors": [],
        }

        # Find GL Entries that reference non-existent vouchers
        orphaned_gl_sql = """
            SELECT
                ge.name,
                ge.voucher_type,
                ge.voucher_no
            FROM `tabGL Entry` ge
            LEFT JOIN `tabSales Invoice` si ON ge.voucher_type = 'Sales Invoice' AND ge.voucher_no = si.name
            LEFT JOIN `tabPurchase Invoice` pi ON ge.voucher_type = 'Purchase Invoice' AND ge.voucher_no = pi.name
            LEFT JOIN `tabPayment Entry` pe ON ge.voucher_type = 'Payment Entry' AND ge.voucher_no = pe.name
            LEFT JOIN `tabJournal Entry` je ON ge.voucher_type = 'Journal Entry' AND ge.voucher_no = je.name
            WHERE (
                (ge.voucher_type = 'Sales Invoice' AND si.name IS NULL) OR
                (ge.voucher_type = 'Purchase Invoice' AND pi.name IS NULL) OR
                (ge.voucher_type = 'Payment Entry' AND pe.name IS NULL) OR
                (ge.voucher_type = 'Journal Entry' AND je.name IS NULL)
            )
            AND ge.voucher_type IN ('Sales Invoice', 'Purchase Invoice', 'Payment Entry', 'Journal Entry')
            ORDER BY ge.voucher_type, ge.voucher_no
        """

        orphaned_entries = frappe.db.sql(orphaned_gl_sql, as_dict=True)

        frappe.logger().info(f"Found {len(orphaned_entries)} orphaned GL Entries")

        for entry in orphaned_entries:
            try:
                frappe.delete_doc("GL Entry", entry.name, ignore_permissions=True)
                results["deleted_gl_entries"] += 1
                frappe.logger().info(
                    f"Deleted orphaned GL Entry {entry.name} (voucher: {entry.voucher_type} {entry.voucher_no})"
                )
            except Exception as e:
                error_msg = f"Failed to delete GL Entry {entry.name}: {str(e)}"
                results["errors"].append(error_msg)
                frappe.logger().error(error_msg)

        # Clean up orphaned Payment Entry References
        frappe.logger().info("Cleaning up orphaned Payment Entry References...")

        orphaned_per_sql = """
            SELECT
                per.name,
                per.parent as payment_entry,
                per.reference_doctype,
                per.reference_name
            FROM `tabPayment Entry Reference` per
            LEFT JOIN `tabSales Invoice` si ON per.reference_doctype = 'Sales Invoice' AND per.reference_name = si.name
            LEFT JOIN `tabPurchase Invoice` pi ON per.reference_doctype = 'Purchase Invoice' AND per.reference_name = pi.name
            WHERE (
                (per.reference_doctype = 'Sales Invoice' AND si.name IS NULL) OR
                (per.reference_doctype = 'Purchase Invoice' AND pi.name IS NULL)
            )
            ORDER BY per.parent
        """

        orphaned_per_entries = frappe.db.sql(orphaned_per_sql, as_dict=True)

        frappe.logger().info(f"Found {len(orphaned_per_entries)} orphaned Payment Entry References")

        # Process in batches to avoid timeout
        batch_size = 100
        for i in range(0, len(orphaned_per_entries), batch_size):
            batch = orphaned_per_entries[i : i + batch_size]
            frappe.logger().info(
                f"Processing Payment Entry Reference batch {i // batch_size + 1}/{(len(orphaned_per_entries) + batch_size - 1) // batch_size}"
            )

            for per_entry in batch:
                try:
                    frappe.delete_doc("Payment Entry Reference", per_entry.name, ignore_permissions=True)
                    results["deleted_payment_references"] += 1
                    if results["deleted_payment_references"] % 100 == 0:  # Log every 100 deletions
                        frappe.logger().info(
                            f"Deleted {results['deleted_payment_references']} Payment Entry References so far..."
                        )
                except Exception as e:
                    error_msg = f"Failed to delete Payment Entry Reference {per_entry.name}: {str(e)}"
                    results["errors"].append(error_msg)
                    frappe.logger().error(error_msg)

            # Commit after each batch to prevent timeout
            frappe.db.commit()

        # Clean up orphaned Payment Ledger Entries
        frappe.logger().info("Cleaning up orphaned Payment Ledger Entries...")

        orphaned_ple_sql = """
            SELECT
                ple.name,
                ple.voucher_type,
                ple.voucher_no
            FROM `tabPayment Ledger Entry` ple
            LEFT JOIN `tabSales Invoice` si ON ple.voucher_type = 'Sales Invoice' AND ple.voucher_no = si.name
            LEFT JOIN `tabPurchase Invoice` pi ON ple.voucher_type = 'Purchase Invoice' AND ple.voucher_no = pi.name
            LEFT JOIN `tabPayment Entry` pe ON ple.voucher_type = 'Payment Entry' AND ple.voucher_no = pe.name
            LEFT JOIN `tabJournal Entry` je ON ple.voucher_type = 'Journal Entry' AND ple.voucher_no = je.name
            WHERE (
                (ple.voucher_type = 'Sales Invoice' AND si.name IS NULL) OR
                (ple.voucher_type = 'Purchase Invoice' AND pi.name IS NULL) OR
                (ple.voucher_type = 'Payment Entry' AND pe.name IS NULL) OR
                (ple.voucher_type = 'Journal Entry' AND je.name IS NULL)
            )
            AND ple.voucher_type IN ('Sales Invoice', 'Purchase Invoice', 'Payment Entry', 'Journal Entry')
            ORDER BY ple.voucher_type, ple.voucher_no
        """

        orphaned_ple_entries = frappe.db.sql(orphaned_ple_sql, as_dict=True)

        frappe.logger().info(f"Found {len(orphaned_ple_entries)} orphaned Payment Ledger Entries")

        # Process in batches to avoid timeout
        batch_size = 100
        for i in range(0, len(orphaned_ple_entries), batch_size):
            batch = orphaned_ple_entries[i : i + batch_size]
            frappe.logger().info(
                f"Processing Payment Ledger Entry batch {i // batch_size + 1}/{(len(orphaned_ple_entries) + batch_size - 1) // batch_size}"
            )

            for ple_entry in batch:
                try:
                    frappe.delete_doc("Payment Ledger Entry", ple_entry.name, ignore_permissions=True)
                    results["deleted_payment_ledger_entries"] += 1
                    if results["deleted_payment_ledger_entries"] % 100 == 0:  # Log every 100 deletions
                        frappe.logger().info(
                            f"Deleted {results['deleted_payment_ledger_entries']} Payment Ledger Entries so far..."
                        )
                except Exception as e:
                    error_msg = f"Failed to delete Payment Ledger Entry {ple_entry.name}: {str(e)}"
                    results["errors"].append(error_msg)
                    frappe.logger().error(error_msg)

            # Commit after each batch to prevent timeout
            frappe.db.commit()

        frappe.logger().info(
            f"Completed cleanup: {results['deleted_gl_entries']} GL Entries, {results['deleted_payment_references']} Payment Entry References, {results['deleted_payment_ledger_entries']} Payment Ledger Entries"
        )

        # Update results for backward compatibility
        results["deleted_entries"] = (
            results["deleted_gl_entries"]
            + results["deleted_payment_references"]
            + results["deleted_payment_ledger_entries"]
        )

        return results

    except Exception as e:
        frappe.logger().error(f"Orphaned cleanup failed: {str(e)}")
        return {"success": False, "error": str(e), "deleted_entries": 0}


@frappe.whitelist()
def cleanup_cancelled_payment_gl_entries():
    """Clean up GL entries from cancelled payment entries"""
    try:
        # Find GL entries for cancelled payment entries
        cancelled_gl = frappe.db.sql(
            """
            SELECT ge.name
            FROM `tabGL Entry` ge
            JOIN `tabPayment Entry` pe ON pe.name = ge.voucher_no
            WHERE ge.voucher_type = 'Payment Entry'
            AND pe.docstatus = 2
        """,
            as_dict=True,
        )

        deleted_count = 0
        for entry in cancelled_gl:
            try:
                frappe.delete_doc("GL Entry", entry.name, ignore_permissions=True)
                deleted_count += 1
            except Exception as e:
                frappe.logger().error(f"Failed to delete GL entry {entry.name}: {str(e)}")

        frappe.db.commit()

        return {"success": True, "message": f"Cleaned up {deleted_count} GL entries from cancelled payments"}

    except Exception as e:
        frappe.db.rollback()
        return {"success": False, "error": str(e)}


# Additional helper functions for comprehensive cleanup
def get_cleanup_dependencies(company):
    """Get dependencies that need to be cleaned before accounts"""
    dependencies = {
        "gl_entries": frappe.db.count("GL Entry", {"company": company}),
        "invoices": frappe.db.count("Sales Invoice", {"company": company, "docstatus": 1}),
        "purchases": frappe.db.count("Purchase Invoice", {"company": company, "docstatus": 1}),
        "payments": frappe.db.count("Payment Entry", {"company": company, "docstatus": 1}),
        "journals": frappe.db.count("Journal Entry", {"company": company, "docstatus": 1}),
    }

    return dependencies


def cleanup_payment_entries(pe_list, method_name):
    """Helper function to cleanup payment entries"""
    results = {"deleted": 0, "errors": []}

    for pe_name in pe_list:
        try:
            pe_doc = frappe.get_doc("Payment Entry", pe_name)
            if pe_doc.docstatus == 1:
                pe_doc.cancel()
            pe_doc.delete(ignore_permissions=True)
            results["deleted"] += 1
        except Exception as e:
            results["errors"].append(f"Failed to delete PE {pe_name}: {str(e)}")

    return results


def cleanup_sales_invoices(si_list, method_name):
    """Helper function to cleanup sales invoices"""
    results = {"deleted": 0, "errors": []}

    for si_name in si_list:
        try:
            si_doc = frappe.get_doc("Sales Invoice", si_name)
            if si_doc.docstatus == 1:
                si_doc.cancel()
            si_doc.delete(ignore_permissions=True)
            results["deleted"] += 1
        except Exception as e:
            results["errors"].append(f"Failed to delete SI {si_name}: {str(e)}")

    return results


def cleanup_purchase_invoices(pi_list, method_name):
    """Helper function to cleanup purchase invoices"""
    results = {"deleted": 0, "errors": []}

    for pi_name in pi_list:
        try:
            pi_doc = frappe.get_doc("Purchase Invoice", pi_name)
            if pi_doc.docstatus == 1:
                pi_doc.cancel()
            pi_doc.delete(ignore_permissions=True)
            results["deleted"] += 1
        except Exception as e:
            results["errors"].append(f"Failed to delete PI {pi_name}: {str(e)}")

    return results
