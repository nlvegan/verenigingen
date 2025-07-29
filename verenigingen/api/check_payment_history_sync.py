"""
Check if payment history was updated for manually generated invoices
"""

import frappe
from frappe.utils import today

from verenigingen.utils.security.api_security_framework import OperationType, critical_api
from verenigingen.utils.security.audit_logging import log_sensitive_operation
from verenigingen.utils.security.authorization import require_role
from verenigingen.utils.security.csrf_protection import validate_csrf_token
from verenigingen.utils.security.rate_limiting import rate_limit


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
@rate_limit(calls=15, period=60)  # 15 calls per minute
@require_role(["Accounts Manager", "System Manager", "Verenigingen Administrator"])
@validate_csrf_token
def check_invoice_payment_history_sync():
    """Check if payment history was updated for today's generated invoices"""
    # Log this sensitive operation
    log_sensitive_operation(
        "payment_history", "check_invoice_payment_history_sync", {"requested_by": frappe.session.user}
    )

    today_date = today()

    # Get invoices generated today (from manual generation)
    todays_invoices = frappe.get_all(
        "Sales Invoice",
        filters={
            "posting_date": today_date,
            "docstatus": 1,  # Submitted
            "creation": [">=", f"{today_date} 07:20:00"],  # Around when manual generation ran
        },
        fields=["name", "customer", "customer_name", "grand_total", "creation", "remarks"],
        order_by="creation",
    )

    results = {
        "today_date": today_date,
        "total_invoices": len(todays_invoices),
        "invoices_checked": [],
        "payment_history_status": {},
        "summary": {},
    }

    members_with_invoices = []
    members_with_history = []
    members_without_history = []

    for invoice in todays_invoices[:10]:  # Check first 10 invoices
        # Get member from customer
        member_name = frappe.db.get_value("Member", {"customer": invoice.customer}, "name")

        if member_name:
            members_with_invoices.append(member_name)

            # Check if member has payment history entry for this invoice
            history_entry = frappe.db.exists(
                "Member Payment History", {"parent": member_name, "invoice_number": invoice.name}
            )

            if history_entry:
                members_with_history.append(member_name)
                history_status = "✅ Found"
            else:
                members_without_history.append(member_name)
                history_status = "❌ Missing"

            results["invoices_checked"].append(
                {
                    "invoice": invoice.name,
                    "customer": invoice.customer_name,
                    "member": member_name,
                    "amount": invoice.grand_total,
                    "payment_history": history_status,
                    "creation": invoice.creation,
                }
            )

    # Get overall statistics
    results["summary"] = {
        "invoices_with_members": len(members_with_invoices),
        "members_with_history": len(members_with_history),
        "members_without_history": len(members_without_history),
        "sync_rate": f"{len(members_with_history)}/{len(members_with_invoices)}"
        if members_with_invoices
        else "N/A",
    }

    results["payment_history_status"] = {
        "working": len(members_with_history) > 0,
        "needs_manual_sync": len(members_without_history) > 0,
        "missing_members": members_without_history[:5],  # First 5 missing
    }

    return results


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
@rate_limit(calls=5, period=300)  # 5 calls per 5 minutes
@require_role(["Accounts Manager", "System Manager"])
@validate_csrf_token
def manually_sync_payment_history_for_todays_invoices():
    """Manually trigger payment history sync for today's invoices"""
    # Log this sensitive operation
    log_sensitive_operation(
        "payment_history",
        "manually_sync_payment_history_for_todays_invoices",
        {"requested_by": frappe.session.user},
    )

    today_date = today()

    # Get invoices that might be missing payment history
    todays_invoices = frappe.get_all(
        "Sales Invoice",
        filters={"posting_date": today_date, "docstatus": 1, "creation": [">=", f"{today_date} 07:20:00"]},
        fields=["name", "customer"],
    )

    results = {"processed": 0, "synced": 0, "errors": [], "details": []}

    for invoice_data in todays_invoices:
        try:
            # Get the member
            member_name = frappe.db.get_value("Member", {"customer": invoice_data.customer}, "name")

            if member_name:
                # Check if history already exists
                existing = frappe.db.exists(
                    "Member Payment History", {"parent": member_name, "invoice_number": invoice_data.name}
                )

                if not existing:
                    # Manually trigger the event handler
                    try:
                        from verenigingen.events.invoice_events import emit_invoice_submitted

                        # Get the invoice document
                        invoice = frappe.get_doc("Sales Invoice", invoice_data.name)

                        # Trigger the event handler
                        emit_invoice_submitted(invoice)

                        results["synced"] += 1
                        results["details"].append(
                            {"invoice": invoice_data.name, "member": member_name, "status": "Synced"}
                        )

                    except Exception as e:
                        results["errors"].append(
                            {"invoice": invoice_data.name, "member": member_name, "error": str(e)}
                        )
                else:
                    results["details"].append(
                        {"invoice": invoice_data.name, "member": member_name, "status": "Already exists"}
                    )

            results["processed"] += 1

        except Exception as e:
            results["errors"].append({"invoice": invoice_data.name, "error": str(e)})

    return results
