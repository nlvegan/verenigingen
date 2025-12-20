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
"""

import hashlib
import json
from typing import Any, Dict, Optional

import frappe
from frappe import _
from frappe.utils import now_datetime

from verenigingen.utils.security.api_security_framework import OperationType, public_api
from verenigingen.verenigingen_payments.ponto.exceptions import PontoWebhookError
from verenigingen.verenigingen_payments.ponto.utils.webhook_security import verify_ponto_webhook


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
    try:
        # Create a hash to detect duplicate webhooks
        webhook_hash = hashlib.sha256(f"{webhook_id}:{raw_payload}".encode()).hexdigest()

        # Check for duplicate
        existing = frappe.db.exists("Webhook Processing Log", {"webhook_hash": webhook_hash})
        if existing:
            frappe.logger().debug(f"Duplicate webhook detected: {webhook_id}")
            return None

        log = frappe.new_doc("Webhook Processing Log")
        log.webhook_id = webhook_id[:140] if webhook_id else "unknown"  # Truncate to field limit
        log.webhook_type = webhook_type
        log.webhook_hash = webhook_hash
        log.processed_at = now_datetime()
        log.status = status
        log.raw_payload = raw_payload

        if processing_result:
            log.processing_result = processing_result

        if error_details:
            log.error_details = error_details[:65535] if len(error_details) > 65535 else error_details

        # SECURITY JUSTIFICATION: Webhook logging is a system audit function during
        # webhook processing. No user session during webhook callbacks.
        log.insert(ignore_permissions=True)
        frappe.db.commit()

        return log.name

    except Exception as e:
        frappe.logger().error(f"Failed to create webhook log: {e}")
        return None


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


def extract_event_type(event_data: Dict[str, Any]) -> Optional[str]:
    """
    Extract the event type from webhook payload.

    Ponto uses JSON:API format, so the event type could be:
    - In `data.type` field
    - In `data.attributes.eventType` field
    - In a top-level `type` field

    Args:
        event_data: Parsed webhook payload

    Returns:
        Event type string or None if not found
    """
    # Try JSON:API data.type format
    if "data" in event_data:
        data = event_data["data"]
        if isinstance(data, dict):
            # Check data.type
            if "type" in data:
                return data["type"]
            # Check data.attributes.eventType
            if "attributes" in data and "eventType" in data["attributes"]:
                return data["attributes"]["eventType"]

    # Try top-level type
    if "type" in event_data:
        return event_data["type"]

    # Try eventType directly
    if "eventType" in event_data:
        return event_data["eventType"]

    return None


def extract_account_id(event_data: Dict[str, Any]) -> Optional[str]:
    """
    Extract the account ID from webhook payload.

    Args:
        event_data: Parsed webhook payload

    Returns:
        Account ID string or None if not found
    """
    if "data" in event_data:
        data = event_data["data"]
        if isinstance(data, dict):
            # Check relationships.account
            if "relationships" in data:
                account_rel = data["relationships"].get("account", {})
                if "data" in account_rel:
                    return account_rel["data"].get("id")
            # Check attributes.accountId
            if "attributes" in data:
                return data["attributes"].get("accountId")

    return None


def extract_payment_request_id(event_data: Dict[str, Any]) -> Optional[str]:
    """
    Extract the payment request ID from webhook payload.

    Args:
        event_data: Parsed webhook payload

    Returns:
        Payment request ID string or None if not found
    """
    if "data" in event_data:
        data = event_data["data"]
        if isinstance(data, dict):
            # Check if this is a payment request event (data.id)
            if data.get("type") == "pontoConnect.paymentRequest.closed":
                return data.get("id")
            # Check relationships.paymentInitiationRequest
            if "relationships" in data:
                payment_rel = data["relationships"].get("paymentInitiationRequest", {})
                if "data" in payment_rel:
                    return payment_rel["data"].get("id")
            # Check attributes.paymentInitiationRequestId
            if "attributes" in data:
                return data["attributes"].get("paymentInitiationRequestId")

    return None


def extract_payment_status(event_data: Dict[str, Any]) -> Optional[str]:
    """
    Extract the payment status from webhook payload.

    Args:
        event_data: Parsed webhook payload

    Returns:
        Payment status string or None if not found
    """
    if "data" in event_data and "attributes" in event_data["data"]:
        attrs = event_data["data"]["attributes"]
        return attrs.get("status")


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
    handlers = {
        PontoEventTypes.SYNC_SUCCEEDED: handle_sync_succeeded,
        PontoEventTypes.SYNC_FAILED: handle_sync_failed,
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


def handle_sync_succeeded(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """Handle synchronization succeeded event."""
    account_id = extract_account_id(event_data)
    frappe.logger().info(f"Ponto sync succeeded for account {account_id}")

    # Trigger transaction import
    if account_id:
        # Queue transaction import job
        frappe.enqueue(
            "verenigingen.verenigingen_payments.ponto.services.transaction_import_service.import_new_transactions",
            account_id=account_id,
            queue="short",
            timeout=300,
        )
        return {"handled": True, "action": "transaction_import_queued", "account_id": account_id}

    return {"handled": True, "action": "logged"}


def handle_sync_failed(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """Handle synchronization failed event."""
    account_id = extract_account_id(event_data)

    # Extract error details
    error_info = {}
    if "data" in event_data and "attributes" in event_data["data"]:
        attrs = event_data["data"]["attributes"]
        error_info = {
            "error_code": attrs.get("errorCode"),
            "error_message": attrs.get("errorMessage"),
        }

    frappe.logger().warning(f"Ponto sync failed for account {account_id}: {error_info}")

    # Log error for admin review
    frappe.log_error(
        title=f"Ponto sync failed: {account_id}",
        message=f"Synchronization failed. Error: {error_info}",
    )

    return {"handled": True, "action": "error_logged", "error": error_info}


def handle_sync_no_change(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """Handle synchronization succeeded without change event."""
    account_id = extract_account_id(event_data)
    frappe.logger().debug(f"Ponto sync completed with no changes for account {account_id}")
    return {"handled": True, "action": "no_action_needed"}


def handle_transactions_created(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """Handle new transactions created event."""
    account_id = extract_account_id(event_data)
    frappe.logger().info(f"New Ponto transactions created for account {account_id}")

    if account_id:
        # Queue transaction import
        frappe.enqueue(
            "verenigingen.verenigingen_payments.ponto.services.transaction_import_service.import_new_transactions",
            account_id=account_id,
            queue="short",
            timeout=300,
        )
        return {"handled": True, "action": "transaction_import_queued"}

    return {"handled": True, "action": "logged"}


def handle_transactions_updated(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """Handle transactions updated event."""
    account_id = extract_account_id(event_data)
    frappe.logger().info(f"Ponto transactions updated for account {account_id}")

    # Transaction updates are less common - just log for now
    # Could implement transaction reconciliation here
    return {"handled": True, "action": "logged"}


def handle_account_updated(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """Handle account details updated event."""
    account_id = extract_account_id(event_data)
    frappe.logger().info(f"Ponto account details updated: {account_id}")

    # Could refresh account info in settings
    return {"handled": True, "action": "logged"}


def handle_account_added(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """Handle new account added to integration event."""
    account_id = extract_account_id(event_data)
    frappe.logger().info(f"New Ponto account added: {account_id}")

    # Could trigger account refresh
    return {"handled": True, "action": "logged", "account_id": account_id}


def handle_account_revoked(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """Handle account revoked from integration event."""
    account_id = extract_account_id(event_data)
    frappe.logger().warning(f"Ponto account revoked: {account_id}")

    # Log for admin attention
    frappe.log_error(
        title="Ponto account revoked",
        message=f"Account {account_id} has been revoked from Ponto integration. Please review and update settings.",
    )

    return {"handled": True, "action": "admin_notified", "account_id": account_id}


def handle_payment_request_closed(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle payment request closed event.

    This event is sent when a payment request reaches a final status
    (executed, rejected, failed, cancelled).

    Updates the corresponding Ponto Payment Request document status.
    Uses explicit transaction boundaries for data integrity.
    """
    payment_id = extract_payment_request_id(event_data)
    new_status = extract_payment_status(event_data)

    frappe.logger().info(f"Ponto payment request closed: {payment_id} with status {new_status}")

    if not payment_id:
        frappe.logger().warning("Payment request closed event without payment ID")
        return {"handled": True, "action": "logged", "reason": "no_payment_id"}

    # Find the Ponto Payment Request by ponto_payment_id
    payment_requests = frappe.get_all(
        "Ponto Payment Request",
        filters={"ponto_payment_id": payment_id},
        fields=["name"],
    )

    if not payment_requests:
        frappe.logger().warning(f"No Ponto Payment Request found for payment ID: {payment_id}")
        return {"handled": True, "action": "logged", "reason": "payment_request_not_found"}

    # Map Ponto status to our status
    status_map = {
        "pending": "Pending",
        "unsigned": "Pending",
        "signed": "Signed",
        "executed": "Executed",
        "rejected": "Rejected",
        "failed": "Failed",
        "cancelled": "Cancelled",
    }

    mapped_status = status_map.get(new_status.lower() if new_status else "", None)

    if mapped_status:
        updated_requests = []
        failed_requests = []

        for pr in payment_requests:
            # Use savepoint for each update to isolate failures
            savepoint_name = f"payment_status_{pr.name}"
            try:
                frappe.db.savepoint(savepoint_name)
                doc = frappe.get_doc("Ponto Payment Request", pr.name)
                doc.update_status_from_webhook(mapped_status)
                frappe.logger().info(f"Updated Ponto Payment Request {pr.name} to status {mapped_status}")
                updated_requests.append(pr.name)
            except Exception as e:
                frappe.db.rollback(save_point=savepoint_name)
                frappe.logger().error(f"Failed to update Ponto Payment Request {pr.name}: {e}")
                frappe.log_error(
                    title=f"Payment webhook status update failed: {pr.name}",
                    message=str(e),
                )
                failed_requests.append(pr.name)

        return {
            "handled": True,
            "action": "status_updated",
            "payment_id": payment_id,
            "new_status": mapped_status,
            "updated_requests": updated_requests,
            "failed_requests": failed_requests if failed_requests else None,
        }

    return {"handled": True, "action": "logged", "reason": "unknown_status"}


