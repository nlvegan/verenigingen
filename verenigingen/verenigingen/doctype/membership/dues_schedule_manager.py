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

    payments_by_invoice = _get_payment_entries_by_invoice([invoice_info.name for invoice_info in invoices])

    payment_history = []

    for invoice_info in invoices:
        payment_history.append(
            {
                "invoice": invoice_info.name,
                "date": invoice_info.posting_date,
                "amount": invoice_info.grand_total,
                "status": invoice_info.status,
                "payments": payments_by_invoice.get(invoice_info.name, []),
            }
        )

    return payment_history


def _get_payment_entries_by_invoice(invoice_names):
    """Map invoice name -> list of its Payment Entry summaries, in two queries.

    Replaces a per-invoice reference lookup plus a per-reference
    frappe.get_doc("Payment Entry") (#1166). Reads bypass permissions, exactly as
    the get_doc/get_all calls it replaces did.
    """
    if not invoice_names:
        return {}

    references = frappe.get_all(
        "Payment Entry Reference",
        filters={"reference_name": ["in", invoice_names]},
        fields=["parent", "reference_name"],
    )
    payment_entries = {
        pe.name: pe
        for pe in frappe.get_all(
            "Payment Entry",
            filters={"name": ["in", list({ref.parent for ref in references})]},
            fields=["name", "paid_amount", "posting_date", "mode_of_payment", "status"],
        )
    }

    payments_by_invoice = {}
    for ref in references:
        pe = payment_entries[ref.parent]
        payments_by_invoice.setdefault(ref.reference_name, []).append(
            {
                "payment_entry": pe.name,
                "amount": pe.paid_amount,
                "date": pe.posting_date,
                "mode": pe.mode_of_payment,
                "status": pe.status,
            }
        )
    return payments_by_invoice
