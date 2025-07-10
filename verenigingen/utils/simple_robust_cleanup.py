#!/usr/bin/env python3
"""
Simple robust cleanup function to completely clean up all imported eBoekhouden data
"""

import frappe


@frappe.whitelist()
def simple_robust_cleanup(company=None):
    """Simple robust function to completely clean up all imported data"""
    try:
        # Get default company if not provided
        if not company:
            try:
                settings = frappe.get_single("E-Boekhouden Settings")
                company = settings.default_company or "Ned Ver Vegan"
            except Exception:
                company = "Ned Ver Vegan"

        results = {"success": True, "company": company, "steps_completed": [], "errors": []}

        # Ensure fresh database connection and disable FK checks
        frappe.db.connect()
        frappe.db.sql("SET FOREIGN_KEY_CHECKS = 0")
        frappe.db.commit()

        try:
            # Step 1: Delete Payment Ledger Entries
            try:
                ple_count = frappe.db.sql(
                    "DELETE FROM `tabPayment Ledger Entry` WHERE company = %s", (company,)
                )
                results["payment_ledger_entries_deleted"] = ple_count
                results["steps_completed"].append(f"Payment Ledger Entries: {ple_count} deleted")
                frappe.db.commit()
            except Exception as e:
                results["errors"].append(f"Payment Ledger cleanup: {str(e)}")

            # Step 2: Delete GL Entries for eBoekhouden imports
            try:
                gl_count = frappe.db.sql(
                    """DELETE FROM `tabGL Entry`
                       WHERE company = %s
                       AND (remarks LIKE '%%eBoekhouden%%' OR remarks LIKE '%%E-Boekhouden%%')""",
                    (company,),
                )
                results["gl_entries_deleted"] = gl_count
                results["steps_completed"].append(f"GL Entries: {gl_count} deleted")
                frappe.db.commit()
            except Exception as e:
                results["errors"].append(f"GL Entry cleanup: {str(e)}")

            # Step 3: Get and delete Journal Entries
            try:
                # Find eBoekhouden Journal Entries
                je_names = []

                je_list = frappe.db.sql(
                    """SELECT name FROM `tabJournal Entry`
                       WHERE company = %s
                       AND (user_remark LIKE '%%eBoekhouden%%'
                            OR user_remark LIKE '%%E-Boekhouden%%'
                            OR title LIKE '%%eBoekhouden%%'
                            OR name LIKE '%%EBH-%%')""",
                    (company,),
                    as_list=True,
                )
                je_names = [name[0] for name in je_list]

                if je_names:
                    # Delete child records first
                    je_placeholder = ",".join(["%s"] * len(je_names))
                    frappe.db.sql(
                        f"DELETE FROM `tabJournal Entry Account` WHERE parent IN ({je_placeholder})", je_names
                    )

                    # Delete Journal Entries
                    frappe.db.sql(
                        f"DELETE FROM `tabJournal Entry` WHERE name IN ({je_placeholder})", je_names
                    )

                    results["journal_entries_deleted"] = len(je_names)
                    results["steps_completed"].append(f"Journal Entries: {len(je_names)} deleted")
                else:
                    results["journal_entries_deleted"] = 0
                    results["steps_completed"].append("Journal Entries: 0 deleted")

                frappe.db.commit()
            except Exception as e:
                results["errors"].append(f"Journal Entry cleanup: {str(e)}")

            # Step 4: Get and delete Payment Entries
            try:
                pe_names = []
                pe_list = frappe.db.sql(
                    """SELECT name FROM `tabPayment Entry`
                       WHERE company = %s
                       AND (remarks LIKE '%%eBoekhouden%%'
                            OR remarks LIKE '%%E-Boekhouden%%'
                            OR reference_no LIKE '%%EBH-%%')""",
                    (company,),
                    as_list=True,
                )
                pe_names = [name[0] for name in pe_list]

                if pe_names:
                    # Delete child records first
                    pe_placeholder = ",".join(["%s"] * len(pe_names))
                    for child_table in ["Payment Entry Reference", "Payment Entry Deduction"]:
                        try:
                            frappe.db.sql(
                                f"DELETE FROM `tab{child_table}` WHERE parent IN ({pe_placeholder})", pe_names
                            )
                        except Exception:
                            pass

                    # Set to cancelled first to avoid constraints
                    frappe.db.sql(
                        "UPDATE `tabPayment Entry` SET docstatus = 2 WHERE name IN ({pe_placeholder})",
                        pe_names,
                    )

                    # Delete Payment Entries
                    frappe.db.sql(
                        f"DELETE FROM `tabPayment Entry` WHERE name IN ({pe_placeholder})", pe_names
                    )

                    results["payment_entries_deleted"] = len(pe_names)
                    results["steps_completed"].append(f"Payment Entries: {len(pe_names)} deleted")
                else:
                    results["payment_entries_deleted"] = 0
                    results["steps_completed"].append("Payment Entries: 0 deleted")

                frappe.db.commit()
            except Exception as e:
                results["errors"].append(f"Payment Entry cleanup: {str(e)}")

            # Step 5: Get and delete Sales Invoices
            try:
                si_names = []
                si_list = frappe.db.sql(
                    """SELECT name FROM `tabSales Invoice`
                       WHERE company = %s
                       AND (remarks LIKE '%%eBoekhouden%%'
                            OR remarks LIKE '%%E-Boekhouden%%'
                            OR name LIKE '%%EBH-%%')""",
                    (company,),
                    as_list=True,
                )
                si_names = [name[0] for name in si_list]

                if si_names:
                    si_placeholder = ",".join(["%s"] * len(si_names))

                    # Delete child records
                    for child_table in ["Sales Invoice Item", "Sales Taxes and Charges"]:
                        try:
                            frappe.db.sql(
                                f"DELETE FROM `tab{child_table}` WHERE parent IN ({si_placeholder})", si_names
                            )
                        except Exception:
                            pass

                    # Delete Sales Invoices
                    frappe.db.sql(
                        f"DELETE FROM `tabSales Invoice` WHERE name IN ({si_placeholder})", si_names
                    )

                    results["sales_invoices_deleted"] = len(si_names)
                    results["steps_completed"].append(f"Sales Invoices: {len(si_names)} deleted")
                else:
                    results["sales_invoices_deleted"] = 0
                    results["steps_completed"].append("Sales Invoices: 0 deleted")

                frappe.db.commit()
            except Exception as e:
                results["errors"].append(f"Sales Invoice cleanup: {str(e)}")

            # Step 6: Get and delete Purchase Invoices
            try:
                pi_names = []
                pi_list = frappe.db.sql(
                    """SELECT name FROM `tabPurchase Invoice`
                       WHERE company = %s
                       AND (remarks LIKE '%%eBoekhouden%%'
                            OR remarks LIKE '%%E-Boekhouden%%'
                            OR name LIKE '%%EBH-%%')""",
                    (company,),
                    as_list=True,
                )
                pi_names = [name[0] for name in pi_list]

                if pi_names:
                    pi_placeholder = ",".join(["%s"] * len(pi_names))

                    # Delete child records
                    for child_table in ["Purchase Invoice Item", "Purchase Taxes and Charges"]:
                        try:
                            frappe.db.sql(
                                f"DELETE FROM `tab{child_table}` WHERE parent IN ({pi_placeholder})", pi_names
                            )
                        except Exception:
                            pass

                    # Delete Purchase Invoices
                    frappe.db.sql(
                        f"DELETE FROM `tabPurchase Invoice` WHERE name IN ({pi_placeholder})", pi_names
                    )

                    results["purchase_invoices_deleted"] = len(pi_names)
                    results["steps_completed"].append(f"Purchase Invoices: {len(pi_names)} deleted")
                else:
                    results["purchase_invoices_deleted"] = 0
                    results["steps_completed"].append("Purchase Invoices: 0 deleted")

                frappe.db.commit()
            except Exception as e:
                results["errors"].append(f"Purchase Invoice cleanup: {str(e)}")

            # Step 7: Clean up any remaining repost entries
            try:
                repost_count = 0
                for table in [
                    "Repost Accounting Ledger",
                    "Repost Accounting Ledger Items",
                    "Repost Payment Ledger",
                    "Repost Payment Ledger Items",
                ]:
                    try:
                        count = frappe.db.sql(f"DELETE FROM `tab{table}` WHERE company = %s", (company,))
                        repost_count += count
                    except Exception:
                        pass

                if repost_count > 0:
                    results["steps_completed"].append(f"Repost entries: {repost_count} deleted")

                frappe.db.commit()
            except Exception as e:
                results["errors"].append(f"Repost cleanup: {str(e)}")

        finally:
            # Re-enable foreign key checks
            frappe.db.sql("SET FOREIGN_KEY_CHECKS = 1")
            frappe.db.commit()

        # Calculate totals
        total_deleted = (
            results.get("journal_entries_deleted", 0)
            + results.get("payment_entries_deleted", 0)
            + results.get("sales_invoices_deleted", 0)
            + results.get("purchase_invoices_deleted", 0)
        )

        results["total_documents_deleted"] = total_deleted
        results["message"] = f"Nuclear cleanup completed successfully: {total_deleted} documents deleted"

        if results["errors"]:
            results["warning"] = f"Completed with {len(results['errors'])} errors"

        return results

    except Exception as e:
        # Ensure foreign key checks are re-enabled
        try:
            frappe.db.sql("SET FOREIGN_KEY_CHECKS = 1")
            frappe.db.commit()
        except Exception:
            pass

        return {"success": False, "error": str(e), "message": "Critical error during cleanup"}
