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
from verenigingen.utils.security.types import OperationType
from verenigingen.utils.service_user import get_service_user


@frappe.whitelist(allow_guest=True, methods=["GET"])
@public_api(operation_type=OperationType.PUBLIC)
def payment_callback():
    """
    Handle redirect from Ponto after payment signing.

    Query Parameters:
        payment_request: Name of the Ponto Payment Request document
        error, error_description: sent by Ponto on a failed signing; IGNORED (#1815)

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

    # The query string is attacker-controlled (this is an allow_guest GET), so nothing in it
    # decides a status: not `error`, not `error_description` (#1815). Ponto is the authority,
    # and `refresh_status()` asks it. A signing the user abandoned stays Pending until Ponto
    # (or the webhook) says otherwise.
    #
    # Known and unknown names must be indistinguishable to the caller, so both redirect to the
    # same document URL, and the messages `refresh_status()` raises are dropped from the
    # response (they exist only for a known name).
    redirect_to = get_url(f"/app/ponto-payment-request/{quote(payment_request_name, safe='')}")
    messages_before = len(frappe.local.message_log or [])

    try:
        if frappe.db.exists("Ponto Payment Request", payment_request_name):
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


def _refresh_from_ponto(payment_request_name):
    """Adopt the status Ponto reports for this request; a failed fetch is left to the webhook."""
    doc = frappe.get_doc("Ponto Payment Request", payment_request_name)
    try:
        doc.refresh_status()
    except Exception as e:
        frappe.logger().error(f"Failed to refresh payment status: {payment_request_name}: {e}")
