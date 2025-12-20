# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Ponto Connect OAuth2 Callback Handler

Handles the OAuth2 authorization callback from Ibanity.

When a user authorizes the application in the Ibanity portal,
they are redirected back to this callback URL with an authorization code.
This endpoint exchanges the code for access and refresh tokens.

Usage:
    Callback URL (auto-generated):
    https://your-site.com/api/method/verenigingen.verenigingen_payments.ponto.api.oauth2_callback.handle_callback
"""

import frappe
from frappe import _
from frappe.utils import get_url

from verenigingen.utils.security.rate_limiter import check_api_rate_limit


def _get_client_ip() -> str:
    """Get client IP address, handling proxies."""
    # Check X-Forwarded-For for reverse proxy setups
    forwarded_for = frappe.request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # Take the first IP (client IP)
        return forwarded_for.split(",")[0].strip()
    # Fall back to remote_addr
    return frappe.request.remote_addr or "unknown"


def _check_oauth_rate_limit() -> bool:
    """
    Check OAuth callback rate limit.

    Returns:
        bool: True if request is allowed, False if rate limited
    """
    ip_address = _get_client_ip()
    # Stricter limit for OAuth callbacks: 10 requests per 10 minutes per IP
    # OAuth callbacks should be infrequent (user authorization events)
    return check_api_rate_limit(
        user=f"ip:{ip_address}",
        endpoint="ponto_oauth_callback",
        max_requests=10,
        window_minutes=10,
    )


@frappe.whitelist(allow_guest=True, methods=["GET"])
def handle_callback():
    """
    Handle OAuth2 authorization callback from Ibanity.

    Query Parameters:
        code: Authorization code to exchange for tokens
        state: CSRF protection state parameter
        error: Error code if authorization failed (optional)
        error_description: Error description (optional)

    Returns:
        Redirect to appropriate page based on result
    """
    # Rate limit check - prevent abuse of OAuth callback endpoint
    if not _check_oauth_rate_limit():
        ip = _get_client_ip()
        frappe.logger().warning(f"OAuth callback rate limit exceeded for IP: {ip}")
        frappe.log_error(
            title="OAuth callback rate limit exceeded",
            message=f"IP {ip} exceeded OAuth callback rate limit. Possible attack attempt.",
        )
        frappe.local.response["http_status_code"] = 429
        frappe.msgprint(
            _("Too many authorization requests. Please try again later."),
            indicator="red",
            title=_("Rate Limited"),
        )
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = get_url("/app/ponto-settings")
        return

    code = frappe.request.args.get("code")
    state = frappe.request.args.get("state")
    error = frappe.request.args.get("error")
    error_description = frappe.request.args.get("error_description")

    # Handle error from Ibanity
    if error:
        frappe.logger().warning(f"Ponto OAuth2 authorization error: {error} - {error_description}")

        if error == "access_denied":
            frappe.msgprint(
                _("Authorization was cancelled or denied."),
                indicator="orange",
                title=_("Authorization Cancelled"),
            )
        else:
            frappe.log_error(
                title="Ponto OAuth2 authorization failed",
                message=f"Error: {error}\nDescription: {error_description}",
            )
            frappe.msgprint(
                _("Authorization failed: {0}").format(error_description or error),
                indicator="red",
                title=_("Authorization Failed"),
            )

        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = get_url("/app/ponto-settings")
        return

    # Validate required parameters
    if not code:
        frappe.logger().warning("OAuth2 callback received without authorization code")
        frappe.msgprint(
            _("No authorization code received."),
            indicator="red",
            title=_("Authorization Failed"),
        )
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = get_url("/app/ponto-settings")
        return

    if not state:
        frappe.logger().warning("OAuth2 callback received without state parameter")
        frappe.msgprint(
            _("Invalid callback - missing state parameter."),
            indicator="red",
            title=_("Security Error"),
        )
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = get_url("/app/ponto-settings")
        return

    try:
        from verenigingen.verenigingen_payments.ponto.services.oauth2_service import get_oauth2_service

        oauth2_service = get_oauth2_service()

        # Verify state for CSRF protection
        if not oauth2_service.verify_state(state):
            frappe.logger().warning("OAuth2 state verification failed")
            frappe.msgprint(
                _("Invalid state parameter. Please try authorizing again."),
                indicator="red",
                title=_("Security Error"),
            )
            frappe.local.response["type"] = "redirect"
            frappe.local.response["location"] = get_url("/app/ponto-settings")
            return

        # Exchange code for tokens
        tokens = oauth2_service.exchange_authorization_code(code)

        frappe.logger().info(
            f"Ponto OAuth2 authorization successful, token expires in {tokens.get('expires_in')} seconds"
        )

        frappe.msgprint(
            _("Ponto Connect authorization successful! You can now use payment initiation features."),
            indicator="green",
            title=_("Authorization Successful"),
        )

        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = get_url("/app/ponto-settings")

    except Exception as e:
        frappe.logger().error(f"OAuth2 callback error: {e}")
        frappe.log_error(
            title="Ponto OAuth2 callback error",
            message=str(e),
        )
        frappe.msgprint(
            _("Failed to complete authorization: {0}").format(str(e)),
            indicator="red",
            title=_("Authorization Failed"),
        )
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = get_url("/app/ponto-settings")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def get_authorization_url():
    """
    Get the Ponto Connect authorization URL.

    Returns:
        Dict with authorization_url
    """
    # Check permissions
    if not frappe.has_permission("Ponto Settings", "write"):
        frappe.throw(_("You don't have permission to authorize Ponto Connect"))

    try:
        from verenigingen.verenigingen_payments.ponto.services.oauth2_service import get_oauth2_service

        oauth2_service = get_oauth2_service()
        auth_url = oauth2_service.get_authorization_url()

        return {
            "success": True,
            "authorization_url": auth_url,
        }

    except Exception as e:
        frappe.log_error(
            title="Ponto OAuth2 get authorization URL error",
            message=str(e),
        )
        return {
            "success": False,
            "error": str(e),
        }


@frappe.whitelist(allow_guest=False, methods=["POST"])
def check_authorization_status():
    """
    Check if Ponto Connect is authorized.

    Returns:
        Dict with authorization status
    """
    try:
        from verenigingen.verenigingen_payments.ponto.services.oauth2_service import get_oauth2_service

        oauth2_service = get_oauth2_service()
        is_authorized = oauth2_service.is_authorized()

        return {
            "success": True,
            "is_authorized": is_authorized,
        }

    except Exception as e:
        return {
            "success": False,
            "is_authorized": False,
            "error": str(e),
        }


@frappe.whitelist(allow_guest=False, methods=["POST"])
def revoke_authorization():
    """
    Revoke Ponto Connect authorization (clear tokens).

    Returns:
        Dict with success status
    """
    # Check permissions
    if not frappe.has_permission("Ponto Settings", "write"):
        frappe.throw(_("You don't have permission to revoke Ponto authorization"))

    try:
        from verenigingen.verenigingen_payments.ponto.services.oauth2_service import get_oauth2_service

        oauth2_service = get_oauth2_service()
        oauth2_service.revoke_tokens()

        frappe.msgprint(
            _("Ponto Connect authorization has been revoked."),
            indicator="green",
            title=_("Authorization Revoked"),
        )

        return {
            "success": True,
        }

    except Exception as e:
        frappe.log_error(
            title="Ponto OAuth2 revoke error",
            message=str(e),
        )
        return {
            "success": False,
            "error": str(e),
        }