def extract_payment_link_id(event_data: Dict[str, Any]) -> Optional[str]:
    """
    Extract the payment initiation request ID from webhook payload.

    For betaalverzoek (incoming payment requests).

    Args:
        event_data: Parsed webhook payload

    Returns:
        Payment initiation request ID string or None if not found
    """
    if "data" in event_data:
        data = event_data["data"]
        if isinstance(data, dict):
            # The ID might be directly in the data
            if "id" in data:
                return data["id"]
            # Or in relationships
            if "relationships" in data:
                pir_rel = data["relationships"].get("paymentInitiationRequest", {})
                if "data" in pir_rel:
                    return pir_rel["data"].get("id")

    return None


def extract_debtor_info(event_data: Dict[str, Any]) -> Dict[str, str]:
    """
    Extract debtor information from webhook payload.

    Args:
        event_data: Parsed webhook payload

    Returns:
        Dict with debtor details (name, iban, bank)
    """
    debtor_info = {}
    if "data" in event_data and "attributes" in event_data["data"]:
        attrs = event_data["data"]["attributes"]
        if attrs.get("debtorName"):
            debtor_info["name"] = attrs["debtorName"]
        if attrs.get("debtorAccountReference"):
            debtor_info["iban"] = attrs["debtorAccountReference"]
        if attrs.get("debtorAgent"):
            debtor_info["bank"] = attrs["debtorAgent"]
    return debtor_info


