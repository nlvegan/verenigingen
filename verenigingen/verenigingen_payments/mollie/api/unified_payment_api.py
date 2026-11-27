"""
Unified Mollie Payment API

A clean, unified API interface that exposes the new service layer functionality
through properly secured Frappe endpoints. This replaces the scattered webhook
endpoints with a comprehensive API.
"""

import hashlib
from typing import Any, Dict, Optional

import frappe
from frappe import _

from verenigingen.utils.security.api_security_framework import (
    OperationType,
    high_security_api,
    public_api,
    standard_api,
)
from verenigingen.utils.security.client_ip import get_client_ip
from verenigingen.utils.service_user import restores_session_user
from verenigingen.utils.webhook_rate_limiter import WebhookRateLimitExceeded
from verenigingen.verenigingen_payments.utils.payment_services.logging_utils import log_webhook_received
from verenigingen.verenigingen_payments.utils.payment_services.refund_utility import (
    validate_refund_permissions,
)
from verenigingen.verenigingen_payments.utils.webhook_ack import (
    first_in_window,
    log_error_once,
    short_id,
    webhook_ack,
)

from ..exceptions import MolliePaymentError, MollieValidationError, MollieWebhookError
from ..services.complete_payment_service import CompletePaymentService
from ..services.webhook_wrapper_service_unified import get_unified_webhook_service
from ..utils.amount_helpers import extract_amount_value

_ERROR_LOG_DEDUPE_PREFIX = "mollie_webhook_failure:"


def _ack_with_error_log(
    messages_before: int, detail: Optional[Dict[str, Any]] = None, *ids: Optional[str]
) -> Dict[str, str]:
    """The shared anonymous-webhook ack, plus an Error Log row for ``detail`` (#1781, #1822).

    Mollie posts a bare ``id=tr_...`` without credentials, so whoever holds a payment id is,
    to this endpoint, Mollie: the caller is told ``ok``/``error`` and nothing else (see
    ``webhook_ack``), and the detail it used to receive goes to the Error Log instead.
    ``ids`` are the caller-supplied ids the failure is deduped (and shortened) by.
    """
    if detail is not None:
        _log_webhook_failure_once(detail, *ids)
    return webhook_ack(messages_before)


def _log_webhook_failure_once(detail: Dict[str, Any], *ids: Optional[str]) -> None:
    """One Error Log row per (id, status, HTTP status) per hour, with the ids cut short.

    An anonymous caller can repeat a failing delivery up to the endpoint's rate limit, and
    the id is theirs to make as long as they like, so neither the row count nor the row size
    may follow the caller. The cache key hashes the whole id; the logged text carries 64
    characters of it.
    """
    http_status = frappe.local.response.get("http_status_code") or 200
    key_ids = "|".join(str(i) for i in ids if i)
    fingerprint = f"{key_ids}|{detail.get('status')}|{http_status}"
    key = _ERROR_LOG_DEDUPE_PREFIX + hashlib.sha256(fingerprint.encode()).hexdigest()
    if not first_in_window(key):
        return
    message = frappe.as_json(detail)
    for value in ids:
        if value and len(str(value)) > len(short_id(value)):
            message = message.replace(str(value), short_id(value))
    # Keywords, because this app's positional (title, message) order is routinely swapped.
    frappe.log_error(title="Mollie Webhook Processing Error", message=message)


def _log_exception_once(
    title: str, exc: Exception, *ids: Optional[str], with_traceback: bool = False
) -> None:
    """The Error Log row for an exception a webhook handler answers with 4xx/5xx (#2136).

    Deduped per (title, caller IP, exception class) per hour, never per id: the id is the
    caller's to choose, so keying on it would let a caller write a row per request. The first
    row of the hour still names the (shortened) ids.
    """
    named = ", ".join(short_id(i) for i in ids if i)
    message = f"{title} ({named}): {exc}" if named else f"{title}: {exc}"
    if with_traceback:
        message += f"\n{frappe.get_traceback()}"
    log_error_once(title, message, get_client_ip(), type(exc).__name__)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@public_api(operation_type=OperationType.PUBLIC)
