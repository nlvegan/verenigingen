"""
Debug why payment history updates aren't working
"""

import frappe
from frappe import _
from frappe.utils import add_days, today

from verenigingen.utils.security.api_security_framework import OperationType, critical_api


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def debug_payment_history_system():
    """Comprehensive debug of payment history update system"""

    results = {
        "flags": {},
        "error_logs": [],
        "recent_invoices": [],
        "bulk_update_test": None,
        "event_system_test": None,
    }

    # Check current flags
    results["flags"] = {
        "bulk_invoice_generation": getattr(frappe.flags, "bulk_invoice_generation", None),
        "in_invoice_generation": getattr(frappe.flags, "in_invoice_generation", None),
    }

    # Check for error logs in last 24 hours
    errors = frappe.db.sql(
        """
        SELECT
            method,
            error,
            creation
        FROM `tabError Log`
        WHERE (
            method LIKE '%%payment_history%%'
            OR method LIKE '%%bulk_update%%'
            OR error LIKE '%%payment history%%'
            OR error LIKE '%%add_invoice_to_payment_history%%'
        )
        AND creation >= %s
        ORDER BY creation DESC
        LIMIT 20
    """,
        add_days(today(), -1),
        as_dict=True,
    )

    for error in errors:
        results["error_logs"].append(
            {
                "method": error.method or "Unknown",
                "error": (error.error or "")[:200],
                "time": str(error.creation),
            }
        )

    # Check recent invoices and their payment history status
    recent_invoices = frappe.db.sql(
        """
        SELECT
            si.name as invoice,
            si.customer,
            si.posting_date,
            si.creation,
            c.member,
            (SELECT COUNT(*)
             FROM `tabMember Payment History` mph
             WHERE mph.parent = c.member
             AND mph.invoice = si.name) as in_payment_history
        FROM `tabSales Invoice` si
        LEFT JOIN `tabCustomer` c ON si.customer = c.name
        WHERE si.docstatus = 1
        AND si.posting_date >= %s
        AND c.member IS NOT NULL
        ORDER BY si.creation DESC
        LIMIT 10
    """,
        add_days(today(), -2),
        as_dict=True,
    )

    results["recent_invoices"] = recent_invoices

    # Test bulk update function
    try:
        from vereinigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import (
            _bulk_update_payment_history,
        )

        # Test with empty data
        test_result = _bulk_update_payment_history(set(), [])
        results["bulk_update_test"] = {"exists": True, "test_result": test_result, "error": None}
    except Exception as e:
        results["bulk_update_test"] = {"exists": False, "error": str(e)}

    # Test event system
    try:
        from vereinigingen.events.invoice_events import _get_event_subscribers

        subscribers = _get_event_subscribers("invoice_submitted")
        results["event_system_test"] = {"subscribers_found": len(subscribers), "subscribers": subscribers}
    except Exception as e:
        results["event_system_test"] = {"error": str(e)}

    # Summary
    total_invoices = len(recent_invoices)
    in_history = sum(1 for inv in recent_invoices if inv.in_payment_history > 0)
    missing = total_invoices - in_history

    results["summary"] = {
        "total_recent_invoices": total_invoices,
        "in_payment_history": in_history,
        "missing_from_history": missing,
        "percentage_missing": f"{(missing / total_invoices * 100):.1f}%" if total_invoices > 0 else "N/A",
    }

    return results


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def test_single_invoice_update(invoice_name):
    """Test updating payment history for a single invoice"""

    try:
        # Get invoice details
        invoice = frappe.get_doc("Sales Invoice", invoice_name)

        if not invoice.customer:
            return {"error": "Invoice has no customer"}

        # Find member
        member_name = frappe.db.get_value("Customer", invoice.customer, "member")

        if not member_name:
            return {"error": f"No member linked to customer {invoice.customer}"}

        # Test the update
        member = frappe.get_doc("Member", member_name)

        # Check if method exists
        if not hasattr(member, "add_invoice_to_payment_history"):
            return {"error": "Member missing add_invoice_to_payment_history method"}

        # Try to add
        member.add_invoice_to_payment_history(invoice_name)

        # Check if it worked
        exists = frappe.db.exists("Member Payment History", {"parent": member_name, "invoice": invoice_name})

        return {
            "success": exists,
            "member": member_name,
            "invoice": invoice_name,
            "customer": invoice.customer,
        }

    except Exception as e:
        return {"error": str(e), "invoice": invoice_name}
