# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Ponto Webhook Handler

Receives and processes webhook events from Ponto/Ibanity.

Supported event types:
- pontoConnect.synchronization.succeeded - New transactions available
- pontoConnect.synchronization.failed - Sync failed
- pontoConnect.synchronization.succeededWithoutChange - No new transactions
- pontoConnect.account.detailsUpdated - Account details changed
- pontoConnect.account.transactionsCreated - New transactions created
- pontoConnect.account.transactionsUpdated - Transactions updated
- pontoConnect.integration.accountAdded - New account linked
- pontoConnect.integration.accountRevoked - Account unlinked
- pontoConnect.paymentRequest.closed - Payment request reached final status

Usage:
    Configure webhook URL in Ponto dashboard:
    https://your-site.com/api/method/verenigingen.verenigingen_payments.ponto.api.webhook.handle_ponto_webhook

Note:
    Webhooks in Ponto may not require manual secret configuration.
    Signature verification uses JWT with JWKS public keys from Ibanity.

Architecture:
    This module was split into three files (HIGH-4 PSP Integration Consolidation):
    - webhook.py: Entry point, routing, and configuration (this file)
    - webhook_handlers.py: Event-specific handlers
    - webhook_utils.py: Extraction/parsing utilities
"""

import json
from typing import Any, Dict, Optional

import frappe
from frappe import _
from frappe.utils import now_datetime

from verenigingen.utils.security.api_security_framework import OperationType, public_api
from verenigingen.utils.webhook.logging import create_webhook_log
from verenigingen.utils.webhook_rate_limiter import WebhookRateLimitExceeded, get_webhook_rate_limiter
from verenigingen.verenigingen_payments.ponto.exceptions import PontoWebhookError
from verenigingen.verenigingen_payments.ponto.utils.webhook_security import verify_ponto_webhook

# Import handlers from split module
from .webhook_handlers import (
    handle_account_added,
    handle_account_revoked,
    handle_account_updated,
    handle_payment_initiation_closed,
    handle_payment_initiation_updated,
    handle_payment_request_closed,
    handle_periodic_payment_closed,
    handle_periodic_payment_execution,
    handle_periodic_payment_updated,
    handle_sync_failed,
    handle_sync_no_change,
    handle_sync_succeeded,
    handle_transactions_created,
    handle_transactions_updated,
)

# Import utilities from split module
from .webhook_utils import extract_event_type


def _create_webhook_log(
    webhook_id: str,
    webhook_type: str,
    raw_payload: str,
    status: str = "success",
    processing_result: str = None,
    error_details: str = None,
) -> Optional[str]:
    """
    Create a Webhook Processing Log entry.

    This is a thin wrapper around the unified create_webhook_log function
    from verenigingen.utils.webhook.logging for backwards compatibility.

    Args:
        webhook_id: Unique identifier for the webhook (e.g., event ID from Ponto)
        webhook_type: Type of webhook (ponto_sync, ponto_payment, ponto_account)
        raw_payload: Original webhook payload as string
        status: Processing status (success, error, ignored)
        processing_result: JSON string with processing result details
        error_details: Error message if status is error

    Returns:
        Name of created log document or None if logging failed
    """
    return create_webhook_log(
        webhook_id=webhook_id,
        webhook_type=webhook_type,
        raw_payload=raw_payload,
        status=status,
        processing_result=processing_result,
        error_details=error_details,
        auto_commit=True,
    )


def _get_webhook_type_from_event(event_type: str) -> str:
    """Map Ponto event type to webhook log type."""
    if not event_type:
        return "ponto_sync"

    if "payment" in event_type.lower():
        return "ponto_payment"
    elif "account" in event_type.lower() or "integration" in event_type.lower():
        return "ponto_account"
    else:
        return "ponto_sync"


def _update_account_sync_status(
    account_id: str,
    status: str = "OK",
    error: str = None,
) -> bool:
    """
    Update the sync status on the Ponto Bank Account Mapping atomically.

    Uses direct database updates to avoid read-modify-write race conditions
    when multiple webhooks arrive concurrently.

    Args:
        account_id: Ponto account UUID
        status: Sync status - "OK", "Failed", or "Needs Re-authorization"
        error: Error message if status is Failed

    Returns:
        True if updated, False if account mapping not found
    """
    try:
        # Check if mapping exists first
        mapping_name = frappe.db.get_value(
            "Ponto Bank Account Mapping", {"parent": "Ponto Settings", "ponto_account_id": account_id}, "name"
        )

        if not mapping_name:
            frappe.logger().warning(f"No bank account mapping found for Ponto account {account_id}")
            return False

        # Build atomic update based on status
        update_fields = {"sync_status": status}

        if status == "OK":
            update_fields["last_sync_time"] = now_datetime()
            # Clear error on successful sync
            update_fields["last_sync_error"] = None
        elif status in ("Failed", "Needs Re-authorization"):
            update_fields["last_sync_failure_time"] = now_datetime()
            update_fields["last_sync_error"] = error

        # Atomic update - no read-modify-write race condition
        frappe.db.set_value("Ponto Bank Account Mapping", mapping_name, update_fields, update_modified=False)
        frappe.db.commit()

        frappe.logger().debug(f"Updated sync status for account {account_id}: {status}")
        return True

    except Exception as e:
        frappe.logger().error(f"Failed to update account sync status: {e}")
        return False


# Ponto Connect webhook event types
class PontoEventTypes:
    """Constants for Ponto webhook event types."""

    # Synchronization events
    SYNC_SUCCEEDED = "pontoConnect.synchronization.succeeded"
    SYNC_FAILED = "pontoConnect.synchronization.failed"
    SYNC_NO_CHANGE = "pontoConnect.synchronization.succeededWithoutChange"

    # Account events
    ACCOUNT_DETAILS_UPDATED = "pontoConnect.account.detailsUpdated"
    ACCOUNT_TRANSACTIONS_CREATED = "pontoConnect.account.transactionsCreated"
    ACCOUNT_TRANSACTIONS_UPDATED = "pontoConnect.account.transactionsUpdated"

    # Integration events
    INTEGRATION_ACCOUNT_ADDED = "pontoConnect.integration.accountAdded"
    INTEGRATION_ACCOUNT_REVOKED = "pontoConnect.integration.accountRevoked"
    INTEGRATION_CREATED = "pontoConnect.integration.created"
    INTEGRATION_REVOKED = "pontoConnect.integration.revoked"

    # Organization events
    ORGANIZATION_BLOCKED = "pontoConnect.organization.blocked"
    ORGANIZATION_UNBLOCKED = "pontoConnect.organization.unblocked"

    # Payment events (outgoing payments)
    PAYMENT_REQUEST_CLOSED = "pontoConnect.paymentRequest.closed"

    # Payment Initiation Request events (incoming payments / betaalverzoek)
    PAYMENT_INITIATION_STATUS_UPDATED = "pontoConnect.paymentInitiationRequest.statusUpdated"
    PAYMENT_INITIATION_CLOSED = "pontoConnect.paymentInitiationRequest.closed"

    # Periodic Payment Initiation Request events (recurring betaalverzoek)
    PERIODIC_PAYMENT_STATUS_UPDATED = "pontoConnect.periodicPaymentInitiationRequest.statusUpdated"
    PERIODIC_PAYMENT_CLOSED = "pontoConnect.periodicPaymentInitiationRequest.closed"
    PERIODIC_PAYMENT_EXECUTION = "pontoConnect.periodicPaymentInitiationRequest.executed"


@frappe.whitelist(allow_guest=True, methods=["POST"])
@public_api(operation_type=OperationType.WEBHOOK_PROCESSING)
def handle_ponto_webhook():
    """
    Handle incoming Ponto webhook events.

    This endpoint receives webhook notifications from Ponto/Ibanity
    about synchronization events, account changes, and payment updates.

    The webhook signature is verified using JWT/JWKS before processing.

    Returns:
        dict: Processing result with status
    """
    try:
        # STEP 0: Rate limiting (before any expensive operations)
        ip_address = frappe.local.request_ip if hasattr(frappe.local, "request_ip") else "unknown"
        # Use event ID from headers if available for rate limit tracking
        webhook_id = frappe.request.headers.get("X-Event-ID") if frappe.request else None

        rate_limiter = get_webhook_rate_limiter()
        is_allowed, reason = rate_limiter.check_rate_limit(ip_address, webhook_id)

        if not is_allowed:
            frappe.log_error(
                f"Ponto webhook rate limited: IP={ip_address}, webhook_id={webhook_id}, reason={reason}",
                "Ponto Webhook Rate Limit",
            )
            raise WebhookRateLimitExceeded(f"Rate limit exceeded: {reason}")

        # Get raw request data
        payload = frappe.request.get_data()
        signature = frappe.request.headers.get("Signature")

        # Check if webhooks are enabled
        settings = frappe.get_single("Ponto Settings")
        if not settings.enable_webhooks:
            frappe.logger().warning("Ponto webhook received but webhooks are disabled")
            return {"status": "ignored", "reason": "webhooks_disabled"}

        # Verify webhook signature (JWT/JWKS)
        # SECURITY: When require_webhook_signature is enabled, reject unsigned requests
        require_signature = getattr(settings, "require_webhook_signature", True)
        claims = None

        if signature:
            try:
                claims = verify_ponto_webhook(payload, signature)
                frappe.logger().debug(f"Webhook signature verified: {claims}")
            except PontoWebhookError as e:
                frappe.logger().error(f"Webhook signature verification failed: {e}")
                frappe.log_error(
                    title="Ponto webhook signature failed",
                    message=str(e),
                )
                frappe.local.response["http_status_code"] = 401
                return {"status": "error", "message": "Signature verification failed"}
        elif require_signature:
            # No signature provided but signature is required - reject the request
            frappe.logger().warning(
                "Ponto webhook rejected: no signature provided but require_webhook_signature is enabled"
            )
            frappe.log_error(
                title="Ponto webhook rejected - missing signature",
                message="Webhook request received without signature while require_webhook_signature is enabled. "
                "This could indicate an attack attempt or misconfigured webhook source.",
            )
            frappe.local.response["http_status_code"] = 401
            return {"status": "error", "message": "Webhook signature required"}
        else:
            # No signature provided but signatures not required (development mode)
            frappe.logger().warning(
                "Ponto webhook received without signature - INSECURE MODE. "
                "Enable require_webhook_signature in Ponto Settings for production."
            )

        # Parse the webhook payload
        try:
            event_data = json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError as e:
            frappe.logger().error(f"Invalid webhook payload: {e}")
            frappe.local.response["http_status_code"] = 400
            return {"status": "error", "message": "Invalid JSON payload"}

        # Extract event type
        # Ponto uses JSON:API format, so event type may be in different locations
        event_type = extract_event_type(event_data)

        # Extract webhook ID for logging (use data.id or generate one)
        webhook_id = event_data.get("data", {}).get("id", "") or f"ponto_{frappe.utils.now()}"
        raw_payload_str = payload.decode("utf-8") if isinstance(payload, bytes) else str(payload)

        if not event_type:
            frappe.logger().warning(f"Unknown webhook event format: {event_data}")
            _create_webhook_log(
                webhook_id=webhook_id,
                webhook_type="ponto_sync",
                raw_payload=raw_payload_str,
                status="error",
                error_details="Unknown event format",
            )
            frappe.local.response["http_status_code"] = 400
            return {"status": "error", "message": "Unknown event format"}

        # Log the webhook receipt
        frappe.logger().info(f"Ponto webhook received: {event_type}")

        # Process the event
        result = process_webhook_event(event_type, event_data)

        # Log successful processing
        _create_webhook_log(
            webhook_id=webhook_id,
            webhook_type=_get_webhook_type_from_event(event_type),
            raw_payload=raw_payload_str,
            status="success",
            processing_result=json.dumps(result, default=str),
        )

        return {
            "status": "success",
            "event_type": event_type,
            "result": result,
        }

    except WebhookRateLimitExceeded as e:
        # Return 429 to signal Ponto/Ibanity to retry later
        frappe.local.response["http_status_code"] = 429
        return {"status": "rate_limited", "message": str(e)}

    except PontoWebhookError as e:
        frappe.logger().error(f"Ponto webhook error: {e}")
        frappe.log_error(
            title="Ponto webhook processing error",
            message=str(e),
        )
        # Log the error
        try:
            raw_payload_str = payload.decode("utf-8") if isinstance(payload, bytes) else str(payload)
            _create_webhook_log(
                webhook_id=f"ponto_error_{frappe.utils.now()}",
                webhook_type="ponto_sync",
                raw_payload=raw_payload_str,
                status="error",
                error_details=str(e),
            )
        except Exception:
            pass  # Don't fail on logging errors
        frappe.local.response["http_status_code"] = 400
        return {"status": "error", "message": str(e)}

    except Exception as e:
        frappe.logger().error(f"Unexpected Ponto webhook error: {e}")
        frappe.log_error(
            title="Ponto webhook unexpected error",
            message=str(e),
        )
        # Log the error
        try:
            raw_payload_str = payload.decode("utf-8") if isinstance(payload, bytes) else str(payload)
            _create_webhook_log(
                webhook_id=f"ponto_error_{frappe.utils.now()}",
                webhook_type="ponto_sync",
                raw_payload=raw_payload_str,
                status="error",
                error_details=str(e),
            )
        except Exception:
            pass  # Don't fail on logging errors
        frappe.local.response["http_status_code"] = 500
        return {"status": "error", "message": "Internal server error"}


def process_webhook_event(event_type: str, event_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process a webhook event based on its type.

    Args:
        event_type: The type of webhook event
        event_data: The full event payload

    Returns:
        Dict with processing result
    """
    # Route to appropriate handler
    # Note: Sync handlers need the update_account_sync_status_fn callback
    handlers = {
        PontoEventTypes.SYNC_SUCCEEDED: lambda data: handle_sync_succeeded(
            data, update_account_sync_status_fn=_update_account_sync_status
        ),
        PontoEventTypes.SYNC_FAILED: lambda data: handle_sync_failed(
            data, update_account_sync_status_fn=_update_account_sync_status
        ),
        PontoEventTypes.SYNC_NO_CHANGE: handle_sync_no_change,
        PontoEventTypes.ACCOUNT_TRANSACTIONS_CREATED: handle_transactions_created,
        PontoEventTypes.ACCOUNT_TRANSACTIONS_UPDATED: handle_transactions_updated,
        PontoEventTypes.ACCOUNT_DETAILS_UPDATED: handle_account_updated,
        PontoEventTypes.INTEGRATION_ACCOUNT_ADDED: handle_account_added,
        PontoEventTypes.INTEGRATION_ACCOUNT_REVOKED: handle_account_revoked,
        # Outgoing payment events
        PontoEventTypes.PAYMENT_REQUEST_CLOSED: handle_payment_request_closed,
        # Incoming payment / betaalverzoek events
        PontoEventTypes.PAYMENT_INITIATION_STATUS_UPDATED: handle_payment_initiation_updated,
        PontoEventTypes.PAYMENT_INITIATION_CLOSED: handle_payment_initiation_closed,
        # Periodic payment / recurring betaalverzoek events
        PontoEventTypes.PERIODIC_PAYMENT_STATUS_UPDATED: handle_periodic_payment_updated,
        PontoEventTypes.PERIODIC_PAYMENT_CLOSED: handle_periodic_payment_closed,
        PontoEventTypes.PERIODIC_PAYMENT_EXECUTION: handle_periodic_payment_execution,
    }

    handler = handlers.get(event_type)

    if handler:
        return handler(event_data)
    else:
        # Unknown event type - log and acknowledge
        frappe.logger().info(f"Unhandled Ponto webhook event type: {event_type}")
        return {"handled": False, "reason": "unknown_event_type"}


# Re-export utilities for backwards compatibility
# (Any code importing directly from webhook.py will still work)
from .webhook_utils import (  # noqa: E402, F401
    extract_account_id,
    extract_debtor_info,
    extract_event_type,
    extract_payment_link_id,
    extract_payment_request_id,
    extract_payment_status,
)