@restores_session_user
def handle_payment_webhook(payment_id: Optional[str] = None):
    """
    Unified webhook handler for all Mollie payment notifications.

    This endpoint handles webhooks for:
    - Single payments (donations)
    - Subscription payments
    - Refunds and chargebacks

    Args:
        payment_id: The Mollie payment/transaction ID (can be passed as parameter or in form_dict)

    Returns:
        Dict with processing results
    """
    messages_before = len(frappe.local.message_log or [])
    try:
        # Get payment ID from parameter or fallback to form_dict (for direct API calls)
        if not payment_id:
            payment_id = frappe.form_dict.get("id") or (frappe.local.form_dict or {}).get("id")

        # Structured logging of webhook receipt (entry-point only; does not alter flow).
        log_webhook_received(
            webhook_id=payment_id or "unknown",
            webhook_type="mollie",
            payload_size=(
                len(frappe.request.data)
                if getattr(frappe, "request", None) and getattr(frappe.request, "data", None)
                else 0
            ),
        )

        if not payment_id:
            frappe.throw(_("Payment ID is required"))

        # PHASE 2: Authentication - set webhook user context
        from verenigingen.verenigingen_payments.mollie.utils.webhook_security import (
            authenticate_mollie_webhook,
        )

        authenticate_mollie_webhook()

        frappe.logger().info(f"🔔 Webhook received for payment: {payment_id}")

        # PHASE 3: Service processing
        service = get_unified_webhook_service()

        # Extract webhook data for processing (if available)
        webhook_data = frappe.form_dict or {}

        result = service.process_payment_webhook(payment_id, webhook_data)

        # CRITICAL FIX: Set appropriate HTTP status based on service result
        if result.get("status") == "error":
            frappe.logger().error(f"❌ Webhook processing failed: {payment_id} - {result.get('message')}")
            frappe.response.http_status_code = 500  # Trigger Mollie retry
        else:
            frappe.logger().info(f"✅ Webhook processed successfully: {payment_id}")

        # A non-2xx without status=="error" is the service's 503 (Mollie unreachable):
        # the caller only sees the ack, so the operator needs the Error Log row.
        failed = (frappe.local.response.get("http_status_code") or 200) >= 400
        return _ack_with_error_log(messages_before, result if failed else None, payment_id)

    except WebhookRateLimitExceeded:
        # Return 429 to signal Mollie to retry later
        frappe.response.http_status_code = 429
        del frappe.local.message_log[messages_before:]
        return {"status": "rate_limited"}

    except (MollieWebhookError, MolliePaymentError) as e:
        _log_exception_once("Mollie Webhook Error", e, payment_id)
        frappe.response.http_status_code = 400
        return _ack_with_error_log(messages_before)

    except Exception as e:
        _log_exception_once("Webhook Processing Error", e, payment_id, with_traceback=True)
        frappe.response.http_status_code = 500
        return _ack_with_error_log(messages_before)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def create_subscription():
    """
    Create a customer subscription for recurring payments.

    Expected form data:
    - customer_name: Customer full name
    - customer_email: Customer email address
    - amount: Subscription amount
    - currency: Payment currency (default: EUR)
    - interval: Payment interval (e.g., "1 month", "3 months")
    - description: Subscription description

    Returns:
        Dict with subscription creation results
    """
    try:
        # Get form data
        customer_name = frappe.form_dict.get("customer_name")
        customer_email = frappe.form_dict.get("customer_email")
        amount = frappe.form_dict.get("amount")
        currency = frappe.form_dict.get("currency", "EUR")
        interval = frappe.form_dict.get("interval")
        description = frappe.form_dict.get("description", "Recurring donation")

        if not customer_email:
            frappe.throw(_("Customer email is required"))
        if not amount:
            frappe.throw(_("Amount is required"))
        if not interval:
            frappe.throw(_("Payment interval is required"))

        # Prepare data for service
        customer_data = {"name": customer_name or customer_email, "email": customer_email}

        subscription_data = {
            "amount": {"currency": currency, "value": f"{float(amount):.2f}"},
            "interval": interval,
            "description": description,
        }

        # Create subscription using service layer
        service = CompletePaymentService()
        result = service.create_customer_subscription(customer_data, subscription_data)

        return result

    except MollieValidationError as e:
        frappe.throw(_(str(e)))
    except MolliePaymentError as e:
        frappe.log_error(f"Subscription creation error: {e}", "Subscription Creation Error")
        frappe.throw(_("Failed to create subscription. Please try again."))


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def cancel_subscription():
    """
    Cancel a subscription.

    Expected form data:
    - customer_id: Mollie customer ID
    - subscription_id: Subscription ID to cancel
    - reason: Cancellation reason (optional)

    Returns:
        Dict with cancellation results
    """
    try:
        customer_id = frappe.form_dict.get("customer_id")
        subscription_id = frappe.form_dict.get("subscription_id")
        reason = frappe.form_dict.get("reason", "Customer request")

        if not customer_id:
            frappe.throw(_("Customer ID is required"))
        if not subscription_id:
            frappe.throw(_("Subscription ID is required"))

        # Cancel subscription using service layer
        service = CompletePaymentService()
        result = service.cancel_subscription(customer_id, subscription_id, reason)

        return result

    except MolliePaymentError as e:
        frappe.log_error(f"Subscription cancellation error: {e}", "Subscription Cancellation Error")
        frappe.throw(_("Failed to cancel subscription. Please try again."))


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_payment_status():
    """
    Get the status of a payment.

    Expected form data:
    - payment_id: Mollie payment ID

    Returns:
        Dict with payment status information
    """
    try:
        payment_id = frappe.form_dict.get("payment_id")
        if not payment_id:
            frappe.throw(_("Payment ID is required"))

        # Get payment status using service layer
        service = CompletePaymentService()
        result = service.get_payment_status(payment_id)

        return result

    except MolliePaymentError as e:
        frappe.log_error(f"Payment status error: {e}", "Payment Status Error")
        frappe.throw(_("Failed to get payment status. Please try again."))


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_client_info():
    """
    Get information about the Mollie client configuration.

    Returns:
        Dict with client configuration information
    """
    try:
        service = CompletePaymentService()
        result = service.get_client_info()
        return result

    except Exception as e:
        frappe.log_error(f"Client info error: {e}", "Client Info Error")
        frappe.throw(_("Failed to get client information"))


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def test_webhook_processing():
    """
    Test endpoint for webhook processing (development only).

    Expected form data:
    - payment_id: Test payment ID

    Returns:
        Dict with test results
    """
    try:
        if not frappe.conf.developer_mode:
            frappe.throw(_("Test endpoint only available in developer mode"))

        payment_id = frappe.form_dict.get("payment_id")
        if not payment_id:
            frappe.throw(_("Payment ID is required"))

        frappe.logger().info(f"🧪 Testing webhook processing for: {payment_id}")

        # Test webhook processing
        service = CompletePaymentService()
        result = service.process_webhook(payment_id)

        return {
            "status": "test_success",
            "payment_id": payment_id,
            "result": result,
            "message": "Test webhook processing completed",
        }

    except Exception as e:
        frappe.log_error(f"Test webhook error: {e}", "Test Webhook Error")
        return {"status": "test_error", "message": str(e)}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def initiate_refund():
    """
    Manually initiate a refund for a payment.

    Expected form data:
    - payment_id: Mollie payment ID to refund
    - amount: Refund amount (optional, defaults to full amount)
    - description: Refund description (optional)

    Returns:
        Dict with refund initiation results
    """
    try:
        # Permission check: @high_security_api only confirms the caller's role
        # profile clears SecurityLevel.HIGH in general -- a population that
        # includes Chapter Board Member and Staff, not just Treasurer/Admin
        # tiers. This function has no local Payment Entry/Donation lookup of
        # its own to gate on, so it reuses the same domain-specific role check
        # refund_utility.py's initiate_refund() applies (#968/#1021); nothing
        # here depends on a specific document, so the check is a direct fit
        # rather than a doc-scoped one. See #1017.
        if not validate_refund_permissions():
            frappe.throw(_("You do not have permission to process refunds"), frappe.PermissionError)

        payment_id = frappe.form_dict.get("payment_id")
        amount = frappe.form_dict.get("amount")
        description = frappe.form_dict.get("description", "Manual refund")

        if not payment_id:
            frappe.throw(_("Payment ID is required"))

        # Use unified system for refund creation
        from ..core.client import MollieClient

        # Prepare refund data
        refund_data = {"description": description}
        if amount:
            refund_data["amount"] = {"currency": "EUR", "value": f"{float(amount):.2f}"}

        # Create refund using unified client
        client = MollieClient()
        refund = client.create_refund(payment_id, refund_data)

        return {
            "status": "success",
            "refund_id": refund.id,
            "payment_id": payment_id,
            "amount": extract_amount_value(refund.amount),
            "message": "Refund initiated successfully",
        }

    except MolliePaymentError as e:
        frappe.log_error(f"Refund initiation error: {e}", "Refund Initiation Error")
        frappe.throw(_("Failed to initiate refund. Please try again."))

    except (frappe.ValidationError, frappe.PermissionError):
        # Preserve the body's own deliberate refusal (e.g. "Payment ID is
        # required") instead of masking it as an "internal" error below (#374).
        raise

    except Exception as e:
        frappe.log_error(f"Unexpected refund error: {e}", "Refund Processing Error")
        frappe.throw(_("Internal refund processing error"))
