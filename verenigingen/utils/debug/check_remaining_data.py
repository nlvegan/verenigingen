#!/usr/bin/env python3
"""
Check what data remains after cleanup
"""

import frappe


@frappe.whitelist()
def check_remaining_data():
    """Check what financial data remains after cleanup"""
    try:
        company = "Ned Ver Vegan"

        results = {"company": company, "remaining_data": {}}

        # Check Payment Entries
        pe_count = frappe.db.sql("SELECT COUNT(*) FROM `tabPayment Entry` WHERE company = %s", (company,))[0][
            0
        ]
        results["remaining_data"]["payment_entries"] = pe_count

        # Check Journal Entries
        je_count = frappe.db.sql("SELECT COUNT(*) FROM `tabJournal Entry` WHERE company = %s", (company,))[0][
            0
        ]
        results["remaining_data"]["journal_entries"] = je_count

        # Check GL Entries
        gl_count = frappe.db.sql("SELECT COUNT(*) FROM `tabGL Entry` WHERE company = %s", (company,))[0][0]
        results["remaining_data"]["gl_entries"] = gl_count

        # Check Payment Ledger Entries
        ple_count = frappe.db.sql(
            "SELECT COUNT(*) FROM `tabPayment Ledger Entry` WHERE company = %s", (company,)
        )[0][0]
        results["remaining_data"]["payment_ledger_entries"] = ple_count

        # Check Sales Invoices
        si_count = frappe.db.sql("SELECT COUNT(*) FROM `tabSales Invoice` WHERE company = %s", (company,))[0][
            0
        ]
        results["remaining_data"]["sales_invoices"] = si_count

        # Check Purchase Invoices
        pi_count = frappe.db.sql("SELECT COUNT(*) FROM `tabPurchase Invoice` WHERE company = %s", (company,))[
            0
        ][0]
        results["remaining_data"]["purchase_invoices"] = pi_count

        # Sample of remaining Payment Entries
        if pe_count > 0:
            sample_pes = frappe.db.sql(
                """SELECT name, payment_type, party_type, party, paid_amount,
                          reference_no, remarks, creation
                   FROM `tabPayment Entry`
                   WHERE company = %s
                   ORDER BY creation DESC
                   LIMIT 5""",
                (company,),
                as_dict=True,
            )
            results["sample_payment_entries"] = sample_pes

        # Sample of remaining GL Entries
        if gl_count > 0:
            sample_gls = frappe.db.sql(
                """SELECT voucher_type, voucher_no, account, debit, credit,
                          remarks, posting_date
                   FROM `tabGL Entry`
                   WHERE company = %s
                   ORDER BY creation DESC
                   LIMIT 5""",
                (company,),
                as_dict=True,
            )
            results["sample_gl_entries"] = sample_gls

        return results

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def nuclear_cleanup_remaining():
    """Nuclear cleanup of ALL remaining financial data"""
    try:
        company = "Ned Ver Vegan"

        results = {"company": company, "cleanup_steps": []}

        # Disable FK checks
        frappe.db.sql("SET FOREIGN_KEY_CHECKS = 0")
        frappe.db.commit()

        try:
            # Delete ALL Payment Entries for this company
            pe_deleted = frappe.db.sql("DELETE FROM `tabPayment Entry` WHERE company = %s", (company,))
            results["cleanup_steps"].append(f"Payment Entries deleted: {pe_deleted}")

            # Delete ALL Journal Entries for this company
            je_deleted = frappe.db.sql("DELETE FROM `tabJournal Entry` WHERE company = %s", (company,))
            results["cleanup_steps"].append(f"Journal Entries deleted: {je_deleted}")

            # Delete ALL GL Entries for this company
            gl_deleted = frappe.db.sql("DELETE FROM `tabGL Entry` WHERE company = %s", (company,))
            results["cleanup_steps"].append(f"GL Entries deleted: {gl_deleted}")

            # Delete ALL Payment Ledger Entries for this company
            ple_deleted = frappe.db.sql(
                "DELETE FROM `tabPayment Ledger Entry` WHERE company = %s", (company,)
            )
            results["cleanup_steps"].append(f"Payment Ledger Entries deleted: {ple_deleted}")

            # Delete ALL Sales Invoices for this company
            si_deleted = frappe.db.sql("DELETE FROM `tabSales Invoice` WHERE company = %s", (company,))
            results["cleanup_steps"].append(f"Sales Invoices deleted: {si_deleted}")

            # Delete ALL Purchase Invoices for this company
            pi_deleted = frappe.db.sql("DELETE FROM `tabPurchase Invoice` WHERE company = %s", (company,))
            results["cleanup_steps"].append(f"Purchase Invoices deleted: {pi_deleted}")

            # Delete child table entries
            child_tables = [
                "Journal Entry Account",
                "Payment Entry Reference",
                "Payment Entry Deduction",
                "Sales Invoice Item",
                "Sales Taxes and Charges",
                "Purchase Invoice Item",
                "Purchase Taxes and Charges",
            ]

            for table in child_tables:
                try:
                    child_deleted = frappe.db.sql(
                        "DELETE FROM `tab{table}` WHERE parent IN (SELECT name FROM `tabJournal Entry` WHERE company = %s UNION SELECT name FROM `tabPayment Entry` WHERE company = %s UNION SELECT name FROM `tabSales Invoice` WHERE company = %s UNION SELECT name FROM `tabPurchase Invoice` WHERE company = %s)",
                        (company, company, company, company),
                    )
                    if child_deleted:
                        results["cleanup_steps"].append("{table} entries deleted: {child_deleted}")
                except Exception:
                    # Delete directly from remaining entries
                    frappe.db.sql("DELETE FROM `tab{table}`")

            frappe.db.commit()

        finally:
            # Re-enable FK checks
            frappe.db.sql("SET FOREIGN_KEY_CHECKS = 1")
            frappe.db.commit()

        results["success"] = True
        results["message"] = "Nuclear cleanup completed - ALL financial data deleted"

        return results

    except Exception as e:
        try:
            frappe.db.sql("SET FOREIGN_KEY_CHECKS = 1")
            frappe.db.commit()
        except Exception:
            pass
        return {"success": False, "error": str(e)}
