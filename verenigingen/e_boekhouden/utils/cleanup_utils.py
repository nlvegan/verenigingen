"""
E-Boekhouden Cleanup Utilities

Conservative refactor: These functions were moved from the main migration file
to improve organization. All original logic is preserved exactly as-is.
"""

import json

import frappe

from verenigingen.e_boekhouden.utils.security_helper import migration_context
from verenigingen.utils.security.api_security_framework import OperationType, critical_api, high_security_api
from verenigingen.utils.security_decorators import development_only


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
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
@high_security_api(operation_type=OperationType.FINANCIAL)
@development_only()
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
@critical_api(operation_type=OperationType.FINANCIAL)
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
            "bank_transactions": 0,
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
                            # For Payment Entries, check and delete linked Bank Transactions first
                            if doctype == "Payment Entry":
                                bt_cleanup = _cleanup_linked_bank_transactions(record.name)
                                results["bank_transactions"] += bt_cleanup["deleted"]
                                results["errors"].extend(bt_cleanup["errors"])

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

        # Clean up orphaned Bank Transactions (those with EB- reference prefix)
        frappe.logger().info("Cleaning up orphaned Bank Transactions...")
        orphaned_bt_cleanup = _cleanup_orphaned_bank_transactions()
        results["bank_transactions"] += orphaned_bt_cleanup["deleted"]
        results["errors"].extend(orphaned_bt_cleanup["errors"])

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
@critical_api(operation_type=OperationType.FINANCIAL)
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
@critical_api(operation_type=OperationType.FINANCIAL)
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


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def delete_all_payment_entries():
    """Delete all payment entries from the system, including linked Bank Transactions"""
    try:
        # Check for Verenigingen Administrator role
        user_roles = frappe.get_roles()
        if "Verenigingen Administrator" not in user_roles and frappe.session.user != "Administrator":
            frappe.throw("Only Verenigingen Administrators can delete all payment entries")

        # Count payment entries before deletion
        count_before = frappe.db.count("Payment Entry")

        frappe.logger().info(f"Starting deletion of {count_before} payment entries")

        results = {
            "success": True,
            "count_before": count_before,
            "deleted": 0,
            "bank_transactions_deleted": 0,
            "errors": [],
        }

        # Get all payment entries
        payment_entries = frappe.get_all(
            "Payment Entry", fields=["name", "docstatus"], limit=10000  # Safety limit
        )

        # Process in batches
        batch_size = 100
        for i in range(0, len(payment_entries), batch_size):
            batch = payment_entries[i : i + batch_size]
            frappe.logger().info(
                f"Processing batch {i // batch_size + 1}/{(len(payment_entries) + batch_size - 1) // batch_size}"
            )

            for pe in batch:
                try:
                    # First, cleanup any linked Bank Transactions
                    bt_cleanup = _cleanup_linked_bank_transactions(pe.name)
                    results["bank_transactions_deleted"] += bt_cleanup["deleted"]
                    results["errors"].extend(bt_cleanup["errors"])

                    # Load the document
                    pe_doc = frappe.get_doc("Payment Entry", pe.name)

                    # Cancel if submitted
                    if pe_doc.docstatus == 1:
                        pe_doc.cancel()

                    # Delete the document
                    frappe.delete_doc("Payment Entry", pe.name, force=True, ignore_permissions=True)
                    results["deleted"] += 1

                except Exception as e:
                    error_msg = f"Failed to delete Payment Entry {pe.name}: {str(e)}"
                    results["errors"].append(error_msg)
                    frappe.logger().error(error_msg)

            # Commit after each batch
            if i % (batch_size * 4) == 0:  # Commit every 400 records
                frappe.db.commit()

        # Final commit
        frappe.db.commit()

        # Count remaining payment entries
        count_after = frappe.db.count("Payment Entry")
        results["count_after"] = count_after

        message = f"Deleted {results['deleted']} payment entries and {results['bank_transactions_deleted']} bank transactions"
        if results["errors"]:
            message += f" ({len(results['errors'])} errors)"

        frappe.logger().info(message)

        return {"success": True, "message": message, "results": results}

    except Exception as e:
        frappe.db.rollback()
        frappe.logger().error(f"Failed to delete payment entries: {str(e)}")
        return {"success": False, "error": str(e)}


