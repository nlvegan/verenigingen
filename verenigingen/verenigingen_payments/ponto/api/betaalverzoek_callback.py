# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Ponto Betaalverzoek Callback Handler

Handles redirects from Ponto after customer payment authorization.

When a customer authorizes a payment in the Ponto payment portal,
they are redirected back to this callback URL. This endpoint:
1. Validates the payment link
2. Redirects to the payment-success page (status comes from the signed webhook)

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

# Scopes the signed `return_proof` minted into the same redirect_uri (#1833). It is the ONLY
# thing that lets payment_link_callback hand out the /payment-success token, so it must be a
# third purpose: distinct from the cancel proof (which authorises a write, not a disclosure)
# and from PONTO_RETURN_TOKEN_PURPOSE (the token it unlocks; if the two were the same string,
# the token this callback hands out would itself pass as the proof for the next request).
RETURN_PROOF_PURPOSE = "ponto_payment_link_return_proof"


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
        return_proof: signed proof, minted into the redirect_uri at signing start, required
            for the redirect to /payment-success; without it the answer is the unknown-name one

    Returns:
        Redirect to appropriate page based on result

    Note:
        Rate limiting is handled by COR 'payment_link_callback'
        with per-IP scope: 30 requests per 5 minutes.
    """
    # Set webhook user context for permission-based operations. No Administrator fallback
    # (#1834): this is an anonymous GET, so with no usable webhook_user it runs as Guest and
    # changes nothing (the token-proved cancel below is skipped).
    webhook_user = get_service_user(
        settings_doctype="Verenigingen Payments Settings",
        user_field="webhook_user",
        service_name="Ponto Betaalverzoek Callback",
        fallback_user=None,
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
        exists = frappe.db.exists("Ponto Payment Link", payment_link_name)
        if not exists:
            frappe.logger().warning("Payment link callback for unknown link")

        # No status comes from the query string (#1815), with ONE ruled exception:
        # `error=access_denied` plus a valid `cancel_token` marks a Pending Authorization
        # link Cancelled, and only as the configured webhook user. Nothing else changes here:
        # the callback does not call Ponto (#1834), the signed webhook is the status writer.
        # Messages raised by the cancel's save are dropped from the response, as in
        # payment_callback, so a known name does not answer differently from an unknown one.
        messages_before = len(frappe.local.message_log or [])
        if exists and webhook_user:
            _cancel_link_if_proved(payment_link_name)
        del frappe.local.message_log[messages_before:]

        # The /payment-success token (#1055) is handed out ONLY against the signed
        # `return_proof` minted into the redirect_uri at signing start (#1833). A known name
        # without a valid proof takes the same branch as an unknown one, so nothing here tells
        # an anonymous caller which names exist. Links created before the proof existed carry
        # none and so get the unknown-name answer.
        if exists and _has_return_proof(payment_link_name):
            frappe.local.response["type"] = "redirect"
            frappe.local.response["location"] = _payment_success_redirect(payment_link_name)
        else:
            frappe.local.response["type"] = "redirect"
            frappe.local.response["location"] = get_url("/app/home")

    except Exception as e:
        frappe.logger().error(f"Payment link callback error: {e}")
        frappe.log_error(
            title="Ponto payment callback error",
            message=str(e),
        )
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = get_url("/app/home")


def _has_return_proof(payment_link_name):
    """True when the request carries the signed proof minted for THIS link at signing start."""
    return verify_guest_return_token(
        RETURN_PROOF_PURPOSE, payment_link_name, frappe.request.args.get("return_proof")
    )


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
