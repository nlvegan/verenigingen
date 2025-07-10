#!/usr/bin/env python3
"""
Robust cleanup function to completely clean up all imported eBoekhouden data
Includes Payment Ledger Entry cleanup and better error handling
"""

import frappe


@frappe.whitelist()
def robust_cleanup_all_imported_data(company=None):
    """Robust function to completely clean up all imported data for fresh migration"""
    try:
        # Get default company if not provided
        if not company:
            try:
                settings = frappe.get_single("E-Boekhouden Settings")
                company = settings.default_company
            except Exception:
                company = "Ned Ver Vegan"  # Fallback to known company

        if not company:
            return {"success": False, "error": "No company specified"}

        results = {
            "success": True,
            "company": company,
            "journal_entries_deleted": 0,
            "payment_entries_deleted": 0,
            "sales_invoices_deleted": 0,
            "purchase_invoices_deleted": 0,
            "gl_entries_deleted": 0,
            "payment_ledger_entries_deleted": 0,
            "accounting_ledger_entries_deleted": 0,
            "errors": [],
        }

        # Ensure fresh database connection
        frappe.db.connect()

        # Disable foreign key checks for cleanup
        frappe.db.sql("SET FOREIGN_KEY_CHECKS = 0")
        frappe.db.commit()

        try:
            # Step 1: Clean up Payment Ledger Entries first (these depend on other documents)
            try:
                ple_deleted = frappe.db.sql(
                    """DELETE FROM `tabPayment Ledger Entry`
                       WHERE company = %s
                       AND (voucher_type IN ('Journal Entry', 'Payment Entry', 'Sales Invoice', 'Purchase Invoice')
                            OR account_type IN ('Receivable', 'Payable'))""",
                    (company,),
                )
                results["payment_ledger_entries_deleted"] = ple_deleted
                frappe.db.commit()
            except Exception as e:
                results["errors"].append(f"Payment Ledger Entry cleanup error: {str(e)}")

            # Step 2: Clean up GL Entries for imported documents
            try:
                gl_deleted = frappe.db.sql(
                    """DELETE FROM `tabGL Entry`
                       WHERE company = %s
                       AND (voucher_type IN ('Journal Entry', 'Payment Entry', 'Sales Invoice', 'Purchase Invoice')
                            OR remarks LIKE '%eBoekhouden%'
                            OR remarks LIKE '%E-Boekhouden%')""",
                    (company,),
                )
                results["gl_entries_deleted"] = gl_deleted
                frappe.db.commit()
            except Exception as e:
                results["errors"].append(f"GL Entry cleanup error: {str(e)}")

            # Step 3: Clean up Journal Entry dependencies
            try:
                # Get all eBoekhouden Journal Entries
                je_names = []

                # Pattern 1: User remark contains import indicators
                je_list1 = frappe.db.sql(
                    """SELECT name FROM `tabJournal Entry`
                       WHERE company = %s
                       AND (user_remark LIKE '%eBoekhouden%'
                            OR user_remark LIKE '%E-Boekhouden%'
                            OR title LIKE '%eBoekhouden%'
                            OR title LIKE '%EBH-%')""",
                    (company,),
                    as_list=True,
                )
                je_names.extend([name[0] for name in je_list1])

                # Pattern 2: Custom field if exists
                try:
                    je_list2 = frappe.db.sql(
                        """SELECT name FROM `tabJournal Entry`
                           WHERE company = %s
                           AND eboekhouden_mutation_nr IS NOT NULL
                           AND eboekhouden_mutation_nr != ''""",
                        (company,),
                        as_list=True,
                    )
                    je_names.extend([name[0] for name in je_list2])
                except Exception:
                    pass  # Field might not exist

                # Deduplicate
                je_names = list(set(je_names))

                if je_names:
                    # Clean Journal Entry Account child records
                    frappe.db.sql(
                        """DELETE FROM `tabJournal Entry Account`
                            WHERE parent IN ({','.join(['%s'] * len(je_names))})""",
                        je_names,
                    )

                    # Clean Journal Entries themselves
                    frappe.db.sql(
                        """DELETE FROM `tabJournal Entry`
                            WHERE name IN ({','.join(['%s'] * len(je_names))})""",
                        je_names,
                    )

                    results["journal_entries_deleted"] = len(je_names)
                    frappe.db.commit()

            except Exception as e:
                results["errors"].append(f"Journal Entry cleanup error: {str(e)}")

            # Step 4: Clean up Payment Entries
            try:
                # Get eBoekhouden Payment Entries
                pe_names = []

                pe_list1 = frappe.db.sql(
                    """SELECT name FROM `tabPayment Entry`
                       WHERE company = %s
                       AND (remarks LIKE '%eBoekhouden%'
                            OR remarks LIKE '%E-Boekhouden%'
                            OR reference_no LIKE '%EBH-%')""",
                    company,
                    as_list=True,
                )
                pe_names.extend([name[0] for name in pe_list1])

                # Custom field if exists
                try:
                    pe_list2 = frappe.db.sql(
                        """SELECT name FROM `tabPayment Entry`
                           WHERE company = %s
                           AND eboekhouden_mutation_nr IS NOT NULL
                           AND eboekhouden_mutation_nr != ''""",
                        company,
                        as_list=True,
                    )
                    pe_names.extend([name[0] for name in pe_list2])
                except Exception:
                    pass

                pe_names = list(set(pe_names))

                if pe_names:
                    # Clean Payment Entry child records first
                    for child_table in ["Payment Entry Reference", "Payment Entry Deduction"]:
                        try:
                            frappe.db.sql(
                                """DELETE FROM `tab{child_table}`
                                    WHERE parent IN ({','.join(['%s'] * len(pe_names))})""",
                                pe_names,
                            )
                        except Exception:
                            pass

                    # Set all to cancelled status first
                    frappe.db.sql(
                        """UPDATE `tabPayment Entry`
                            SET docstatus = 2
                            WHERE name IN ({','.join(['%s'] * len(pe_names))})""",
                        pe_names,
                    )

                    # Delete Payment Entries
                    frappe.db.sql(
                        """DELETE FROM `tabPayment Entry`
                            WHERE name IN ({','.join(['%s'] * len(pe_names))})""",
                        pe_names,
                    )

                    results["payment_entries_deleted"] = len(pe_names)
                    frappe.db.commit()

            except Exception as e:
                results["errors"].append(f"Payment Entry cleanup error: {str(e)}")

            # Step 5: Clean up Sales Invoices
            try:
                si_names = []

                si_list1 = frappe.db.sql(
                    """SELECT name FROM `tabSales Invoice`
                       WHERE company = %s
                       AND (remarks LIKE '%eBoekhouden%'
                            OR remarks LIKE '%E-Boekhouden%'
                            OR name LIKE '%EBH-%')""",
                    company,
                    as_list=True,
                )
                si_names.extend([name[0] for name in si_list1])

                # Custom field if exists
                try:
                    si_list2 = frappe.db.sql(
                        """SELECT name FROM `tabSales Invoice`
                           WHERE company = %s
                           AND eboekhouden_mutation_nr IS NOT NULL
                           AND eboekhouden_mutation_nr != ''""",
                        company,
                        as_list=True,
                    )
                    si_names.extend([name[0] for name in si_list2])
                except Exception:
                    pass

                si_names = list(set(si_names))

                if si_names:
                    # Clean child records
                    for child_table in ["Sales Invoice Item", "Sales Taxes and Charges"]:
                        try:
                            frappe.db.sql(
                                """DELETE FROM `tab{child_table}`
                                    WHERE parent IN ({','.join(['%s'] * len(si_names))})""",
                                si_names,
                            )
                        except Exception:
                            pass

                    # Delete Sales Invoices
                    frappe.db.sql(
                        """DELETE FROM `tabSales Invoice`
                            WHERE name IN ({','.join(['%s'] * len(si_names))})""",
                        si_names,
                    )

                    results["sales_invoices_deleted"] = len(si_names)
                    frappe.db.commit()

            except Exception as e:
                results["errors"].append(f"Sales Invoice cleanup error: {str(e)}")

            # Step 6: Clean up Purchase Invoices
            try:
                pi_names = []

                pi_list1 = frappe.db.sql(
                    """SELECT name FROM `tabPurchase Invoice`
                       WHERE company = %s
                       AND (remarks LIKE '%eBoekhouden%'
                            OR remarks LIKE '%E-Boekhouden%'
                            OR name LIKE '%EBH-%')""",
                    company,
                    as_list=True,
                )
                pi_names.extend([name[0] for name in pi_list1])

                # Custom field if exists
                try:
                    pi_list2 = frappe.db.sql(
                        """SELECT name FROM `tabPurchase Invoice`
                           WHERE company = %s
                           AND eboekhouden_mutation_nr IS NOT NULL
                           AND eboekhouden_mutation_nr != ''""",
                        company,
                        as_list=True,
                    )
                    pi_names.extend([name[0] for name in pi_list2])
                except Exception:
                    pass

                pi_names = list(set(pi_names))

                if pi_names:
                    # Clean child records
                    for child_table in ["Purchase Invoice Item", "Purchase Taxes and Charges"]:
                        try:
                            frappe.db.sql(
                                """DELETE FROM `tab{child_table}`
                                    WHERE parent IN ({','.join(['%s'] * len(pi_names))})""",
                                pi_names,
                            )
                        except Exception:
                            pass

                    # Delete Purchase Invoices
                    frappe.db.sql(
                        """DELETE FROM `tabPurchase Invoice`
                            WHERE name IN ({','.join(['%s'] * len(pi_names))})""",
                        pi_names,
                    )

                    results["purchase_invoices_deleted"] = len(pi_names)
                    frappe.db.commit()

            except Exception as e:
                results["errors"].append(f"Purchase Invoice cleanup error: {str(e)}")

            # Step 7: Final cleanup of any remaining ledger entries
            try:
                # Clean up any remaining Repost entries
                for table in [
                    "Repost Accounting Ledger",
                    "Repost Accounting Ledger Items",
                    "Repost Payment Ledger",
                    "Repost Payment Ledger Items",
                ]:
                    try:
                        frappe.db.sql(f"DELETE FROM `tab{table}` WHERE company = %s", company)
                    except Exception:
                        pass

                frappe.db.commit()
            except Exception as e:
                results["errors"].append(f"Final ledger cleanup error: {str(e)}")

        finally:
            # Re-enable foreign key checks
            frappe.db.sql("SET FOREIGN_KEY_CHECKS = 1")
            frappe.db.commit()

        # Calculate total
        total_deleted = (
            results["journal_entries_deleted"]
            + results["payment_entries_deleted"]
            + results["sales_invoices_deleted"]
            + results["purchase_invoices_deleted"]
        )

        results["total_documents_deleted"] = total_deleted
        results["message"] = f"Cleanup completed: {total_deleted} documents deleted"

        if results["errors"]:
            results["warning"] = f"Completed with {len(results['errors'])} non-critical errors"

        return results

    except Exception as e:
        # Ensure foreign key checks are re-enabled even on error
        try:
            frappe.db.sql("SET FOREIGN_KEY_CHECKS = 1")
            frappe.db.commit()
        except Exception:
            pass

        return {
            "success": False,
            "error": str(e),
            "message": "Critical error during cleanup - foreign key checks re-enabled",
        }
