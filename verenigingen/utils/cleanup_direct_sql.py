#!/usr/bin/env python3

import frappe


@frappe.whitelist()
def direct_cleanup_gl_and_pl():
    """Direct SQL cleanup of GL and Payment Ledger entries"""
    try:
        # Count entries before cleanup
        gl_count_before = frappe.db.sql("SELECT COUNT(*) FROM `tabGL Entry`")[0][0]
        pl_count_before = frappe.db.sql("SELECT COUNT(*) FROM `tabPayment Ledger Entry`")[0][0]

        print(f"Before cleanup: {gl_count_before} GL entries, {pl_count_before} Payment Ledger entries")

        # Delete GL Entries
        frappe.db.sql("DELETE FROM `tabGL Entry`")

        # Delete Payment Ledger Entries
        frappe.db.sql("DELETE FROM `tabPayment Ledger Entry`")

        # Delete Journal Entries
        frappe.db.sql("DELETE FROM `tabJournal Entry Account`")
        frappe.db.sql("DELETE FROM `tabJournal Entry`")

        # Delete Payment Entries
        frappe.db.sql("DELETE FROM `tabPayment Entry Reference`")
        frappe.db.sql("DELETE FROM `tabPayment Entry Deduction`")
        frappe.db.sql("DELETE FROM `tabPayment Entry`")

        # Delete Sales Invoices
        frappe.db.sql("DELETE FROM `tabSales Invoice Item`")
        frappe.db.sql("DELETE FROM `tabSales Invoice`")

        # Delete Purchase Invoices
        frappe.db.sql("DELETE FROM `tabPurchase Invoice Item`")
        frappe.db.sql("DELETE FROM `tabPurchase Invoice`")

        frappe.db.commit()

        # Count entries after cleanup
        gl_count_after = frappe.db.sql("SELECT COUNT(*) FROM `tabGL Entry`")[0][0]
        pl_count_after = frappe.db.sql("SELECT COUNT(*) FROM `tabPayment Ledger Entry`")[0][0]

        return {
            "success": True,
            "message": "Direct SQL cleanup completed",
            "results": {
                "gl_entries_deleted": gl_count_before - gl_count_after,
                "payment_ledger_deleted": pl_count_before - pl_count_after,
                "gl_remaining": gl_count_after,
                "pl_remaining": pl_count_after,
            },
        }

    except Exception as e:
        frappe.db.rollback()
        return {"success": False, "error": str(e)}
