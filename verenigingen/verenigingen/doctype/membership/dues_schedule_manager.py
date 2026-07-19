import frappe

from verenigingen.utils.constants import PaymentStatus
from verenigingen.utils.member_utils import get_dues_schedule_for_membership_name


def sync_membership_with_dues_schedule(membership_doc):
    """
    Synchronize membership with Membership Dues Schedule
    - Update payment status based on dues schedule invoices
    - Track payment history
    """
    # Find dues schedule that links to this membership
    dues_schedule = get_dues_schedule_for_membership_name(membership_doc.name)
    if not dues_schedule:
        return

    member = frappe.get_doc("Member", membership_doc.member)

    if not member.customer:
        return

    # Get invoices linked to this member/customer
    invoices = frappe.get_all(
        "Sales Invoice",
        filters={
            "customer": member.customer,
            "docstatus": 1,
            "posting_date": [">=", membership_doc.start_date],
        },
        fields=["name", "status", "outstanding_amount", "posting_date"],
        order_by="posting_date desc",
    )

    if not invoices:
        return

    # Check latest invoice status
    if invoices:
        latest_invoice = invoices[0]

        # Update membership payment status based on invoice - modernized with constants
        if latest_invoice.status in PaymentStatus.PAID_STATUSES:
            membership_doc.last_payment_date = latest_invoice.posting_date
            membership_doc.unpaid_amount = 0
        elif latest_invoice.status == PaymentStatus.INVOICE_OVERDUE:
            membership_doc.unpaid_amount = latest_invoice.outstanding_amount
        elif latest_invoice.status == "Return":  # Keep specific return status as is
            membership_doc.unpaid_amount = 0
        else:
            membership_doc.unpaid_amount = latest_invoice.outstanding_amount or 0

    # Save membership document
    membership_doc.flags.ignore_validate_update_after_submit = True
    membership_doc.save()

    # Return information about linked invoices for display
    return invoices


def get_membership_payment_history(membership_doc):
    """
    Get payment history for a membership from linked dues schedule
    """
    # Find dues schedule that links to this membership
    dues_schedule = get_dues_schedule_for_membership_name(membership_doc.name)
    if not dues_schedule:
        return []

    # Get member customer
    member = frappe.get_doc("Member", membership_doc.member)
    if not member.customer:
        return []

    # Get invoices from member/customer
    invoices = frappe.get_all(
        "Sales Invoice",
        filters={
            "customer": member.customer,
            "docstatus": 1,
            "posting_date": [">=", membership_doc.start_date],
        },
        fields=["name", "status", "posting_date", "grand_total", "outstanding_amount"],
        order_by="posting_date desc",
    )

    payment_history = []

    for invoice_info in invoices:
        invoice = frappe.get_doc("Sales Invoice", invoice_info.name)

        # Get linked payments
        payments = frappe.get_all(
            "Payment Entry Reference", filters={"reference_name": invoice.name}, fields=["parent"]
        )

        payment_entries = []
        for payment in payments:
            payment_doc = frappe.get_doc("Payment Entry", payment.parent)
            payment_entries.append(
                {
                    "payment_entry": payment_doc.name,
                    "amount": payment_doc.paid_amount,
                    "date": payment_doc.posting_date,
                    "mode": payment_doc.mode_of_payment,
                    "status": payment_doc.status,
                }
            )

        payment_history.append(
            {
                "invoice": invoice.name,
                "date": invoice.posting_date,
                "amount": invoice.grand_total,
                "status": invoice.status,
                "payments": payment_entries,
            }
        )

    return payment_history
