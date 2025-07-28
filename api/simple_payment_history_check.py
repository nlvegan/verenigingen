"""
Simple payment history check
"""

import frappe
from frappe import _
from frappe.utils import today


@frappe.whitelist()
def check_missing_invoices():
    """Check for today's invoices that are missing from payment history"""

    # Get all invoices created today
    today_invoices = frappe.db.sql(
        """
        SELECT
            si.name as invoice_name,
            si.customer,
            si.grand_total,
            si.posting_date,
            c.member
        FROM `tabSales Invoice` si
        LEFT JOIN (
            SELECT name, member
            FROM `tabCustomer`
            WHERE member IS NOT NULL
        ) c ON si.customer = c.name
        WHERE si.posting_date = %s
        AND si.docstatus = 1
        AND c.member IS NOT NULL
        ORDER BY si.creation DESC
        LIMIT 20
    """,
        today(),
        as_dict=True,
    )

    results = {
        "date": today(),
        "invoices_found": len(today_invoices),
        "missing_from_history": [],
        "in_history": [],
    }

    for invoice in today_invoices:
        member_name = invoice.member

        # Check if invoice is in member's payment history
        in_history = frappe.db.exists(
            "Member Payment History", {"parent": member_name, "invoice": invoice.invoice_name}
        )

        invoice_info = {
            "invoice": invoice.invoice_name,
            "member": member_name,
            "customer": invoice.customer,
            "amount": invoice.grand_total,
        }

        if in_history:
            results["in_history"].append(invoice_info)
        else:
            results["missing_from_history"].append(invoice_info)

    results["missing_count"] = len(results["missing_from_history"])
    results["in_history_count"] = len(results["in_history"])

    return results


@frappe.whitelist()
def fix_missing_payment_history():
    """Add missing invoices to payment history"""

    # First check what's missing
    check_results = check_missing_invoices()

    fixed_members = []
    errors = []

    for missing in check_results["missing_from_history"]:
        try:
            member = frappe.get_doc("Member", missing["member"])
            member.add_invoice_to_payment_history(missing["invoice"])
            fixed_members.append(
                {"member": missing["member"], "invoice": missing["invoice"], "status": "Fixed"}
            )
        except Exception as e:
            errors.append({"member": missing["member"], "invoice": missing["invoice"], "error": str(e)})

    return {
        "fixed": len(fixed_members),
        "errors": len(errors),
        "fixed_details": fixed_members,
        "error_details": errors,
    }


@frappe.whitelist()
def check_on_submit_hooks():
    """Check if on_submit hooks are configured for Sales Invoice"""

    # Get hooks.py content
    hooks_py = frappe.get_hooks()

    # Check doc_events
    doc_events = hooks_py.get("doc_events", {})
    sales_invoice_events = doc_events.get("Sales Invoice", {})

    results = {
        "sales_invoice_hooks": sales_invoice_events,
        "has_on_submit": "on_submit" in sales_invoice_events,
        "payment_entry_hooks": doc_events.get("Payment Entry", {}),
        "recommendation": "",
    }

    if not results["has_on_submit"]:
        results["recommendation"] = "Add on_submit hook for Sales Invoice to update payment history"

    return results
