"""
Utilities for tracking dues-related invoices
Uses the existing Member Payment History infrastructure
"""

import frappe
from frappe.utils import getdate, today


def get_dues_invoices_for_member(member_name, schedule_name=None):
    """
    Get all dues-related invoices for a member
    Leverages the existing Member Payment History table
    """

    # The Member Payment History is automatically populated
    # We can query it directly or via the member document
    member = frappe.get_doc("Member", member_name)

    dues_invoices = []

    if hasattr(member, "payment_history"):
        for payment in member.payment_history:
            # Check if this is a dues-related invoice
            if payment.transaction_type == "Membership" or (
                payment.invoice and "dues" in (payment.notes or "").lower()
            ):
                # If schedule_name provided, filter by it
                if schedule_name:
                    invoice_doc = frappe.get_doc("Sales Invoice", payment.invoice)
                    if schedule_name in (invoice_doc.remarks or ""):
                        dues_invoices.append(payment)
                else:
                    dues_invoices.append(payment)

    return dues_invoices


def get_pending_dues_for_schedule(schedule_name):
    """
    Get pending invoices for a specific dues schedule
    """

    schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)
    member = frappe.get_doc("Member", schedule.member)

    pending = []

    # Check payment history for unpaid dues
    if hasattr(member, "payment_history"):
        for payment in member.payment_history:
            if payment.payment_status in ["Unpaid", "Overdue", "Partially Paid"]:
                # Check if related to this schedule
                if payment.invoice:
                    invoice = frappe.get_doc("Sales Invoice", payment.invoice)
                    if schedule_name in (invoice.remarks or ""):
                        pending.append(
                            {
                                "invoice": payment.invoice,
                                "amount": payment.amount,
                                "due_date": payment.due_date,
                                "status": payment.payment_status,
                                "outstanding": payment.outstanding_amount,
                            }
                        )

    return pending


@frappe.whitelist()
def get_dues_summary_for_member(member_name):
    """
    Get a comprehensive dues summary for a member
    """

    summary = {
        "member": member_name,
        "active_schedules": [],
        "total_paid_ytd": 0,
        "total_pending": 0,
        "next_due_date": None,
        "payment_history": [],
    }

    # Get active schedules
    schedules = frappe.get_all(
        "Membership Dues Schedule",
        filters={"member": member_name, "status": "Active"},
        fields=["name", "billing_frequency", "dues_rate", "next_invoice_date"],
    )

    summary["active_schedules"] = schedules

    # Get next due date
    if schedules:
        next_dates = [s["next_invoice_date"] for s in schedules if s["next_invoice_date"]]
        if next_dates:
            summary["next_due_date"] = min(next_dates)

    # Get payment history from member
    member = frappe.get_doc("Member", member_name)

    if hasattr(member, "payment_history"):
        for payment in member.payment_history:
            # Only include membership-related payments
            if payment.transaction_type == "Membership":
                summary["payment_history"].append(
                    {
                        "invoice": payment.invoice,
                        "date": payment.posting_date,
                        "amount": payment.amount,
                        "status": payment.payment_status,
                        "paid_amount": payment.paid_amount or 0,
                    }
                )

                # Calculate totals with enhanced error handling
                # Follows direct_debit_batch.py patterns for financial calculations
                if (
                    payment.payment_status == "Paid"
                    and getdate(payment.posting_date).year == getdate(today()).year
                ):
                    try:
                        paid_amount = payment.paid_amount
                        if paid_amount is None:
                            # Same as SQL COALESCE(paid_amount, 0)
                            paid_amount = 0.0
                        elif isinstance(paid_amount, str):
                            # Handle string amounts gracefully
                            paid_amount = float(paid_amount) if paid_amount.strip() else 0.0
                        else:
                            paid_amount = float(paid_amount)

                        summary["total_paid_ytd"] += round(paid_amount, 2)

                    except (ValueError, TypeError, AttributeError):
                        # Handle conversion errors gracefully
                        continue

                if payment.payment_status in ["Unpaid", "Overdue"]:
                    try:
                        outstanding_amount = payment.outstanding_amount
                        if outstanding_amount is None:
                            # Same as SQL COALESCE(outstanding_amount, 0)
                            outstanding_amount = 0.0
                        elif isinstance(outstanding_amount, str):
                            # Handle string amounts gracefully
                            outstanding_amount = (
                                float(outstanding_amount) if outstanding_amount.strip() else 0.0
                            )
                        else:
                            outstanding_amount = float(outstanding_amount)

                        summary["total_pending"] += round(outstanding_amount, 2)

                    except (ValueError, TypeError, AttributeError):
                        # Handle conversion errors gracefully
                        continue

    return summary
