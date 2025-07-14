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
def debug_gl_entries_comprehensive_analysis():
    """Comprehensive analysis of GL entries for debugging"""
    try:
        analysis = {
            "total_gl_entries": 0,
            "eboekhouden_entries": 0,
            "by_voucher_type": {},
            "by_company": {},
            "unbalanced_vouchers": [],
            "orphaned_entries": [],
            "date_range": {"earliest": None, "latest": None},
        }

        # Get all GL entries
        gl_entries = frappe.db.sql(
            """
            SELECT
                voucher_type,
                voucher_no,
                company,
                posting_date,
                account,
                debit,
                credit,
                against_voucher_type,
                against_voucher
            FROM `tabGL Entry`
            ORDER BY creation DESC
        """,
            as_dict=True,
        )

        analysis["total_gl_entries"] = len(gl_entries)

        for entry in gl_entries:
            # Count by voucher type
            vtype = entry.get("voucher_type", "Unknown")
            analysis["by_voucher_type"][vtype] = analysis["by_voucher_type"].get(vtype, 0) + 1

            # Count by company
            company = entry.get("company", "Unknown")
            analysis["by_company"][company] = analysis["by_company"].get(company, 0) + 1

            # Track date range
            date = entry.get("posting_date")
            if date:
                if not analysis["date_range"]["earliest"] or date < analysis["date_range"]["earliest"]:
                    analysis["date_range"]["earliest"] = date
                if not analysis["date_range"]["latest"] or date > analysis["date_range"]["latest"]:
                    analysis["date_range"]["latest"] = date

        # Check for E-Boekhouden entries
        eboekhouden_vouchers = frappe.db.sql(
            """
            SELECT DISTINCT voucher_type, voucher_no
            FROM `tabGL Entry` ge
            WHERE EXISTS (
                SELECT 1 FROM `tabSales Invoice` si
                WHERE si.name = ge.voucher_no AND si.eboekhouden_invoice_number IS NOT NULL
            ) OR EXISTS (
                SELECT 1 FROM `tabPurchase Invoice` pi
                WHERE pi.name = ge.voucher_no AND pi.eboekhouden_invoice_number IS NOT NULL
            ) OR EXISTS (
                SELECT 1 FROM `tabPayment Entry` pe
                WHERE pe.name = ge.voucher_no AND pe.eboekhouden_mutation_nr IS NOT NULL
            ) OR EXISTS (
                SELECT 1 FROM `tabJournal Entry` je
                WHERE je.name = ge.voucher_no AND je.eboekhouden_mutation_nr IS NOT NULL
            )
        """,
            as_dict=True,
        )

        analysis["eboekhouden_entries"] = len(eboekhouden_vouchers)

        # Check for unbalanced vouchers
        unbalanced = frappe.db.sql(
            """
            SELECT
                voucher_type,
                voucher_no,
                SUM(debit) as total_debit,
                SUM(credit) as total_credit,
                ABS(SUM(debit) - SUM(credit)) as difference
            FROM `tabGL Entry`
            GROUP BY voucher_type, voucher_no
            HAVING ABS(SUM(debit) - SUM(credit)) > 0.01
            ORDER BY difference DESC
            LIMIT 10
        """,
            as_dict=True,
        )

        analysis["unbalanced_vouchers"] = unbalanced

        return {"success": True, "analysis": analysis}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def debug_gl_entries_analysis(company=None):
    """Analyze GL entries with focus on E-Boekhouden imported data"""
    try:
        if not company:
            company = frappe.db.get_single_value("Global Defaults", "default_company")

        analysis = {
            "company": company,
            "gl_entry_summary": {},
            "eboekhouden_entries": {},
            "potential_issues": [],
        }

        # Basic GL entry statistics
        total_gl = frappe.db.count("GL Entry", {"company": company})
        analysis["gl_entry_summary"]["total"] = total_gl

        # E-Boekhouden specific entries
        eboekhouden_invoices = frappe.db.sql(
            """
            SELECT COUNT(*) as count, SUM(ge.debit) as total_debit, SUM(ge.credit) as total_credit
            FROM `tabGL Entry` ge
            JOIN `tabSales Invoice` si ON si.name = ge.voucher_no
            WHERE ge.company = %s AND ge.voucher_type = 'Sales Invoice'
            AND si.eboekhouden_invoice_number IS NOT NULL
        """,
            (company,),
            as_dict=True,
        )

        if eboekhouden_invoices:
            analysis["eboekhouden_entries"]["sales_invoices"] = eboekhouden_invoices[0]

        eboekhouden_purchases = frappe.db.sql(
            """
            SELECT COUNT(*) as count, SUM(ge.debit) as total_debit, SUM(ge.credit) as total_credit
            FROM `tabGL Entry` ge
            JOIN `tabPurchase Invoice` pi ON pi.name = ge.voucher_no
            WHERE ge.company = %s AND ge.voucher_type = 'Purchase Invoice'
            AND pi.eboekhouden_invoice_number IS NOT NULL
        """,
            (company,),
            as_dict=True,
        )

        if eboekhouden_purchases:
            analysis["eboekhouden_entries"]["purchase_invoices"] = eboekhouden_purchases[0]

        eboekhouden_payments = frappe.db.sql(
            """
            SELECT COUNT(*) as count, SUM(ge.debit) as total_debit, SUM(ge.credit) as total_credit
            FROM `tabGL Entry` ge
            JOIN `tabPayment Entry` pe ON pe.name = ge.voucher_no
            WHERE ge.company = %s AND ge.voucher_type = 'Payment Entry'
            AND pe.eboekhouden_mutation_nr IS NOT NULL
        """,
            (company,),
            as_dict=True,
        )

        if eboekhouden_payments:
            analysis["eboekhouden_entries"]["payment_entries"] = eboekhouden_payments[0]

        # Check for potential issues
        zero_amount_entries = frappe.db.count("GL Entry", {"company": company, "debit": 0, "credit": 0})

        if zero_amount_entries > 0:
            analysis["potential_issues"].append(f"Found {zero_amount_entries} GL entries with zero amounts")

        return {"success": True, "analysis": analysis}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def debug_nuclear_gl_cleanup():
    """Nuclear GL cleanup - removes all GL entries"""
    try:
        if not frappe.has_permission("System Manager"):
            frappe.throw("Only System Managers can perform nuclear GL cleanup")

        # Count entries before deletion
        total_entries = frappe.db.count("GL Entry")

        # Delete all GL entries
        frappe.db.sql("DELETE FROM `tabGL Entry`")
        frappe.db.commit()

        return {
            "success": True,
            "message": f"Nuclear GL cleanup completed - deleted {total_entries} GL entries",
        }

    except Exception as e:
        frappe.db.rollback()
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def debug_test_gl_deletion():
    """Test GL entry deletion for debugging"""
    try:
        # Get sample GL entries for analysis
        sample_entries = frappe.db.sql(
            """
            SELECT voucher_type, voucher_no, COUNT(*) as entry_count
            FROM `tabGL Entry`
            GROUP BY voucher_type, voucher_no
            ORDER BY entry_count DESC
            LIMIT 5
        """,
            as_dict=True,
        )

        return {"success": True, "sample_entries": sample_entries, "message": "GL deletion test completed"}

    except Exception as e:
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


