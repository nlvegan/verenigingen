# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Ponto Betaalverzoek Callback Handler

Handles redirects from Ponto after customer payment authorization.

When a customer authorizes a payment in the Ponto payment portal,
they are redirected back to this callback URL. This endpoint:
1. Validates the payment link
2. Refreshes the payment status from Ponto API
3. Redirects to appropriate success/failure page

Usage:
    Callback URL:
    https://your-site.com/api/method/verenigingen.verenigingen_payments.ponto.api.betaalverzoek_callback.payment_link_callback?payment_link=PONTO-LINK-0001
"""

import frappe
from frappe import _
from frappe.utils import get_url

from verenigingen.templates.pages.payment_success import PONTO_RETURN_TOKEN_PURPOSE
from verenigingen.utils.security.api_security_framework import public_api
from verenigingen.utils.security.guest_return_tokens import (
    generate_guest_return_token,
    verify_guest_return_token,
)
from verenigingen.utils.security.types import OperationType
from verenigingen.utils.service_user import get_service_user

# Scopes the signed `cancel_token` minted into the redirect_uri at signing start
# (PontoPaymentLink.create_ponto_payment_request). Distinct from PONTO_RETURN_TOKEN_PURPOSE
# (the #1055 payment-success proof), so neither verifies as the other.
CANCEL_TOKEN_PURPOSE = "ponto_payment_link_cancel"


def _payment_success_redirect(payment_link_name):
    """Build the /payment-success redirect URL for a Ponto Payment Link return.

    Embeds an HMAC proof (#1055 finding 1) since Ponto Payment Link.autoname
    is a small sequential PONTO-LINK-{####} counter and payment_success.py's
    Ponto branch has no session to check ownership against -- this is the
    one place we construct that URL, so it's the one place that can mint it.
    """
    token = generate_guest_return_token(PONTO_RETURN_TOKEN_PURPOSE, payment_link_name)
    return get_url(f"/payment-success?payment_link={payment_link_name}&token={token}")


@frappe.whitelist(allow_guest=True, methods=["GET"])
@public_api(operation_type=OperationType.PUBLIC)
def payment_link_callback():
    """
    Handle redirect from Ponto after customer payment authorization.

    Query Parameters:
        payment_link: Name of the Ponto Payment Link document
        error: `access_denied` cancels a Pending Authorization link ONLY with a valid
            `cancel_token` (minted into the redirect_uri at signing start); any other error,
            or a missing or invalid token, is ignored (#1815)
        error_description: ignored
        cancel_token: signed proof that this browser was sent to Ponto for this link

    Returns:
        Redirect to appropriate page based on result

    Note:
        Rate limiting is handled by COR 'payment_link_callback'
        with per-IP scope: 30 requests per 5 minutes.
    """
    # Set webhook user context for permission-based operations
    webhook_user = get_service_user(
        settings_doctype="Verenigingen Payments Settings",
        user_field="webhook_user",
        service_name="Ponto Betaalverzoek Callback",
    )
    if webhook_user:
        frappe.set_user(webhook_user)

    payment_link_name = frappe.request.args.get("payment_link")

    if not payment_link_name:
        frappe.logger().warning("Payment link callback received without payment_link")
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = get_url("/app/home")
        return

    try:
        # Check if payment link exists
        if not frappe.db.exists("Ponto Payment Link", payment_link_name):
            frappe.logger().warning(f"Payment link callback for unknown link: {payment_link_name}")
            frappe.local.response["type"] = "redirect"
            frappe.local.response["location"] = get_url("/app/home")
            return

        # No status comes from the query string (#1815), with ONE ruled exception:
        # `error=access_denied` plus a valid `cancel_token` marks a Pending Authorization
        # link Cancelled. Everything else asks Ponto, the authority, via refresh_status().
        # Links created before the token existed carry none and so take the Ponto path.
        # Messages raised by the refresh/save are dropped from the response, as in
        # payment_callback, so a known name does not answer differently from an unknown one.
        messages_before = len(frappe.local.message_log or [])
        if not _cancel_link_if_proved(payment_link_name):
            _refresh_link_from_ponto(payment_link_name)
        del frappe.local.message_log[messages_before:]

        # Redirect to customer-friendly payment status page
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = _payment_success_redirect(payment_link_name)

    except Exception as e:
        frappe.logger().error(f"Payment link callback error: {e}")
        frappe.log_error(
            title="Ponto payment callback error",
            message=str(e),
        )
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = get_url("/app/home")


def _cancel_link_if_proved(payment_link_name):
    """Cancel a Pending Authorization link on a token-proved access_denied. True when it did."""
    args = frappe.request.args
    if args.get("error") != "access_denied":
        return False
    if not verify_guest_return_token(CANCEL_TOKEN_PURPOSE, payment_link_name, args.get("cancel_token")):
        return False
    doc = frappe.get_doc("Ponto Payment Link", payment_link_name)
    if doc.status != "Pending Authorization":
        return False
    doc.status = "Cancelled"
    # The webhook user has write permission on Ponto Payment Link (added 2026-01-10).
    doc.save()
    return True


def _refresh_link_from_ponto(payment_link_name):
    """Adopt the status Ponto reports; a failed fetch is left to the webhook."""
    doc = frappe.get_doc("Ponto Payment Link", payment_link_name)
    try:
        result = doc.refresh_status()
        frappe.logger().info(f"Payment link {payment_link_name} status: {result.get('status')}")
    except Exception as e:
        frappe.logger().error(f"Failed to refresh payment link status: {payment_link_name}: {e}")


@frappe.whitelist(allow_guest=True, methods=["GET"])
@public_api
def payment_page():
    """
    Serve a customer-facing payment page for a Ponto Payment Link.

    This is an alternative to sharing the direct Ponto redirect link.
    Shows payment details and redirects customer to Ponto authorization.

    Query Parameters:
        link: Ponto Payment Link name

    Returns:
        HTML page with payment details and authorization button
    """
    payment_link_name = frappe.request.args.get("link")

    if not payment_link_name:
        frappe.throw(_("Payment link not specified"), frappe.exceptions.DoesNotExistError)

    if not frappe.db.exists("Ponto Payment Link", payment_link_name):
        frappe.throw(_("Payment link not found"), frappe.exceptions.DoesNotExistError)

    doc = frappe.get_doc("Ponto Payment Link", payment_link_name)

    # Check if payment link is still valid
    if doc.status not in ["Draft", "Pending Authorization"]:
        if doc.status == "Executed":
            return {"status": "already_paid", "message": _("This payment has already been completed.")}
        elif doc.status == "Cancelled":
            return {"status": "cancelled", "message": _("This payment request has been cancelled.")}
        elif doc.status == "Expired":
            return {"status": "expired", "message": _("This payment request has expired.")}
        else:
            return {"status": doc.status.lower(), "message": _("This payment request is not available.")}

    # Return payment details
    return {
        "status": "pending",
        "payment_link": doc.name,
        "amount": doc.amount,
        "currency": doc.currency,
        "description": doc.description,
        "creditor_name": doc.creditor_name,
        "payment_type": doc.payment_type,
        "frequency": doc.frequency if doc.payment_type == "Periodic" else None,
        "redirect_link": doc.redirect_link,
    }
