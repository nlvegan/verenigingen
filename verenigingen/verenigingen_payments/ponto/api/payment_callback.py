# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Ponto Payment Callback Handler

Handles redirects from Ponto after payment signing.

When a user signs a payment in the Ponto authorization portal,
they are redirected back to this callback URL. This endpoint:
1. Validates the payment request
2. Refreshes the payment status from Ponto API
3. Redirects to appropriate success/failure page

Usage:
    Default callback URL:
    https://your-site.com/api/method/verenigingen.verenigingen_payments.ponto.api.payment_callback?payment_request=PONTO-PAY-0001

    Custom redirect_uri can be set per payment request.
"""

from urllib.parse import quote

import frappe
from frappe.utils import get_url

from verenigingen.utils.security.api_security_framework import public_api
from verenigingen.utils.security.guest_return_tokens import verify_guest_return_token
from verenigingen.utils.security.types import OperationType
from verenigingen.utils.service_user import get_service_user

# Scopes the signed `cancel_token` minted into the redirect_uri at signing start
# (PontoPaymentRequest.create_ponto_payment). A different purpose string from the #1055
# payment-success token, so neither verifies as the other.
CANCEL_TOKEN_PURPOSE = "ponto_payment_request_cancel"


@frappe.whitelist(allow_guest=True, methods=["GET"])
@public_api(operation_type=OperationType.PUBLIC)
def payment_callback():
    """
    Handle redirect from Ponto after payment signing.

    Query Parameters:
        payment_request: Name of the Ponto Payment Request document
        error: `access_denied` cancels a Pending request ONLY with a valid `cancel_token`
            (minted into the redirect_uri at signing start); any other error, or a missing
            or invalid token, is ignored (#1815)
        error_description: ignored
        cancel_token: signed proof that this browser was sent to Ponto for this request

    Returns:
        Redirect to appropriate page based on result

    Note:
        Rate limiting is handled by COR 'payment_callback'
        with per-IP scope: 20 requests per 5 minutes.
    """
    # Set webhook user context for permission-based operations
    webhook_user = get_service_user(
        settings_doctype="Verenigingen Payments Settings",
        user_field="webhook_user",
        service_name="Ponto Payment Callback",
    )
    if webhook_user:
        frappe.set_user(webhook_user)

    payment_request_name = frappe.request.args.get("payment_request")

    if not payment_request_name:
        frappe.logger().warning("Payment callback received without payment_request")
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = get_url("/desk")
        return

    # The query string is attacker-controlled (this is an allow_guest GET), so no status comes
    # from it (#1815), with ONE ruled exception: `error=access_denied` plus a valid
    # `cancel_token` (HMAC of this request's name, minted when signing started) marks a
    # Pending request Cancelled. Everything else asks Ponto, the authority, via
    # `refresh_status()`. Requests created before the token existed carry none and so
    # always take the Ponto path.
    #
    # Known and unknown names must be indistinguishable to the caller, so both redirect to the
    # same document URL, and the messages `refresh_status()` raises are dropped from the
    # response (they exist only for a known name).
    redirect_to = get_url(f"/app/ponto-payment-request/{quote(payment_request_name, safe='')}")
    messages_before = len(frappe.local.message_log or [])

    try:
        if frappe.db.exists("Ponto Payment Request", payment_request_name):
            if not _cancel_if_proved(payment_request_name):
                _refresh_from_ponto(payment_request_name)
        else:
            frappe.logger().warning("Payment callback for unknown request")

        del frappe.local.message_log[messages_before:]
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = redirect_to

    except Exception as e:
        frappe.logger().error(f"Payment callback error: {e}")
        frappe.log_error(
            title="Ponto payment callback error",
            message=str(e),
        )
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = get_url("/desk")


def _cancel_if_proved(payment_request_name):
    """Cancel a Pending request on a token-proved access_denied. True when it did."""
    args = frappe.request.args
    if args.get("error") != "access_denied":
        return False
    if not verify_guest_return_token(CANCEL_TOKEN_PURPOSE, payment_request_name, args.get("cancel_token")):
        return False
    doc = frappe.get_doc("Ponto Payment Request", payment_request_name)
    if doc.status != "Pending":
        return False
    doc.status = "Cancelled"
    # The webhook user has write permission on Ponto Payment Request (added 2026-01-10).
    doc.save()
    return True


def _refresh_from_ponto(payment_request_name):
    """Adopt the status Ponto reports for this request; a failed fetch is left to the webhook."""
    doc = frappe.get_doc("Ponto Payment Request", payment_request_name)
    try:
        doc.refresh_status()
    except Exception as e:
        frappe.logger().error(f"Failed to refresh payment status: {payment_request_name}: {e}")
