"""
Bulk delete test Sales Invoices and their Member Payment History links

This utility provides a UI-accessible method for bulk deleting test invoices
that are linked to Member records via the payment_history child table.
"""

import frappe
from frappe import _


@frappe.whitelist()
def delete_test_invoices():
    """
    Delete all Sales Invoices with 'Test' in customer name/title
    and remove their Member Payment History links.

    Returns dict with deletion statistics
    """
    frappe.only_for("System Manager")  # Restrict to System Managers only

    # Find all test invoices
    test_invoices = frappe.db.sql(
        """
        SELECT name, customer, docstatus
        FROM `tabSales Invoice`
        WHERE customer LIKE %s OR title LIKE %s
    """,
        ("%Test%", "%Test%"),
        as_dict=True,
    )

    if not test_invoices:
        return {
            "success": True,
            "message": "No test invoices found",
            "deleted": 0,
            "cancelled": 0,
            "payment_history_removed": 0,
        }

    invoice_names = [inv.name for inv in test_invoices]

    # Remove Member Payment History links first
    payment_history_count = frappe.db.sql(
        """
        DELETE FROM `tabMember Payment History`
        WHERE invoice IN ({})
    """.format(
            ", ".join(["%s"] * len(invoice_names))
        ),
        tuple(invoice_names),
    )

    frappe.db.commit()

    deleted_count = 0
    cancelled_count = 0
    error_count = 0
    errors = []

    for inv in test_invoices:
        try:
            doc = frappe.get_doc("Sales Invoice", inv.name)

            # Cancel if submitted
            if doc.docstatus == 1:
                doc.cancel()
                cancelled_count += 1

            # Delete GL Entries if they exist
            frappe.db.sql("DELETE FROM `tabGL Entry` WHERE voucher_no = %s", (inv.name,))

            # Delete Sales Invoice Items
            frappe.db.sql("DELETE FROM `tabSales Invoice Item` WHERE parent = %s", (inv.name,))

            # Delete the invoice via SQL to bypass any remaining link checks
            frappe.db.sql("DELETE FROM `tabSales Invoice` WHERE name = %s", (inv.name,))

            deleted_count += 1

            if deleted_count % 100 == 0:
                frappe.db.commit()
                frappe.publish_realtime(
                    "bulk_delete_progress",
                    {"processed": deleted_count, "total": len(test_invoices)},
                    user=frappe.session.user,
                )

        except Exception as e:
            error_count += 1
            if error_count <= 10:
                errors.append(f"{inv.name}: {str(e)[:100]}")

    frappe.db.commit()

    result = {
        "success": True,
        "message": f"Deleted {deleted_count} invoices (cancelled {cancelled_count} first)",
        "deleted": deleted_count,
        "cancelled": cancelled_count,
        "payment_history_removed": payment_history_count,
        "errors": error_count,
        "error_details": errors if errors else None,
    }

    return result
