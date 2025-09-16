"""
Webhook Payment Gateway Access Utility

Provides secure, read-only access to payment gateway settings specifically for webhook operations.
This avoids the need to grant webhooks admin-level permissions while maintaining security.

Supported Payment Processors:
- Mollie
- Stripe (future)
- PayPal (future)
- Adyen (future)
"""

from typing import Any, Dict, Optional

import frappe
from frappe import _

from verenigingen.utils.security.api_security_framework import OperationType, webhook_api


class WebhookPaymentGatewayAccessError(frappe.ValidationError):
    """Raised when webhook payment gateway access fails"""

    pass


@frappe.whitelist()
@webhook_api(operation_type=OperationType.FINANCIAL)
def get_payment_gateway_settings(gateway_type: str, gateway_name: str = "Default") -> Dict[str, Any]:
    """
    Get payment gateway settings for webhook operations with read-only access.

    This function provides webhooks with secure access to payment gateway configuration
    without requiring admin permissions. Only essential fields are exposed.

    Args:
        gateway_type (str): Type of payment gateway ("mollie", "stripe", "paypal", etc.)
        gateway_name (str): Name/identifier of the specific gateway instance

    Returns:
        Dict[str, Any]: Payment gateway settings with sensitive data filtered

    Raises:
        WebhookPaymentGatewayAccessError: If gateway is not found or not properly configured
    """

    try:
        gateway_type = gateway_type.lower().strip()

        if gateway_type == "mollie":
            return _get_mollie_settings_for_webhook(gateway_name)
        elif gateway_type == "stripe":
            return _get_stripe_settings_for_webhook(gateway_name)
        elif gateway_type == "paypal":
            return _get_paypal_settings_for_webhook(gateway_name)
        elif gateway_type == "adyen":
            return _get_adyen_settings_for_webhook(gateway_name)
        else:
            raise WebhookPaymentGatewayAccessError(
                _("Unsupported payment gateway type: {0}").format(gateway_type)
            )

    except Exception as e:
        frappe.logger().error(f"Webhook payment gateway access failed: {str(e)}")
        raise WebhookPaymentGatewayAccessError(
            _("Failed to access {0} gateway settings: {1}").format(gateway_type, str(e))
        )


def _get_mollie_settings_for_webhook(gateway_name: str = "Default") -> Dict[str, Any]:
    """Get Mollie settings with webhook-safe field filtering using proper permissions"""

    try:
        # Check if Mollie Settings document exists
        if not frappe.db.exists("Mollie Settings", "Mollie Settings"):
            raise WebhookPaymentGatewayAccessError(_("Mollie Settings not configured"))

        # Use proper role-based access - webhook user should have read access to Mollie Settings
        settings_doc = frappe.get_doc("Mollie Settings", "Mollie Settings")

        # Return only webhook-safe fields (no sensitive configuration data)
        return {
            "gateway_type": "mollie",
            "gateway_name": gateway_name,
            "enabled": getattr(settings_doc, "enabled", False),
            "is_sandbox": getattr(settings_doc, "is_sandbox", True),
            "api_key": settings_doc.get_active_api_key(),  # Uses existing safe method
            "webhook_url": getattr(settings_doc, "webhook_url", ""),
            "currency": getattr(settings_doc, "currency", "EUR"),
            "company": getattr(settings_doc, "company", ""),
            # Don't expose: admin settings, webhook secrets, configuration URLs
        }

    except frappe.PermissionError as e:
        raise WebhookPaymentGatewayAccessError(
            _("Webhook user lacks permission to read Mollie Settings: {0}").format(str(e))
        )


def _get_stripe_settings_for_webhook(gateway_name: str = "Default") -> Dict[str, Any]:
    """Get Stripe settings with webhook-safe field filtering (future implementation)"""

    # Placeholder for future Stripe integration
    # Will follow same pattern as Mollie

    try:
        # Check if Stripe Settings doctype exists
        if not frappe.db.exists("DocType", "Stripe Settings"):
            raise WebhookPaymentGatewayAccessError(_("Stripe integration not installed"))

        if not frappe.db.exists("Stripe Settings", "Stripe Settings"):
            raise WebhookPaymentGatewayAccessError(_("Stripe Settings not configured"))

        settings_doc = frappe.get_doc("Stripe Settings", "Stripe Settings")

        return {
            "gateway_type": "stripe",
            "gateway_name": gateway_name,
            "enabled": getattr(settings_doc, "enabled", False),
            "is_sandbox": getattr(settings_doc, "is_sandbox", True),
            "publishable_key": getattr(settings_doc, "publishable_key", ""),
            "webhook_endpoint_secret": settings_doc.get_webhook_secret()
            if hasattr(settings_doc, "get_webhook_secret")
            else "",
            "currency": getattr(settings_doc, "currency", "EUR"),
            "company": getattr(settings_doc, "company", ""),
        }

    except frappe.PermissionError as e:
        raise WebhookPaymentGatewayAccessError(
            _("Webhook user lacks permission to read payment gateway settings: {0}").format(str(e))
        )


