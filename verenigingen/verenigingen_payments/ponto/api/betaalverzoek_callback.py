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

from verenigingen.utils.security.api_security_framework import OperationType, standard_api
from verenigingen.utils.security.rate_limiter import check_api_rate_limit


def _get_client_ip() -> str:
    """Get client IP address, handling proxies."""
    forwarded_for = frappe.request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return frappe.request.remote_addr or "unknown"


def _check_betaalverzoek_callback_rate_limit() -> bool:
    """Check betaalverzoek callback rate limit - 30 per 5 minutes per IP."""
    ip_address = _get_client_ip()
    return check_api_rate_limit(
        user=f"ip:{ip_address}",
        endpoint="ponto_betaalverzoek_callback",
        max_requests=30,
        window_minutes=5,
    )


@frappe.whitelist(allow_guest=True, methods=["GET"])
@standard_api(operation_type=OperationType.PUBLIC)
def payment_link_callback():
    """
    Handle redirect from Ponto after customer payment authorization.

    Query Parameters:
        payment_link: Name of the Ponto Payment Link document
        error: Error message if authorization failed (optional)
        error_description: Detailed error description (optional)

    Returns:
        Redirect to appropriate page based on result
    """
    # Rate limit check
    if not _check_betaalverzoek_callback_rate_limit():
        ip = _get_client_ip()
        frappe.logger().warning(f"Betaalverzoek callback rate limit exceeded for IP: {ip}")
        frappe.local.response["http_status_code"] = 429
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = get_url("/app/home")
        return

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
            # SECURITY JUSTIFICATION: OAuth2 callback from external Ponto system. Guest endpoint
            # by design (allow_guest=True). Audit trail via doc.status change and error logs.
            if error == "access_denied":
                doc.status = "Cancelled"
                doc.save(ignore_permissions=True)
                frappe.local.response["type"] = "redirect"
                frappe.local.response["location"] = get_url(
                    f"/payment-success?payment_link={payment_link_name}"
                )
                return
            else:
                # Other errors - mark as rejected
                doc.status = "Rejected"
                doc.save(ignore_permissions=True)
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
