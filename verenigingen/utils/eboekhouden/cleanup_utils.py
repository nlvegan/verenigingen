"""
E-Boekhouden Cleanup Utilities

Conservative refactor: These functions were moved from the main migration file
to improve organization. All original logic is preserved exactly as-is.
"""

import json

import frappe


@frappe.whitelist()
def cleanup_chart_of_accounts(company, delete_all_accounts=0):
    """Clean up chart of accounts imported from E-Boekhouden"""
    try:
        if not frappe.has_permission("Account", "delete"):
            frappe.throw("Insufficient permissions to delete accounts")

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
                filters={"company": company, "custom_eboekhouden_code": ["!=", ""]},
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

                # Try to delete the account
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
                records = frappe.get_all(doctype, filters={field: ["!=", ""]}, fields=["name"])
                for record in records:
                    try:
                        frappe.delete_doc(doctype, record.name, force=True, ignore_permissions=True)
                        results[doctype.lower().replace(" ", "_") + "s"] += 1
                    except Exception as e:
                        results["errors"].append(f"Failed to delete {doctype} {record.name}: {str(e)}")

            except Exception as e:
                results["errors"].append(f"Failed to clean {doctype}: {str(e)}")

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

        frappe.db.commit()

        return {"success": True, "message": "Nuclear cleanup completed", "results": results}

    except Exception as e:
        frappe.db.rollback()
        return {"success": False, "error": str(e)}


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
