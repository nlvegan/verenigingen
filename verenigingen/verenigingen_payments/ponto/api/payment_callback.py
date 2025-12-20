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


def _check_payment_callback_rate_limit() -> bool:
    """Check payment callback rate limit - 20 per 5 minutes per IP."""
    ip_address = _get_client_ip()
    return check_api_rate_limit(
        user=f"ip:{ip_address}",
        endpoint="ponto_payment_callback",
        max_requests=20,
        window_minutes=5,
    )


@frappe.whitelist(allow_guest=True, methods=["GET"])
@standard_api(operation_type=OperationType.API_ACCESS)
def payment_callback():
    """
    Handle redirect from Ponto after payment signing.

    Query Parameters:
        payment_request: Name of the Ponto Payment Request document
        error: Error message if signing failed (optional)
        error_description: Detailed error description (optional)

    Returns:
        Redirect to appropriate page based on result
    """
    # Rate limit check
    if not _check_payment_callback_rate_limit():
        ip = _get_client_ip()
        frappe.logger().warning(f"Payment callback rate limit exceeded for IP: {ip}")
        frappe.local.response["http_status_code"] = 429
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = get_url("/desk")
        return

    payment_request_name = frappe.request.args.get("payment_request")
    error = frappe.request.args.get("error")
    error_description = frappe.request.args.get("error_description")

    if not payment_request_name:
        frappe.logger().warning("Payment callback received without payment_request")
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = get_url("/desk")
        return

    try:
        # Check if payment request exists
        if not frappe.db.exists("Ponto Payment Request", payment_request_name):
            frappe.logger().warning(f"Payment callback for unknown request: {payment_request_name}")
            frappe.local.response["type"] = "redirect"
            frappe.local.response["location"] = get_url("/desk")
            return

        doc = frappe.get_doc("Ponto Payment Request", payment_request_name)

        # Handle error from Ponto
        if error:
            frappe.logger().warning(
                f"Payment signing error for {payment_request_name}: {error} - {error_description}"
            )

            # If access_denied, user cancelled the signing
            # SECURITY JUSTIFICATION: OAuth2 callback from external Ponto system. Guest endpoint
            # by design (allow_guest=True). Audit trail via doc.status change and error logs.
            if error == "access_denied":
                doc.status = "Cancelled"
                doc.save(ignore_permissions=True)
                frappe.msgprint(
                    _("Payment signing was cancelled"),
                    indicator="orange",
                    alert=True,
                )
            else:
                # Other errors - mark as rejected
                doc.status = "Rejected"
                doc.save(ignore_permissions=True)
                frappe.log_error(
                    title=f"Ponto payment signing failed: {payment_request_name}",
                    message=f"Error: {error}\nDescription: {error_description}",
                )
                frappe.msgprint(
                    _("Payment signing failed: {0}").format(error_description or error),
                    indicator="red",
                    alert=True,
                )

            # Redirect to the document
            frappe.local.response["type"] = "redirect"
            frappe.local.response["location"] = get_url(f"/app/ponto-payment-request/{payment_request_name}")
            return

        # No error - refresh status from Ponto API
        frappe.logger().info(f"Payment callback success for {payment_request_name}, refreshing status")

        try:
            result = doc.refresh_status()
            new_status = result.get("status", doc.status)

            if new_status == "Signed":
                frappe.msgprint(
                    _("Payment has been signed and is awaiting execution"),
                    indicator="blue",
                    alert=True,
                )
            elif new_status == "Executed":
                frappe.msgprint(
                    _("Payment has been executed successfully"),
                    indicator="green",
                    alert=True,
                )
            else:
                frappe.msgprint(
                    _("Payment status updated to {0}").format(new_status),
                    indicator="blue",
                    alert=True,
                )

        except Exception as e:
            frappe.logger().error(f"Failed to refresh payment status: {payment_request_name}: {e}")
            frappe.msgprint(
                _("Payment callback received. Status will be updated shortly."),
                indicator="blue",
                alert=True,
            )

        # Redirect to the document
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = get_url(f"/app/ponto-payment-request/{payment_request_name}")

    except Exception as e:
        frappe.logger().error(f"Payment callback error: {e}")
        frappe.log_error(
            title="Ponto payment callback error",
            message=str(e),
        )
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = get_url("/desk")
