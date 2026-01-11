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

from verenigingen.utils.security.api_security_framework import public_api
from verenigingen.utils.security.types import OperationType
from verenigingen.utils.service_user import get_service_user


@frappe.whitelist(allow_guest=True, methods=["GET"])
@public_api(operation_type=OperationType.PUBLIC)
def payment_link_callback():
    """
    Handle redirect from Ponto after customer payment authorization.

    Query Parameters:
        payment_link: Name of the Ponto Payment Link document
        error: Error message if authorization failed (optional)
        error_description: Detailed error description (optional)

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
    error = frappe.request.args.get("error")
    error_description = frappe.request.args.get("error_description")

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

        doc = frappe.get_doc("Ponto Payment Link", payment_link_name)

        # Handle error from Ponto
        if error:
            frappe.logger().warning(
                f"Payment link authorization error for {payment_link_name}: {error} - {error_description}"
            )

            # If access_denied, customer cancelled the authorization
            if error == "access_denied":
                doc.status = "Cancelled"
                # Webhook user has write permission on Ponto Payment Link (added 2026-01-10)
                doc.save()
                frappe.local.response["type"] = "redirect"
                frappe.local.response["location"] = get_url(
                    f"/payment-success?payment_link={payment_link_name}"
                )
                return
            else:
                # Other errors - mark as rejected
                doc.status = "Rejected"
                # Webhook user has write permission on Ponto Payment Link (added 2026-01-10)
                doc.save()
                frappe.log_error(
                    title=f"Ponto payment authorization failed: {payment_link_name}",
                    message=f"Error: {error}\nDescription: {error_description}",
                )
                frappe.local.response["type"] = "redirect"
                frappe.local.response["location"] = get_url(
                    f"/payment-success?payment_link={payment_link_name}"
                )
                return

        # No error - refresh status from Ponto API
        frappe.logger().info(f"Payment link callback success for {payment_link_name}, refreshing status")

        try:
            result = doc.refresh_status()
            new_status = result.get("status", doc.status)
            frappe.logger().info(f"Payment link {payment_link_name} status: {new_status}")

        except Exception as e:
            frappe.logger().error(f"Failed to refresh payment link status: {payment_link_name}: {e}")
            # Status will be updated by webhook

        # Redirect to customer-friendly payment status page
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = get_url(f"/payment-success?payment_link={payment_link_name}")

    except Exception as e:
        frappe.logger().error(f"Payment link callback error: {e}")
        frappe.log_error(
            title="Ponto payment callback error",
            message=str(e),
        )
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = get_url("/app/home")


@frappe.whitelist(allow_guest=True, methods=["GET"])
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