@frappe.whitelist()
def debug_cleanup_remaining_gl_entries():
    """Debug cleanup of remaining GL entries"""
    try:
        # Analyze remaining GL entries
        remaining_entries = frappe.db.sql(
            """
            SELECT
                voucher_type,
                COUNT(*) as count,
                MIN(posting_date) as earliest_date,
                MAX(posting_date) as latest_date
            FROM `tabGL Entry`
            GROUP BY voucher_type
            ORDER BY count DESC
        """,
            as_dict=True,
        )

        return {
            "success": True,
            "remaining_entries": remaining_entries,
            "total_remaining": sum(entry.get("count", 0) for entry in remaining_entries),
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def debug_cleanup_all_imported_data(company=None):
    """Comprehensive cleanup of all E-Boekhouden imported data"""
    try:
        if not company:
            company = frappe.db.get_single_value("Global Defaults", "default_company")

        results = {"company": company, "cleaned_doctypes": {}, "errors": []}

        # Define doctypes and their E-Boekhouden identifier fields
        doctype_cleanup = [
            ("Sales Invoice", "eboekhouden_invoice_number"),
            ("Purchase Invoice", "eboekhouden_invoice_number"),
            ("Payment Entry", "eboekhouden_mutation_nr"),
            ("Journal Entry", "eboekhouden_mutation_nr"),
        ]

        # Clean each doctype
        for doctype, field in doctype_cleanup:
            try:
                records = frappe.get_all(
                    doctype, filters={"company": company, field: ["!=", ""]}, fields=["name"]
                )

                deleted_count = 0
                for record in records:
                    try:
                        doc = frappe.get_doc(doctype, record.name)
                        if doc.docstatus == 1:  # Submitted
                            doc.cancel()
                        doc.delete(ignore_permissions=True)
                        deleted_count += 1
                    except Exception as e:
                        results["errors"].append(f"Failed to delete {doctype} {record.name}: {str(e)}")

                results["cleaned_doctypes"][doctype] = deleted_count

            except Exception as e:
                results["errors"].append(f"Failed to clean {doctype}: {str(e)}")

        # Clean provisional parties
        provisional_customers = frappe.get_all(
            "Customer",
            filters={"customer_name": ["like", "Provisional Customer%"], "disabled": 0},
            fields=["name"],
        )

        customer_count = 0
        for customer in provisional_customers:
            try:
                frappe.delete_doc("Customer", customer.name, ignore_permissions=True)
                customer_count += 1
            except Exception as e:
                results["errors"].append(f"Failed to delete customer {customer.name}: {str(e)}")

        results["cleaned_doctypes"]["Customer"] = customer_count

        provisional_suppliers = frappe.get_all(
            "Supplier",
            filters={"supplier_name": ["like", "Provisional Supplier%"], "disabled": 0},
            fields=["name"],
        )

        supplier_count = 0
        for supplier in provisional_suppliers:
            try:
                frappe.delete_doc("Supplier", supplier.name, ignore_permissions=True)
                supplier_count += 1
            except Exception as e:
                results["errors"].append(f"Failed to delete supplier {supplier.name}: {str(e)}")

        results["cleaned_doctypes"]["Supplier"] = supplier_count

        frappe.db.commit()

        total_cleaned = sum(results["cleaned_doctypes"].values())
        return {
            "success": True,
            "message": f"Cleaned {total_cleaned} records across {len(results['cleaned_doctypes'])} doctypes",
            "results": results,
        }

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
