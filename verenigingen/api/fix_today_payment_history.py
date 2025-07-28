"""
Fix missing payment history entries for today's invoices
"""

import frappe
from frappe import _
from frappe.utils import today

from verenigingen.utils.security.api_security_framework import OperationType, critical_api


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def fix_today_invoices():
    """Add today's invoices to payment history"""

    # Get all invoices created today that are linked to members
    today_invoices = frappe.db.sql(
        """
        SELECT
            si.name as invoice_name,
            si.customer,
            c.member
        FROM `tabSales Invoice` si
        INNER JOIN `tabCustomer` c ON si.customer = c.name
        WHERE si.posting_date = %s
        AND si.docstatus = 1
        AND c.member IS NOT NULL
    """,
        today(),
        as_dict=True,
    )

    results = {"date": today(), "invoices_found": len(today_invoices), "members_updated": 0, "errors": []}

    # Group by member
    member_invoices = {}
    for invoice in today_invoices:
        if invoice.member not in member_invoices:
            member_invoices[invoice.member] = []
        member_invoices[invoice.member].append(invoice.invoice_name)

    # Update each member
    for member_name, invoice_names in member_invoices.items():
        try:
            member = frappe.get_doc("Member", member_name)

            for invoice_name in invoice_names:
                try:
                    member.add_invoice_to_payment_history(invoice_name)
                except Exception as e:
                    results["errors"].append(
                        {"member": member_name, "invoice": invoice_name, "error": str(e)}
                    )

            results["members_updated"] += 1

        except Exception as e:
            results["errors"].append({"member": member_name, "error": str(e)})

    results["success"] = results["members_updated"] > 0
    results[
        "message"
    ] = f"Updated {results['members_updated']} members with {results['invoices_found']} invoices"

    return results


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def check_bulk_flag_status():
    """Check if bulk invoice generation flag is set"""

    return {
        "bulk_invoice_generation": getattr(frappe.flags, "bulk_invoice_generation", None),
        "in_invoice_generation": getattr(frappe.flags, "in_invoice_generation", None),
        "all_flags": {k: v for k, v in frappe.flags.__dict__.items() if not k.startswith("_")},
    }
