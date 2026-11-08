"""
Mollie Webhook API Endpoints

Updated HTTP endpoints using the complete webhook service with all business logic.
"""

import frappe
from frappe import _

from verenigingen.utils.security.api_security_framework import OperationType, public_api
from verenigingen.utils.security.client_ip import get_client_ip

from ...utils.webhook_ack import log_error_once
from ..exceptions import MollieSecurityError, MollieWebhookError


def _log_wrapper_error_once(title: str, what: str, exc: Exception) -> None:
    """One row per (title, caller IP, exception class) per hour; the endpoints are guest-reachable (#2187).

    The exception text is cut before the traceback is appended so that a long caller-influenced
    message cannot push the frames past the 4000-character cap. Passing a message makes frappe
    skip its own traceback, hence ``get_traceback`` here.
    """
    message = f"{what}: {str(exc)[:500]}\n{frappe.get_traceback()}"
    log_error_once(title, message, get_client_ip(), type(exc).__name__)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@public_api(operation_type=OperationType.WEBHOOK_PROCESSING)
def handle_mollie_payment_webhook():
    """
    Redirect to unified API endpoint for better architecture.
    This maintains backward compatibility while using the modern service layer.
    """
    try:
        # Import and delegate to unified API
        from .unified_payment_api import handle_payment_webhook

        return handle_payment_webhook()

    except Exception as e:
        _log_wrapper_error_once("Mollie Webhook API", "Webhook endpoint error", e)
        frappe.response.http_status_code = 500
        return {"status": "error"}


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

        # Process webhook using unified API
        from .unified_payment_api import handle_payment_webhook

        result = handle_payment_webhook()
        return result

    except MollieSecurityError:
        frappe.response.http_status_code = 403
        return {"status": "error"}

    except MollieWebhookError:
        frappe.response.http_status_code = 400
        return {"status": "error"}

    except Exception as e:
        _log_wrapper_error_once("Mollie Webhook Error", "Unexpected error in unified webhook", e)
        frappe.response.http_status_code = 500
        return {"status": "error"}


@frappe.whitelist(methods=["GET"])
@public_api(operation_type=OperationType.UTILITY)
def webhook_health_check():
    """
    Health check endpoint for webhook monitoring.
    """
    try:
        # Check Mollie settings
        mollie_settings = frappe.get_single("Mollie Settings")

        # The webhook URL is stored per-mode (testing_webhook_url / live_webhook_url);
        # there is no flat `webhook_url` field, so read the mode-appropriate one.
        # (Accessing the non-existent `webhook_url` previously made this health
        # check ALWAYS raise AttributeError and report 'unhealthy'.)
        webhook_url = (
            mollie_settings.get("testing_webhook_url")
            if mollie_settings.test_mode
            else mollie_settings.get("live_webhook_url")
        )

        health_status = {
            "status": "healthy",
            "service": "Mollie Webhook Service",
            "timestamp": frappe.utils.now_datetime(),
            "configuration": {
                "webhook_url_configured": bool(webhook_url),
                "api_key_configured": bool(mollie_settings.get_active_api_key()),
                "test_mode": mollie_settings.test_mode,
                "webhook_user_exists": frappe.db.exists("User", "webhook.user@veganisme.org"),
            },
        }

        # Check webhook service
        try:
            from ..services.webhook_wrapper_service_unified import get_unified_webhook_service

            webhook_service = get_unified_webhook_service()
            health_status["services"] = {
                "webhook_service": "available",
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
@public_api
def mollie_payment_webhook():
    """Backward compatibility - routes to main handler"""
    return handle_mollie_payment_webhook()


@frappe.whitelist(allow_guest=True, methods=["POST"])
@public_api
def mollie_subscription_webhook():
    """Backward compatibility - routes to main handler"""
    return handle_mollie_payment_webhook()