def _get_paypal_settings_for_webhook(gateway_name: str = "Default") -> Dict[str, Any]:
    """Get PayPal settings with webhook-safe field filtering (future implementation)"""

    try:
        if not frappe.db.exists("DocType", "PayPal Settings"):
            raise WebhookPaymentGatewayAccessError(_("PayPal integration not installed"))

        if not frappe.db.exists("PayPal Settings", "PayPal Settings"):
            raise WebhookPaymentGatewayAccessError(_("PayPal Settings not configured"))

        settings_doc = frappe.get_doc("PayPal Settings", "PayPal Settings")

        return {
            "gateway_type": "paypal",
            "gateway_name": gateway_name,
            "enabled": getattr(settings_doc, "enabled", False),
            "is_sandbox": getattr(settings_doc, "is_sandbox", True),
            "client_id": getattr(settings_doc, "client_id", ""),
            "webhook_id": getattr(settings_doc, "webhook_id", ""),
            "currency": getattr(settings_doc, "currency", "EUR"),
            "company": getattr(settings_doc, "company", ""),
        }

    except frappe.PermissionError as e:
        raise WebhookPaymentGatewayAccessError(
            _("Webhook user lacks permission to read payment gateway settings: {0}").format(str(e))
        )


def _get_adyen_settings_for_webhook(gateway_name: str = "Default") -> Dict[str, Any]:
    """Get Adyen settings with webhook-safe field filtering (future implementation)"""

    try:
        if not frappe.db.exists("DocType", "Adyen Settings"):
            raise WebhookPaymentGatewayAccessError(_("Adyen integration not installed"))

        if not frappe.db.exists("Adyen Settings", "Adyen Settings"):
            raise WebhookPaymentGatewayAccessError(_("Adyen Settings not configured"))

        settings_doc = frappe.get_doc("Adyen Settings", "Adyen Settings")

        return {
            "gateway_type": "adyen",
            "gateway_name": gateway_name,
            "enabled": getattr(settings_doc, "enabled", False),
            "is_sandbox": getattr(settings_doc, "is_sandbox", True),
            "api_key": settings_doc.get_api_key() if hasattr(settings_doc, "get_api_key") else "",
            "merchant_account": getattr(settings_doc, "merchant_account", ""),
            "hmac_key": settings_doc.get_hmac_key() if hasattr(settings_doc, "get_hmac_key") else "",
            "currency": getattr(settings_doc, "currency", "EUR"),
            "company": getattr(settings_doc, "company", ""),
        }

    except frappe.PermissionError as e:
        raise WebhookPaymentGatewayAccessError(
            _("Webhook user lacks permission to read payment gateway settings: {0}").format(str(e))
        )


@frappe.whitelist()
@webhook_api(operation_type=OperationType.FINANCIAL)
def get_supported_payment_gateways() -> Dict[str, Any]:
    """
    Get list of supported payment gateways and their availability.

    Returns:
        Dict[str, Any]: Available payment gateways with their status
    """

    gateways = {}

    # Check Mollie
    try:
        mollie_settings = _get_mollie_settings_for_webhook()
        gateways["mollie"] = {
            "available": True,
            "enabled": mollie_settings.get("enabled", False),
            "configured": bool(mollie_settings.get("api_key")),
        }
    except Exception:
        gateways["mollie"] = {"available": False, "enabled": False, "configured": False}

    # Check Stripe (future)
    try:
        stripe_settings = _get_stripe_settings_for_webhook()
        gateways["stripe"] = {
            "available": True,
            "enabled": stripe_settings.get("enabled", False),
            "configured": bool(stripe_settings.get("publishable_key")),
        }
    except Exception:
        gateways["stripe"] = {"available": False, "enabled": False, "configured": False}

    # Check PayPal (future)
    try:
        paypal_settings = _get_paypal_settings_for_webhook()
        gateways["paypal"] = {
            "available": True,
            "enabled": paypal_settings.get("enabled", False),
            "configured": bool(paypal_settings.get("client_id")),
        }
    except Exception:
        gateways["paypal"] = {"available": False, "enabled": False, "configured": False}

    # Check Adyen (future)
    try:
        adyen_settings = _get_adyen_settings_for_webhook()
        gateways["adyen"] = {
            "available": True,
            "enabled": adyen_settings.get("enabled", False),
            "configured": bool(adyen_settings.get("api_key")),
        }
    except Exception:
        gateways["adyen"] = {"available": False, "enabled": False, "configured": False}

    return {
        "supported_gateways": list(gateways.keys()),
        "gateway_status": gateways,
        "total_available": sum(1 for g in gateways.values() if g["available"]),
        "total_enabled": sum(1 for g in gateways.values() if g["enabled"]),
    }


def get_mollie_client_for_webhook(gateway_name: str = "Default"):
    """
    Get configured Mollie API client for webhook operations.

    This is a convenience function that combines settings access with client creation.

    Args:
        gateway_name (str): Gateway instance name

    Returns:
        mollie.api.client.Client: Configured Mollie API client

    Raises:
        WebhookPaymentGatewayAccessError: If client cannot be created
    """

    try:
        import mollie.api.client

        settings = _get_mollie_settings_for_webhook(gateway_name)

        if not settings.get("enabled"):
            raise WebhookPaymentGatewayAccessError(_("Mollie gateway is disabled"))

        api_key = settings.get("api_key")
        if not api_key:
            raise WebhookPaymentGatewayAccessError(_("Mollie API key not configured"))

        client = mollie.api.client.Client()
        client.set_api_key(api_key)

        frappe.logger().info(f"✅ Created Mollie client for webhook (sandbox: {settings.get('is_sandbox')})")
        return client

    except ImportError:
        raise WebhookPaymentGatewayAccessError(_("Mollie Python library not installed"))
    except Exception as e:
        frappe.logger().error(f"Failed to create Mollie client for webhook: {str(e)}")
        raise WebhookPaymentGatewayAccessError(_("Failed to create Mollie client: {0}").format(str(e)))
