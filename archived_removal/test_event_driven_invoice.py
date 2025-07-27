"""
Quick test to verify event-driven invoice submission works
"""

import frappe
from frappe.utils import add_days, today


@frappe.whitelist()
def test_invoice_submission_with_events():
    """Test that invoice submission works with the new event-driven system"""
    try:
        # Find a member with a customer
        member = frappe.get_all(
            "Member", filters={"customer": ["!=", ""]}, fields=["name", "customer", "full_name"], limit=1
        )

        if not member:
            return {"status": "error", "message": "No member with customer found"}

        member = member[0]

        # Create a test invoice
        invoice = frappe.new_doc("Sales Invoice")
        invoice.customer = member.customer
        invoice.posting_date = today()
        invoice.due_date = add_days(today(), 30)  # Proper future due date

        # Add invoice item
        invoice.append(
            "items",
            {
                "item_code": "Membership Dues - Daily",
                "qty": 1,
                "rate": 5.0,
                "description": f"Event-driven test for {member.full_name}",
            },
        )

        # Insert the invoice
        invoice.insert()
        invoice_name = invoice.name

        # The critical test: submit the invoice
        # With the old system, this could fail due to payment history validation
        # With the new event-driven system, this should always succeed
        invoice.submit()

        # Check if any background jobs were queued
        recent_jobs = frappe.get_all(
            "RQ Job",
            filters={
                "job_name": ["like", f"%invoice_submitted%{invoice_name}%"],
                "creation": [">", frappe.utils.add_to_date(frappe.utils.now(), minutes=-1)],
            },
            fields=["name", "job_name", "status"],
            limit=5,
        )

        return {
            "status": "success",
            "message": "Invoice submitted successfully with event-driven system",
            "invoice": invoice_name,
            "invoice_status": invoice.docstatus,
            "member": member.name,
            "background_jobs_queued": len(recent_jobs),
            "jobs": recent_jobs,
        }

    except Exception as e:
        frappe.db.rollback()
        return {
            "status": "error",
            "message": f"Invoice submission failed: {str(e)}",
            "error_type": type(e).__name__,
        }


@frappe.whitelist()
def check_payment_history_sync_status(member_name):
    """Check if a member's payment history has been synced"""
    try:
        member = frappe.get_doc("Member", member_name)

        payment_history_count = len(member.payment_history) if hasattr(member, "payment_history") else 0

        # Get recent invoices for this member
        recent_invoices = []
        if member.customer:
            recent_invoices = frappe.get_all(
                "Sales Invoice",
                filters={
                    "customer": member.customer,
                    "docstatus": 1,
                    "posting_date": [">=", frappe.utils.add_days(today(), -7)],
                },
                fields=["name", "posting_date", "grand_total", "status"],
                order_by="posting_date desc",
                limit=5,
            )

        # Check which invoices are in payment history
        invoices_in_history = []
        if hasattr(member, "payment_history"):
            for payment in member.payment_history:
                if hasattr(payment, "invoice") and payment.invoice:
                    invoices_in_history.append(payment.invoice)

        return {
            "status": "success",
            "member": member_name,
            "payment_history_count": payment_history_count,
            "recent_invoices": recent_invoices,
            "invoices_in_history": invoices_in_history,
            "sync_status": "synced" if payment_history_count > 0 else "not_synced",
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}
