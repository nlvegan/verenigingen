# Copyright (c) 2026, Verenigingen
"""Gateway-agnostic finalization of a payment-plan installment payment.

Called from a payment gateway's webhook AT WEBHOOK TOP LEVEL (no enclosing
savepoint), because it commits/rolls back the request transaction. The
installment is marked Paid via PaymentPlan.process_payment ONLY here (never on
a member-triggered path), so a member cannot self-certify payment.
"""

import hashlib
import json

import frappe
from frappe.utils import today

# #1330: failed finalization attempts for ONE gateway payment id before finance staff are alerted.
# Mollie's and Pay.nl's retry counts are not established here, so this is kept low.
PE_FAILURE_ALERT_THRESHOLD = 3

ATTEMPT_LOG_TITLE = "Payment Plan Payment Webhook"
ALERT_LOG_TITLE = "Payment Plan Payment Repeated Failure"
ALERT_NOTIFICATION_KEY = "payment_alert_failure"


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
                title="Payment Plan Payment Double Payment",
                message=f"Duplicate payment-plan installment payment: intent {intent_name} for installment "
                f"{row.installment_number} of {row.payment_plan}, which is already Paid. A real "
                f"payment ({payment_reference}) was taken -> MANUAL REFUND REVIEW NEEDED.",
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
        # Security: webhook context; finalization runs as the configured webhook user.
        #
        # It needs the HIGH tier, NOT "the FINANCIAL tier" as this comment used to
        # claim. @high_security_api hardcodes security_level=SecurityLevel.HIGH
        # (api_security_framework.py, high_security_api -> api_security_framework);
        # its operation_type argument -- FINANCIAL here -- is a rate-limiting
        # classification and is never mapped to a required tier. Granting the service
        # account CRITICAL on the strength of the old wording would have been a real
        # privilege escalation. The Verenigingen Webhook User role profile already
        # grants HIGH.
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
            title=ATTEMPT_LOG_TITLE,
            message=f"Payment plan payment finalize failed for intent {intent_name}: {e}\n"
            f"Gateway payment id: {_payment_id_display(payment_reference)}\n"
            f"{_payment_id_line(payment_reference)}",
        )
        if status == "paid":
            _alert_after_repeated_failure(intent_name, payment_reference, str(e))
        return {"status": "error", "message": str(e)}


def _payment_id_line(payment_reference):
    """The LAST-LINE key of a counted Error Log row: a hash, so a gateway-supplied id holding
    newlines, control characters or LIKE wildcards can neither forge another id's line nor break
    the match. The readable id (JSON-escaped to ONE line) is logged by `_payment_id_display`."""
    digest = hashlib.sha256(str(payment_reference).encode("utf-8", "replace")).hexdigest()[:32]
    return f"Gateway payment id key: {digest}"


def _payment_id_display(payment_reference):
    """The id as ONE printable line (quotes and control characters escaped): safe in a log row and
    in a mail subject."""
    return json.dumps(str(payment_reference))


def _error_log_lines(title, payment_reference, from_end):
    """Error Log rows of `title` for this gateway payment id: the key line must be the exact
    `from_end`-th line from the END of the row (1 = last)."""
    line = _payment_id_line(payment_reference)
    rows = frappe.get_all(
        "Error Log",
        filters={"method": title, "error": ["like", f"%{line}%"]},
        fields=["error"],
    )
    # Text before the key lines (the cause) can echo attacker input, so only the tail counts.
    return [
        r for r in rows if len(r.error.splitlines()) >= from_end and r.error.splitlines()[-from_end] == line
    ]


def _alert_after_repeated_failure(intent_name, payment_reference, cause):
    """#1330: tell finance staff, once, when ONE gateway payment id has failed
    PE_FAILURE_ALERT_THRESHOLD times.

    The attempts are counted from the Error Log rows the failure path writes above. tabError Log
    is MyISAM (non-transactional), so those rows survive the rollback that every failed attempt
    causes; a counter in a document row or the transaction would not. It needs no schema change
    and no cache key (which could expire mid-retry). Deleting the rows resets the count.

    Delivery is retried on a later attempt while no alert has reached anyone (no recipient, key
    disabled); once one has, the Error Log row marks it delivered and the rest stay silent.
    Never raises: the caller answers the gateway with an error either way so it retries.
    """
    try:
        if (
            len(_error_log_lines(ATTEMPT_LOG_TITLE, payment_reference, from_end=1))
            < PE_FAILURE_ALERT_THRESHOLD
        ):
            return
        alerts = _error_log_lines(ALERT_LOG_TITLE, payment_reference, from_end=2)
        if any(r.error.splitlines()[-1] == "Mail delivered: yes" for r in alerts):
            return
        delivered = _send_failure_alert(intent_name, payment_reference, cause)
        frappe.log_error(
            title=ALERT_LOG_TITLE,
            message=f"Payment {_payment_id_display(payment_reference)} (intent {intent_name}) has failed "
            f"{PE_FAILURE_ALERT_THRESHOLD} or more times: {cause}\n"
            f"{_payment_id_line(payment_reference)}\nMail delivered: {'yes' if delivered else 'no'}",
        )
        frappe.db.commit()
    except Exception as alert_error:
        frappe.log_error(
            title=f"{ALERT_LOG_TITLE} Alert Failed",
            message=f"Payment {_payment_id_display(payment_reference)}: the alert could not be sent ({alert_error}). Cause: {cause}",
        )


def _send_failure_alert(intent_name, payment_reference, cause):
    from frappe.utils import escape_html

    from verenigingen.services.communication.email_service import get_email_service
    from verenigingen.utils.constants import Roles
    from verenigingen.verenigingen_payments.api.sepa_batch_notifications import get_financial_admin_emails

    recipients = get_financial_admin_emails(ALERT_NOTIFICATION_KEY, default_roles=[Roles.FINANCIAL_MANAGER])
    if not recipients:
        return False
    result = get_email_service().send_simple_email(
        recipients=recipients,
        subject=f"URGENT: payment {_payment_id_display(payment_reference)} is paid but its installment could not be booked",
        message=(
            f"<p>Gateway payment <strong>{escape_html(_payment_id_display(payment_reference))}</strong> (payment plan intent "
            f"{escape_html(intent_name)}) has failed to book {PE_FAILURE_ALERT_THRESHOLD} times. The member "
            f"has paid; the installment is still Pending and no Payment Entry exists.</p>"
            f"<p><strong>Cause:</strong></p><pre>{escape_html(cause)}</pre>"
            f"<p>The gateway keeps retrying until it gives up. Fix the cause (for example the company's "
            f"default accounts) or book the payment by hand.</p>"
        ),
        notification_key=ALERT_NOTIFICATION_KEY,
        cooldown_scope=_payment_id_line(payment_reference).rsplit(" ", 1)[
            -1
        ],  # per payment: one payment's alert must not silence another's
    )
    return bool(result.success and not result.skip_reason)
