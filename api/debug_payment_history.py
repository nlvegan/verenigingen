"""
Debug payment history issues for newly generated invoices
"""

import frappe
from frappe import _
from frappe.utils import getdate, today

from verenigingen.utils.security.api_security_framework import OperationType, critical_api


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def check_member_payment_history(member_name):
    """Check payment history for a specific member"""

    member = frappe.get_doc("Member", member_name)

    results = {
        "member": member_name,
        "customer": member.customer,
        "payment_history_count": len(member.payment_history) if hasattr(member, "payment_history") else 0,
        "recent_invoices": [],
        "today_invoices": [],
        "errors": [],
    }

    # Get today's date
    today_date = today()

    # Check payment history entries
    if hasattr(member, "payment_history") and member.payment_history:
        for entry in member.payment_history[:10]:  # Last 10 entries
            results["recent_invoices"].append(
                {
                    "invoice": entry.invoice,
                    "date": str(entry.date),
                    "amount": entry.amount,
                    "status": entry.status,
                }
            )

    # Check for invoices created today
    if member.customer:
        today_invoices = frappe.get_all(
            "Sales Invoice",
            filters={"customer": member.customer, "posting_date": today_date, "docstatus": 1},
            fields=["name", "grand_total", "status", "creation"],
        )

        for inv in today_invoices:
            results["today_invoices"].append(
                {
                    "invoice": inv.name,
                    "amount": inv.grand_total,
                    "status": inv.status,
                    "created_at": str(inv.creation),
                    "in_payment_history": any(e.invoice == inv.name for e in member.payment_history)
                    if hasattr(member, "payment_history")
                    else False,
                }
            )

    # Check latest dues schedule
    schedules = frappe.get_all(
        "Membership Dues Schedule",
        filters={"member": member_name, "status": "Active"},
        fields=["name", "last_invoice_date", "next_invoice_date"],
    )

    results["active_schedules"] = schedules

    return results


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def debug_bulk_update_function():
    """Check if the bulk update function is being called correctly"""

    # Check for recent error logs
    errors = frappe.get_all(
        "Error Log",
        filters={
            "method": ["like", "%payment_history%"],
            "creation": [">=", frappe.utils.add_days(today(), -1)],
        },
        fields=["method", "error", "creation"],
        order_by="creation desc",
        limit=10,
    )

    results = {"recent_errors": [], "bulk_update_test": None}

    for error in errors:
        results["recent_errors"].append(
            {
                "method": error.method,
                "error": error.error[:200] if error.error else "",
                "time": str(error.creation),
            }
        )

    # Try to test the bulk update function
    try:
        from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import (
            _bulk_update_payment_history,
        )

        # Test with empty sets
        test_result = _bulk_update_payment_history(set(), [])
        results["bulk_update_test"] = {"success": True, "result": test_result}
    except Exception as e:
        results["bulk_update_test"] = {"success": False, "error": str(e)}

    return results


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def manually_update_payment_history(member_name):
    """Manually trigger payment history update for a member"""

    try:
        member = frappe.get_doc("Member", member_name)

        # Get today's invoices
        today_invoices = []
        if member.customer:
            today_invoices = frappe.get_all(
                "Sales Invoice",
                filters={"customer": member.customer, "posting_date": today(), "docstatus": 1},
                pluck="name",
            )

        results = {
            "member": member_name,
            "invoices_to_add": today_invoices,
            "before_count": len(member.payment_history) if hasattr(member, "payment_history") else 0,
            "added": [],
        }

        # Try to add each invoice
        for invoice in today_invoices:
            try:
                member.add_invoice_to_payment_history(invoice)
                results["added"].append(invoice)
            except Exception as e:
                results["errors"] = results.get("errors", [])
                results["errors"].append({"invoice": invoice, "error": str(e)})

        # Reload to check
        member.reload()
        results["after_count"] = len(member.payment_history) if hasattr(member, "payment_history") else 0

        return results

    except Exception as e:
        return {"error": str(e), "member": member_name}
