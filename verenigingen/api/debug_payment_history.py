#!/usr/bin/env python3
"""
Debug Payment History Event Handler
"""

import frappe
from frappe.utils import nowdate, today


@frappe.whitelist()
def debug_payment_history_for_member(member_name):
    """Debug payment history updates for a specific member"""
    try:
        # Get member
        member = frappe.get_doc("Member", member_name)

        result = {
            "member_info": {
                "name": member.name,
                "full_name": member.full_name,
                "email": member.email,
                "customer": getattr(member, "customer", "No customer linked"),
            }
        }

        # Check today's invoices
        today_date = today()

        if hasattr(member, "customer") and member.customer:
            invoices = frappe.get_all(
                "Sales Invoice",
                filters={"customer": member.customer, "creation": [">=", today_date + " 00:00:00"]},
                fields=["name", "creation", "grand_total", "status", "due_date", "posting_date"],
                order_by="creation desc",
            )

            result["todays_invoices"] = {"count": len(invoices), "invoices": invoices}
        else:
            result["todays_invoices"] = {"count": 0, "error": "No customer linked to member"}

        # Check payment history
        payment_history = getattr(member, "payment_history", [])
        result["payment_history"] = {"count": len(payment_history), "recent_entries": []}

        if payment_history:
            # Get last 5 entries
            for entry in payment_history[-5:]:
                result["payment_history"]["recent_entries"].append(
                    {
                        "invoice": getattr(entry, "invoice", "N/A"),
                        "amount": getattr(entry, "amount", "N/A"),
                        "posting_date": str(getattr(entry, "posting_date", "N/A")),
                        "payment_date": str(getattr(entry, "payment_date", "N/A")),
                        "payment_status": getattr(entry, "payment_status", "N/A"),
                    }
                )

        # Check if there's a mismatch between invoices and payment history
        if hasattr(member, "customer") and member.customer:
            all_invoices = frappe.get_all(
                "Sales Invoice",
                filters={"customer": member.customer},
                fields=["name"],
                order_by="creation desc",
                limit=20,
            )

            payment_history_invoice_ids = (
                [getattr(entry, "invoice", "") for entry in payment_history] if payment_history else []
            )

            missing_in_history = []
            for inv in all_invoices:
                if inv.name not in payment_history_invoice_ids:
                    missing_in_history.append(inv.name)

            result["analysis"] = {
                "total_invoices_for_customer": len(all_invoices),
                "invoices_in_payment_history": len(payment_history_invoice_ids),
                "missing_in_payment_history": missing_in_history[:10],  # First 10
            }

        return result

    except Exception as e:
        frappe.log_error(f"Error debugging payment history: {str(e)}")
        return {"error": str(e)}


@frappe.whitelist()
def debug_payment_history_hooks():
    """Debug the payment history event handlers"""
    try:
        from verenigingen.hooks import payment_history_hooks

        result = {"hooks_defined": {}, "handler_functions": []}

        # Check what hooks are defined
        hooks_content = frappe.get_hooks()

        if "doc_events" in hooks_content:
            doc_events = hooks_content["doc_events"]
            if "Sales Invoice" in doc_events:
                result["hooks_defined"]["Sales Invoice"] = doc_events["Sales Invoice"]
            if "*" in doc_events:
                result["hooks_defined"]["All Documents"] = doc_events["*"]

        # Check if our payment history functions exist
        try:
            from verenigingen.utils.payment_history import sync_payment_history_on_invoice_save

            result["handler_functions"].append("sync_payment_history_on_invoice_save - EXISTS")
        except ImportError as e:
            result["handler_functions"].append(f"sync_payment_history_on_invoice_save - MISSING: {e}")

        try:
            from verenigingen.utils.payment_history import sync_payment_history_on_payment_save

            result["handler_functions"].append("sync_payment_history_on_payment_save - EXISTS")
        except ImportError as e:
            result["handler_functions"].append(f"sync_payment_history_on_payment_save - MISSING: {e}")

        return result

    except Exception as e:
        frappe.log_error(f"Error debugging payment history hooks: {str(e)}")
        return {"error": str(e)}


@frappe.whitelist()
def manually_update_payment_history(member_name):
    """Manually trigger payment history update for a member"""
    try:
        member = frappe.get_doc("Member", member_name)

        if not hasattr(member, "customer") or not member.customer:
            return {"error": "No customer linked to member"}

        # Get all invoices for this customer (including drafts)
        invoices = frappe.get_all(
            "Sales Invoice",
            filters={"customer": member.customer, "docstatus": ["!=", 2]},  # Exclude cancelled
            fields=["name", "posting_date", "grand_total", "outstanding_amount", "status"],
            order_by="posting_date desc",
        )

        # Clear existing payment history
        member.payment_history = []

        # Add all invoices to payment history
        for invoice in invoices:
            member.append(
                "payment_history",
                {
                    "invoice": invoice.name,
                    "posting_date": invoice.posting_date,
                    "amount": invoice.grand_total,
                    "outstanding_amount": invoice.outstanding_amount,
                    "payment_status": "Paid" if invoice.outstanding_amount == 0 else "Unpaid",
                },
            )

        # Save the member
        member.save()

        return {
            "success": True,
            "invoices_added": len(invoices),
            "message": f"Updated payment history with {len(invoices)} invoices",
        }

    except Exception as e:
        frappe.log_error(f"Error manually updating payment history: {str(e)}")
        return {"error": str(e)}
