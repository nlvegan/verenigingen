# Copyright (c) 2026, Verenigingen
"""Finalize a payment-plan installment payment from a confirmed Mollie webhook.

Invoked from the unified webhook dispatch when a Mollie payment's metadata
reference_doctype is "Payment Plan Payment". The installment is marked Paid via
the existing PaymentPlan.process_payment ONLY here (never on a member-triggered
path), so a member cannot self-certify payment.
"""

import frappe
from frappe.utils import today


def _payment_status(payment) -> str:
    if isinstance(payment, dict):
        return payment.get("status") or ""
    return getattr(payment, "status", "") or ""


def _metadata(payment) -> dict:
    if isinstance(payment, dict):
        md = payment.get("metadata")
    else:
        md = getattr(payment, "metadata", None)
    return md if isinstance(md, dict) else {}


def handle_payment_plan_payment(payment_id: str, payment) -> dict:
    """Idempotently finalize the installment for a Payment Plan Payment intent."""
    intent_name = _metadata(payment).get("reference_docname")
    if not intent_name or not frappe.db.exists("Payment Plan Payment", intent_name):
        # Nothing we can do; do not 500 (Mollie would retry forever).
        return {"status": "error", "message": f"intent {intent_name} not found"}

    status = _payment_status(payment)

    try:
        # Serialize concurrent duplicate deliveries on this intent.
        frappe.db.sql("SELECT name FROM `tabPayment Plan Payment` WHERE name=%s FOR UPDATE", intent_name)
        intent = frappe.get_doc("Payment Plan Payment", intent_name)

        # Idempotency guard: already finalized -> success no-op (never reach
        # process_payment, which throws on an already-Paid installment).
        if intent.status == "Paid":
            frappe.db.commit()
            return {"status": "skipped", "message": "already processed"}

        if status != "paid":
            # failed / expired / open -> record and leave installment payable.
            new_status = {"failed": "Failed", "expired": "Expired", "canceled": "Failed"}.get(
                status, intent.status
            )
            intent.db_set("status", new_status)
            frappe.db.commit()
            return {"status": "skipped", "message": f"payment status {status}"}

        # Confirmed paid: finalize the installment FIRST, mark intent Paid only
        # after it returns (so a mid-finalize failure leaves the intent
        # re-processable rather than a Paid intent with an unfinalized installment).
        # Security: webhook context; finalization runs as the webhook user.
        plan = frappe.get_doc("Payment Plan", intent.payment_plan)
        plan.process_payment(
            installment_number=intent.installment_number,
            payment_amount=intent.amount,
            payment_reference=payment_id,
            payment_date=today(),
        )
        intent.db_set("status", "Paid")
        intent.db_set("paid", 1)
        if not intent.payment_id:
            intent.db_set("payment_id", payment_id)
        frappe.db.commit()
        return {"status": "success", "intent": intent_name}

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(
            f"Payment plan payment finalize failed for intent {intent_name}: {e}",
            "Payment Plan Payment Webhook",
        )
        # Return error (not raise) so the caller decides the HTTP code; a 500 here
        # would trigger Mollie retries, which is acceptable since we rolled back.
        return {"status": "error", "message": str(e)}
