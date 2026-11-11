"""A Mollie 404 for a payment id is acknowledged like a known id, loudly to staff (#1805).

The webhook is anonymous: Mollie posts a bare ``id=tr_...``. If an id Mollie does not know
answered 503 + ``Retry-After`` while a known one answers 200, any caller could probe which
``tr_`` ids exist. Maintainer ruling 2026-11-11: ONLY Mollie's ``NotFoundError`` (404) is
permanent and is answered exactly like a known id. Every other fetch failure (timeout, 5xx,
auth) keeps 503 + Retry-After, because that retry is what books a real payment after an outage.

Acking a 404 stops Mollie retrying, so a REAL id our key cannot ``get`` (rotated key, test/live
mode mismatch, wrong profile) would be dropped silently. Hence the Error Log row and staff alert
written here: once per caller IP per hour (never keyed on the id, which the caller chooses).
"""

import frappe
from frappe.utils import escape_html

from verenigingen.utils.security.client_ip import get_client_ip
from verenigingen.verenigingen_payments.utils.webhook_ack import log_error_once, short_id

ALERT_KEY = "mollie_payment_not_found"
ALERT_TITLE = "Mollie Webhook Payment Not Found"


def acknowledge_unknown_payment(payment_id: str) -> dict:
    """Record the 404 for staff and return the result a booked payment would carry.

    Never raises: it runs inside a webhook, where an exception would become a retry (and a
    different response than a known id gets).
    """
    try:
        _alert_staff_once(payment_id)
    except Exception:
        frappe.log_error(title=ALERT_TITLE + " (alert failed)", message=frappe.get_traceback())
    return {"status": "skipped", "message": "payment not found at Mollie", "payment_id": payment_id}


def _alert_staff_once(payment_id: str) -> None:
    details = (
        f"Mollie answered 404 for payment {short_id(payment_id)} on a webhook delivery. The webhook was "
        f"acknowledged, so Mollie will NOT retry it. If this is a real payment, the Mollie API key, its "
        f"test/live mode or the profile in Mollie Settings does not match the one that created it: fix "
        f"the setting and book the payment by hand. Otherwise someone is probing payment ids."
    )
    if not log_error_once(ALERT_TITLE, details, get_client_ip()):
        return
    from verenigingen.utils.notification_helpers import notify_administrators

    notify_administrators(
        subject="Mollie webhook for a payment id Mollie does not know",
        message=f"<p>{escape_html(details)}</p>",
        notification_key="mollie_payment_not_found",  # literal: key discovery greps for it
        exclude_users=["Administrator"],  # ruling 2026-11-01: staff alerts never go to Administrator
        staff_alert=True,
    )
