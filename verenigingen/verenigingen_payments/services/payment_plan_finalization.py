# Copyright (c) 2026, Verenigingen
"""Gateway-agnostic finalization of a payment-plan installment payment.

Called from a payment gateway's webhook AT WEBHOOK TOP LEVEL (no enclosing
savepoint), because it commits/rolls back the request transaction. The
installment is marked Paid via PaymentPlan.process_payment ONLY here (never on
a member-triggered path), so a member cannot self-certify payment.
"""

import frappe
from frappe.utils import today


def finalize_payment_plan_installment(intent_name: str, payment_reference: str, status: str = "paid") -> dict:
    """Idempotently finalize the installment for a Payment Plan Payment intent.

    status: the gateway-neutral payment status ("paid" finalizes; "failed"/
    "expired" record and leave the installment payable; anything else is
    treated the same as an unrecognized non-paid status).
    """
    try:
        # Lock the intent row and read the fields we act on FROM THE LOCKED ROW
        # (CLAUDE.md Pattern 5). A separate plain ORM read could return a stale
        # pre-lock snapshot under REPEATABLE READ and let a concurrent duplicate
        # delivery slip past the idempotency guard into process_payment.
        locked = frappe.db.sql(
            """SELECT name, status, payment_plan, installment_number, amount, payment_id
               FROM `tabPayment Plan Payment` WHERE name=%s FOR UPDATE""",
            intent_name,
            as_dict=True,
        )
        if not locked:
            # Intent not found. Return an error (HTTP 500) so the gateway retries:
            # the webhook can legitimately arrive before the initiating request has
            # committed the intent. Gateway retry schedules are bounded, so a truly
            # orphaned payment stops retrying on its own.
            frappe.db.commit()
            return {"status": "error", "message": f"intent {intent_name} not found"}
        row = locked[0]

        # Idempotency guard on the LOCKED status: already finalized -> no-op
        # (never reach process_payment, which throws on an already-Paid installment).
        if row.status == "Paid":
            frappe.db.commit()
            return {"status": "skipped", "message": "already processed"}

        if status != "paid":
            # failed / expired / open -> record and leave the installment payable.
            new_status = {"failed": "Failed", "expired": "Expired", "canceled": "Failed"}.get(
                status, row.status
            )
            frappe.db.set_value("Payment Plan Payment", intent_name, "status", new_status)
            frappe.db.commit()
            return {"status": "skipped", "message": f"payment status {status}"}

        # Guard against a SECOND intent for the SAME installment (e.g. the member
        # opened the pay page twice and both gateway payments succeeded). The
        # installment is already Paid via the other intent; calling process_payment
        # would throw "already paid" -> error -> HTTP 500 -> gateway retries forever,
        # and the duplicate (real) charge would go unnoticed. Stop the loop, flag the
        # duplicate charge for manual refund, and mark THIS intent Paid so it is not
        # reprocessed.
        installment_status = frappe.db.get_value(
            "Payment Plan Installment",
            {"parent": row.payment_plan, "installment_number": row.installment_number},
            "status",
        )
        if installment_status == "Paid":
            frappe.log_error(
                f"Duplicate payment-plan installment payment: intent {intent_name} for installment "
                f"{row.installment_number} of {row.payment_plan}, which is already Paid. A real "
                f"payment ({payment_reference}) was taken -> MANUAL REFUND REVIEW NEEDED.",
                "Payment Plan Payment Double Payment",
            )
            frappe.db.set_value(
                "Payment Plan Payment",
                intent_name,
                {"status": "Paid", "paid": 1, "payment_id": row.payment_id or payment_reference},
            )
            frappe.db.commit()
            return {"status": "skipped", "message": "installment already paid"}

        # Confirmed paid: finalize the installment FIRST, mark the intent Paid only
        # AFTER it returns (a mid-finalize failure must leave the intent
        # re-processable, not a Paid intent with an unfinalized installment).
        # Security: webhook context; finalization runs as the webhook user (defaults
        # to Administrator; a restricted webhook_user must hold the FINANCIAL tier,
        # since PaymentPlan.process_payment is decorated @high_security_api(FINANCIAL)).
        plan = frappe.get_doc("Payment Plan", row.payment_plan)
        plan.process_payment(
            installment_number=row.installment_number,
            payment_amount=row.amount,
            payment_reference=payment_reference,
            payment_date=today(),
        )
        frappe.db.set_value(
            "Payment Plan Payment",
            intent_name,
            {"status": "Paid", "paid": 1, "payment_id": row.payment_id or payment_reference},
        )
        frappe.db.commit()
        return {"status": "success", "intent": intent_name}

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(
            f"Payment plan payment finalize failed for intent {intent_name}: {e}",
            "Payment Plan Payment Webhook",
        )
        return {"status": "error", "message": str(e)}