def _cleanup_linked_bank_transactions(payment_entry_name):
    """
    Clean up Bank Transactions linked to a specific Payment Entry.

    Args:
        payment_entry_name: Name of the Payment Entry

    Returns:
        dict: Results with deleted count and errors
    """
    results = {"deleted": 0, "errors": []}

    try:
        # Find all Bank Transactions linked to this Payment Entry
        linked_bt_refs = frappe.get_all(
            "Bank Transaction Payments",
            filters={"payment_entry": payment_entry_name},
            fields=["parent"],
        )

        for bt_ref in linked_bt_refs:
            try:
                bt_doc = frappe.get_doc("Bank Transaction", bt_ref.parent)

                # Cancel if submitted
                if bt_doc.docstatus == 1:
                    bt_doc.cancel()

                # Delete the Bank Transaction
                frappe.delete_doc("Bank Transaction", bt_ref.parent, force=True)
                results["deleted"] += 1
                frappe.logger().info(
                    f"Deleted linked Bank Transaction {bt_ref.parent} for Payment Entry {payment_entry_name}"
                )

            except Exception as bt_error:
                error_msg = f"Failed to delete Bank Transaction {bt_ref.parent}: {str(bt_error)}"
                results["errors"].append(error_msg)
                frappe.logger().error(error_msg)

    except Exception as e:
        error_msg = f"Failed to cleanup Bank Transactions for Payment Entry {payment_entry_name}: {str(e)}"
        results["errors"].append(error_msg)
        frappe.logger().error(error_msg)

    return results


def _cleanup_orphaned_bank_transactions():
    """
    Clean up orphaned Bank Transactions from E-Boekhouden import.

    Identifies and deletes Bank Transactions with EB- reference prefix that are either:
    - Not linked to any Payment Entry
    - Linked to Payment Entries that no longer exist

    Returns:
        dict: Results with deleted count and errors
    """
    results = {"deleted": 0, "errors": []}

    try:
        # Find Bank Transactions with EB- reference prefix (E-Boekhouden imports)
        bank_transactions = frappe.get_all(
            "Bank Transaction",
            filters={"reference_number": ["like", "EB-%"]},
            fields=["name", "reference_number", "docstatus"],
        )

        frappe.logger().info(f"Found {len(bank_transactions)} Bank Transactions with EB- reference")

        for bt in bank_transactions:
            try:
                # Check if it has any linked payments
                linked_payments = frappe.get_all(
                    "Bank Transaction Payments",
                    filters={"parent": bt.name},
                    fields=["payment_entry"],
                )

                is_orphaned = False

                if not linked_payments:
                    # No linked payments at all - orphaned
                    is_orphaned = True
                    frappe.logger().info(f"Bank Transaction {bt.name} has no linked payments")
                else:
                    # Check if any linked Payment Entries still exist
                    has_valid_payment = False
                    for link in linked_payments:
                        if frappe.db.exists("Payment Entry", link.payment_entry):
                            has_valid_payment = True
                            break

                    if not has_valid_payment:
                        # All linked Payment Entries are gone - orphaned
                        is_orphaned = True
                        frappe.logger().info(f"Bank Transaction {bt.name} linked to deleted Payment Entries")

                if is_orphaned:
                    # Delete the orphaned Bank Transaction
                    bt_doc = frappe.get_doc("Bank Transaction", bt.name)

                    # Cancel if submitted
                    if bt_doc.docstatus == 1:
                        bt_doc.cancel()

                    # Delete
                    frappe.delete_doc("Bank Transaction", bt.name, force=True)
                    results["deleted"] += 1
                    frappe.logger().info(
                        f"Deleted orphaned Bank Transaction {bt.name} ({bt.reference_number})"
                    )

            except Exception as bt_error:
                error_msg = f"Failed to process Bank Transaction {bt.name}: {str(bt_error)}"
                results["errors"].append(error_msg)
                frappe.logger().error(error_msg)

        frappe.logger().info(f"Orphaned Bank Transaction cleanup: {results['deleted']} deleted")

    except Exception as e:
        error_msg = f"Failed to cleanup orphaned Bank Transactions: {str(e)}"
        results["errors"].append(error_msg)
        frappe.logger().error(error_msg)

    return results
