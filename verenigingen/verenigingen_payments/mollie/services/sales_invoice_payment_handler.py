# Copyright (c) 2026, Verenigingen
"""Book a confirmed Mollie payment for a member's Sales Invoice (#2244).

Invoked from the unified webhook dispatch when a Mollie payment's metadata ``reference_doctype``
is "Sales Invoice" (what ``mollie_checkout.make_payment`` sends). The payment carries no customer
or subscription id, so the dues classifier cannot attribute it: the invoice named in the metadata
is the attribution. It is trusted only after the stored ``Sales Invoice.payment_id`` matches the
payment's own id, because the metadata is ours but the invoice may since have been given a newer
payment (a stale one is cancelled at checkout, and may still have been paid).

Booking is the #1803 dues path: a Payment Entry allocated to the invoice, idempotent per payment
id, with the #2406 refusal for a Payment Entry staff cancelled.

Anything that cannot be booked (no such invoice, not a member invoice, a payment that is not the
invoice's current one) is NOT raised: the webhook is acknowledged so Mollie stops retrying, and
staff get an Error Log row plus a registered alert (once per payment) to book it by hand.
"""

import frappe
from frappe.utils import escape_html, flt

ALERT_KEY = "mollie_invoice_payment_unbookable"
ALERT_TITLE = "Mollie Invoice Payment Not Booked"


def _read(payment, field):
    if isinstance(payment, dict):
        return payment.get(field)
    return getattr(payment, field, None)


def handle_sales_invoice_payment(payment_id: str, payment) -> dict:
    """Book a paid Mollie payment against the Sales Invoice its metadata names."""
    status = _read(payment, "status")
    if status != "paid":
        return {"status": "skipped", "message": f"payment status is '{status}', nothing to book"}

    metadata = _read(payment, "metadata")
    invoice_name = metadata.get("reference_docname") if isinstance(metadata, dict) else None
    reason = _unbookable_reason(payment_id, invoice_name)
    if reason:
        _report_unbookable(payment_id, invoice_name, payment, reason)
        return {"status": "skipped", "message": "not booked; staff alerted", "payment_id": payment_id}

    member = frappe.db.get_value("Sales Invoice", invoice_name, "member")
    from .dues_payment_processor import DuesPaymentProcessor

    return DuesPaymentProcessor().process_dues_payment(
        payment_id, payment=payment, invoice_name=invoice_name, member_name=member
    )


def _unbookable_reason(payment_id, invoice_name):
    """Why this payment cannot be booked to its invoice, or None when it can."""
    if not invoice_name or not frappe.db.exists("Sales Invoice", invoice_name):
        return "the invoice named in the payment does not exist"
    invoice = frappe.db.get_value(
        "Sales Invoice", invoice_name, ["member", "payment_id", "docstatus"], as_dict=True
    )
    if invoice.docstatus != 1:
        return "the invoice is not submitted (cancelled or draft)"
    if not invoice.member:
        return "the invoice is not linked to a Member"
    if invoice.payment_id != payment_id:
        return f"it is not the invoice's current payment (the invoice holds {invoice.payment_id or 'none'})"
    return None


def _report_unbookable(payment_id, invoice_name, payment, reason):
    amount = _read(payment, "amount")
    amount_text = (
        f"{amount.get('currency')} {flt(amount.get('value')):,.2f}"
        if isinstance(amount, dict)
        else "an unknown amount"
    )
    details = (
        f"Mollie payment {payment_id} ({amount_text}) for invoice {invoice_name or '(none)'} was paid but "
        f"NOT booked: {reason}. Mollie was acknowledged and will not retry. Action required: book it by "
        f"hand, or refund it at Mollie."
    )
    frappe.log_error(title=ALERT_TITLE, message=details)
    delivered = frappe.db.exists(
        "Staff Alert Event",
        {"notification_key": ALERT_KEY, "reference_name": payment_id, "delivered_at": ["is", "set"]},
    )
    if delivered:
        return
    from verenigingen.utils.notification_helpers import notify_administrators

    try:
        notify_administrators(
            subject=f"Mollie payment {payment_id} for an invoice could not be booked",
            message=f"<p>{escape_html(details)}</p>",
            notification_key="mollie_invoice_payment_unbookable",  # literal: key discovery greps for it
            event_reference=payment_id,
            exclude_users=["Administrator"],  # ruling 2026-11-01: staff alerts never go to Administrator
            staff_alert=True,
        )
    except Exception as exc:
        frappe.log_error(
            title=f"{ALERT_TITLE} (alert failed)",
            message=f"Payment {payment_id}: the staff alert could not be sent ({exc}). {details}",
        )