def _update_payment_link_status(
    request_id: str,
    new_status: str,
    debtor_info: dict = None,
    is_periodic: bool = False,
) -> Dict[str, Any]:
    """
    Common helper to update Ponto Payment Link status.

    Uses explicit transaction boundaries (savepoints) for data integrity.
    Each payment link update is isolated so failures don't affect others.

    Args:
        request_id: Ponto request ID
        new_status: New status value
        debtor_info: Optional debtor details
        is_periodic: Whether this is a periodic payment

    Returns:
        Dict with update result
    """
    # Find the Ponto Payment Link by ponto_request_id
    payment_links = frappe.get_all(
        "Ponto Payment Link",
        filters={"ponto_request_id": request_id},
        fields=["name"],
    )

    if not payment_links:
        frappe.logger().warning(f"No Ponto Payment Link found for request ID: {request_id}")
        return {"handled": True, "action": "logged", "reason": "payment_link_not_found"}

    # Map Ponto status to our status
    status_map = {
        "pending": "Pending Authorization",
        "unsigned": "Pending Authorization",
        "signed": "Authorized",
        "authorized": "Authorized",
        "executed": "Executed",
        "rejected": "Rejected",
        "failed": "Failed",
        "cancelled": "Cancelled",
        "expired": "Expired",
    }

    mapped_status = status_map.get(new_status.lower() if new_status else "", None)

    if mapped_status:
        updated_links = []
        failed_links = []

        for pl in payment_links:
            # Use savepoint for each update to isolate failures
            savepoint_name = f"payment_link_status_{pl.name}"
            try:
                frappe.db.savepoint(savepoint_name)
                doc = frappe.get_doc("Ponto Payment Link", pl.name)
                doc.update_status_from_webhook(mapped_status, debtor_info)
                frappe.logger().info(f"Updated Ponto Payment Link {pl.name} to status {mapped_status}")
                updated_links.append(pl.name)
            except Exception as e:
                frappe.db.rollback(save_point=savepoint_name)
                frappe.logger().error(f"Failed to update Ponto Payment Link {pl.name}: {e}")
                frappe.log_error(
                    title=f"Payment link webhook status update failed: {pl.name}",
                    message=str(e),
                )
                failed_links.append(pl.name)

        return {
            "handled": True,
            "action": "status_updated",
            "request_id": request_id,
            "new_status": mapped_status,
            "updated_links": updated_links,
            "failed_links": failed_links if failed_links else None,
        }

    return {"handled": True, "action": "logged", "reason": "unknown_status"}


