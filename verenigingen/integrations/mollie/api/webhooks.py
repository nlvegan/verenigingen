"""
Mollie Webhook API Endpoints

Updated HTTP endpoints using the complete webhook service with all business logic.
"""

import frappe
from frappe import _

from verenigingen.utils.security.api_security_framework import OperationType, public_api

from ..core.mollie_exceptions import MollieSecurityError, MollieWebhookError
from ..services.webhook_service import WebhookService


@frappe.whitelist(allow_guest=True, methods=["POST"])
@public_api(operation_type=OperationType.WEBHOOK_PROCESSING)
def handle_mollie_payment_webhook():
    """
    Main webhook endpoint that uses the complete webhook service.
    This replaces the original handle_mollie_payment_webhook function.
    """
    try:
        webhook_service = WebhookService()
        result = webhook_service.handle_mollie_payment_webhook()
        return result

    except Exception as e:
        frappe.log_error(f"Webhook endpoint error: {e}", "Mollie Webhook API")
        frappe.response.http_status_code = 500
        return {"status": "error", "message": "Internal server error processing webhook", "error": str(e)}


@frappe.whitelist(allow_guest=True, methods=["POST", "GET"])
@public_api(operation_type=OperationType.WEBHOOK_PROCESSING)
def handle_unified_webhook():
    """
    Unified webhook handler for all Mollie events.
    Routes to appropriate handlers based on event type.
    """
    try:
        # Handle GET requests as health checks
        if frappe.local.request.method == "GET":
            return {
                "status": "healthy",
                "service": "Mollie Webhook Handler",
                "version": "2.0.0",
                "timestamp": frappe.utils.now_datetime(),
            }

        # Process webhook using complete service
        webhook_service = WebhookService()
        result = webhook_service.handle_mollie_payment_webhook()
        return result

    except MollieSecurityError as e:
        frappe.response.http_status_code = 403
        return {"status": "error", "message": "Security validation failed", "error": str(e)}

    except MollieWebhookError as e:
        frappe.response.http_status_code = 400
        return {"status": "error", "message": "Webhook processing failed", "error": str(e)}

    except Exception as e:
        frappe.log_error(f"Unexpected error in unified webhook: {e}", "Mollie Webhook Error")
        frappe.response.http_status_code = 500
        return {"status": "error", "message": "Internal server error"}


@frappe.whitelist(methods=["GET"])
@public_api(operation_type=OperationType.SYSTEM_STATUS)
def webhook_health_check():
    """
    Health check endpoint for webhook monitoring.
    """
    try:
        # Check Mollie settings
        mollie_settings = frappe.get_single("Mollie Settings")

        health_status = {
            "status": "healthy",
            "service": "Mollie Webhook Service",
            "timestamp": frappe.utils.now_datetime(),
            "configuration": {
                "webhook_url_configured": bool(mollie_settings.webhook_url),
                "api_key_configured": bool(mollie_settings.get_active_api_key()),
                "test_mode": mollie_settings.test_mode,
                "webhook_user_exists": frappe.db.exists("User", "webhook.user@veganisme.org"),
            },
        }

        # Check webhook service
        try:
            webhook_service = WebhookService()
            health_status["services"] = {
                "webhook_service": "available",
                "client_available": "available" if webhook_service.client else "unavailable",
            }
        except Exception as e:
            health_status["services"] = {"webhook_service": "error", "error": str(e)}
            health_status["status"] = "degraded"

        return health_status

    except Exception as e:
        frappe.response.http_status_code = 500
        return {"status": "unhealthy", "error": str(e), "timestamp": frappe.utils.now_datetime()}


# Backward compatibility endpoints
@frappe.whitelist(allow_guest=True, methods=["POST"])
def mollie_payment_webhook():
    """Backward compatibility - routes to main handler"""
    return handle_mollie_payment_webhook()


@frappe.whitelist(allow_guest=True, methods=["POST"])
def mollie_subscription_webhook():
    """Backward compatibility - routes to main handler"""
    return handle_mollie_payment_webhook()