def handle_payment_initiation_updated(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle payment initiation request status updated event.

    This event is sent when a one-time betaalverzoek status changes.
    """
    request_id = extract_payment_link_id(event_data)
    new_status = extract_payment_status(event_data)
    debtor_info = extract_debtor_info(event_data)

    frappe.logger().info(f"Ponto payment initiation updated: {request_id} to status {new_status}")

    if not request_id:
        frappe.logger().warning("Payment initiation updated event without request ID")
        return {"handled": True, "action": "logged", "reason": "no_request_id"}

    return _update_payment_link_status(request_id, new_status, debtor_info, is_periodic=False)


def handle_payment_initiation_closed(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle payment initiation request closed event.

    This event is sent when a one-time betaalverzoek reaches final status.
    """
    request_id = extract_payment_link_id(event_data)
    new_status = extract_payment_status(event_data)
    debtor_info = extract_debtor_info(event_data)

    frappe.logger().info(f"Ponto payment initiation closed: {request_id} with status {new_status}")

    if not request_id:
        frappe.logger().warning("Payment initiation closed event without request ID")
        return {"handled": True, "action": "logged", "reason": "no_request_id"}

    return _update_payment_link_status(request_id, new_status, debtor_info, is_periodic=False)


def handle_periodic_payment_updated(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle periodic payment initiation request status updated event.

    This event is sent when a recurring betaalverzoek status changes.
    """
    request_id = extract_payment_link_id(event_data)
    new_status = extract_payment_status(event_data)
    debtor_info = extract_debtor_info(event_data)

    frappe.logger().info(f"Ponto periodic payment updated: {request_id} to status {new_status}")

    if not request_id:
        frappe.logger().warning("Periodic payment updated event without request ID")
        return {"handled": True, "action": "logged", "reason": "no_request_id"}

    return _update_payment_link_status(request_id, new_status, debtor_info, is_periodic=True)


def handle_periodic_payment_closed(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle periodic payment initiation request closed event.

    This event is sent when a recurring betaalverzoek reaches final status.
    """
    request_id = extract_payment_link_id(event_data)
    new_status = extract_payment_status(event_data)
    debtor_info = extract_debtor_info(event_data)

    frappe.logger().info(f"Ponto periodic payment closed: {request_id} with status {new_status}")

    if not request_id:
        frappe.logger().warning("Periodic payment closed event without request ID")
        return {"handled": True, "action": "logged", "reason": "no_request_id"}

    return _update_payment_link_status(request_id, new_status, debtor_info, is_periodic=True)


def handle_periodic_payment_execution(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle periodic payment execution event.

    This event is sent each time a recurring payment is executed.
    Used to track individual payment executions in a standing order.

    Uses explicit transaction boundaries (savepoints) for data integrity.
    Each payment link update is atomic - counter, payment processing, and
    debtor info updates are committed together or rolled back together.
    """
    request_id = extract_payment_link_id(event_data)
    debtor_info = extract_debtor_info(event_data)

    frappe.logger().info(f"Ponto periodic payment executed: {request_id}")

    if not request_id:
        frappe.logger().warning("Periodic payment execution event without request ID")
        return {"handled": True, "action": "logged", "reason": "no_request_id"}

    # Find and update the payment link
    payment_links = frappe.get_all(
        "Ponto Payment Link",
        filters={"ponto_request_id": request_id},
        fields=["name"],
    )

    if not payment_links:
        frappe.logger().warning(f"No Ponto Payment Link found for request ID: {request_id}")
        return {"handled": True, "action": "logged", "reason": "payment_link_not_found"}

    updated_links = []
    failed_links = []

    for pl in payment_links:
        # Use savepoint for each payment link - all operations within are atomic
        savepoint_name = f"periodic_payment_{pl.name}"
        try:
            frappe.db.savepoint(savepoint_name)

            doc = frappe.get_doc("Ponto Payment Link", pl.name)

            # Increment payment counter
            doc.increment_payment_count()

            # Process the individual payment
            doc.process_payment_received()

            # Update debtor info if provided
            if debtor_info:
                if debtor_info.get("name"):
                    doc.debtor_name = debtor_info["name"]
                if debtor_info.get("iban"):
                    doc.debtor_iban = debtor_info["iban"]
                if debtor_info.get("bank"):
                    doc.debtor_bank = debtor_info["bank"]
                # SECURITY JUSTIFICATION: Webhook handler processes external Ponto callbacks.
                # No user session during webhook processing. Audit trail via webhook event logs.
                doc.save(ignore_permissions=True)

            frappe.logger().info(
                f"Processed periodic payment execution for {pl.name}, "
                f"total payments: {doc.total_payments_collected}"
            )
            updated_links.append(pl.name)

        except Exception as e:
            frappe.db.rollback(save_point=savepoint_name)
            frappe.logger().error(f"Failed to process periodic payment execution for {pl.name}: {e}")
            frappe.log_error(
                title=f"Periodic payment execution failed: {pl.name}",
                message=str(e),
            )
            failed_links.append(pl.name)

    return {
        "handled": True,
        "action": "payment_processed",
        "request_id": request_id,
        "updated_links": updated_links,
        "failed_links": failed_links if failed_links else None,
    }
