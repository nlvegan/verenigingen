# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Pay.nl Webhook Handlers for ING Checkout

Handles exchange notifications from Pay.nl for:
- Order status changes (iDEAL payments)
- Mandate status changes (SEPA Direct Debit)
- Direct debit status changes

Security:
- Webhook signature verification (HMAC-SHA256) when configured
- Idempotency protection via Webhook Processing Log
- Savepoints for atomic operations
- Proper user context for background jobs

API Documentation: https://developer.pay.nl/docs/exchanges
"""

import json
from decimal import Decimal
from typing import Any, Dict, Optional

import frappe
from frappe import _

from verenigingen.utils.security.api_security_framework import OperationType, public_api
from verenigingen.utils.webhook_rate_limiter import WebhookRateLimitExceeded, get_webhook_rate_limiter
from verenigingen.verenigingen_payments.ing_checkout.utils.webhook_security import (
    INGCheckoutWebhookError,
    authenticate_webhook,
    compute_webhook_hash,
    get_webhook_user,
    is_duplicate_webhook,
    log_webhook,
    verify_ing_checkout_webhook,
)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@public_api(operation_type=OperationType.WEBHOOK_PROCESSING)
def handle_payment():
    """
    Handle Pay.nl exchange notifications for payment orders.

    This endpoint receives POST requests from Pay.nl when order status changes.
    The exchange contains the full order object with current status.

    Security:
    - Verifies webhook signature if configured
    - Checks for duplicate webhooks (idempotency)
    - Uses savepoints for atomic operations

    Expected payload structure:
    {
        "event": "status_changed",
        "type": "order",
        "version": "1",
        "id": "EX-1234-5678-9012",
        "object": {
            "id": "EX-1234-5678-9012",
            "reference": "INV-2025-001",
            "status": {"code": 100, "action": "PAID"},
            "amount": {"value": 2500, "currency": "EUR"},
            "payments": [{...}]
        }
    }

    Returns:
        JSON response with status
    """
    raw_payload = None
    try:
        # STEP 0: Rate limiting (before any expensive operations)
        ip_address = frappe.local.request_ip if hasattr(frappe.local, "request_ip") else "unknown"
        # Use event ID from form data if available
        webhook_id = frappe.form_dict.get("id") if frappe.form_dict else None

        rate_limiter = get_webhook_rate_limiter()
        is_allowed, reason = rate_limiter.check_rate_limit(ip_address, webhook_id)

        if not is_allowed:
            frappe.log_error(
                f"ING Checkout payment webhook rate limited: IP={ip_address}, webhook_id={webhook_id}, reason={reason}",
                "ING Checkout Webhook Rate Limit",
            )
            raise WebhookRateLimitExceeded(f"Rate limit exceeded: {reason}")

        # Get raw request data
        raw_payload = frappe.request.get_data()
        if not raw_payload:
            frappe.local.response["http_status_code"] = 400
            return {"status": "error", "message": "Empty request body"}

        # Verify webhook signature
        signature = frappe.request.headers.get("X-Pay-Signature") or frappe.request.headers.get("Signature")
        try:
            verify_ing_checkout_webhook(raw_payload, signature)
        except INGCheckoutWebhookError as e:
            frappe.log_error(
                title="ING Checkout webhook signature failed",
                message=f"{e.message}\nDetails: {e.details}",
            )
            frappe.local.response["http_status_code"] = 401
            return {"status": "error", "message": "Signature verification failed"}

        # Parse payload
        try:
            payload = json.loads(
                raw_payload.decode("utf-8") if isinstance(raw_payload, bytes) else raw_payload
            )
        except json.JSONDecodeError:
            frappe.local.response["http_status_code"] = 400
            return {"status": "error", "message": "Invalid JSON payload"}

        raw_payload_str = raw_payload.decode("utf-8") if isinstance(raw_payload, bytes) else str(raw_payload)

        # Extract event ID for idempotency
        event_id = payload.get("id") or payload.get("object", {}).get("id") or f"ing_{frappe.utils.now()}"

        # Check for duplicate webhook (idempotency)
        if is_duplicate_webhook(event_id, raw_payload_str):
            frappe.logger().info(f"Duplicate ING Checkout payment webhook ignored: {event_id}")
            return {"status": "duplicate", "message": "Webhook already processed"}

        # Validate payload structure
        if not payload.get("object"):
            frappe.local.response["http_status_code"] = 400
            log_webhook(
                event_id=event_id,
                webhook_type="ing_checkout_payment",
                raw_payload=raw_payload_str,
                status="error",
                error_details="Invalid webhook payload structure - missing 'object'",
            )
            return {"status": "error", "message": "Invalid webhook payload structure"}

        # Extract key fields
        order_id = payload.get("id")
        order_object = payload.get("object", {})
        reference = order_object.get("reference")
        status = order_object.get("status", {})
        status_code = status.get("code")
        status_action = status.get("action")

        frappe.logger().info(
            f"ING Checkout payment webhook: order={order_id}, reference={reference}, "
            f"status_code={status_code}, action={status_action}"
        )

        # Process the payment with savepoint for atomicity
        savepoint_name = f"ing_payment_{order_id}"
        try:
            frappe.db.savepoint(savepoint_name)
            result = _process_payment_webhook(order_id, payload)

            # Log successful processing
            log_webhook(
                event_id=event_id,
                webhook_type="ing_checkout_payment",
                raw_payload=raw_payload_str,
                status="success",
                processing_result=json.dumps(result, default=str),
            )

            return {"status": "processed", "order_id": order_id, "result": result}

        except Exception:
            frappe.db.rollback(save_point=savepoint_name)
            raise

    except WebhookRateLimitExceeded as e:
        # Return 429 to signal Pay.nl to retry later
        frappe.local.response["http_status_code"] = 429
        return {"status": "rate_limited", "message": str(e)}

    except INGCheckoutWebhookError as e:
        frappe.logger().error(f"ING Checkout webhook error: {e.message}")
        frappe.log_error(
            title="ING Checkout Webhook Error",
            message=f"{e.message}\nDetails: {e.details}",
        )
        if raw_payload:
            raw_str = raw_payload.decode("utf-8") if isinstance(raw_payload, bytes) else str(raw_payload)
            log_webhook(
                event_id=f"ing_error_{frappe.utils.now()}",
                webhook_type="ing_checkout_payment",
                raw_payload=raw_str,
                status="error",
                error_details=str(e),
            )
        frappe.local.response["http_status_code"] = 400
        return {"status": "error", "message": str(e)}

    except Exception as e:
        frappe.logger().error(f"Unexpected ING Checkout webhook error: {e}")
        frappe.log_error(
            title="ING Checkout Webhook Error",
            message=f"Error processing payment webhook: {str(e)}",
        )
        if raw_payload:
            raw_str = raw_payload.decode("utf-8") if isinstance(raw_payload, bytes) else str(raw_payload)
            log_webhook(
                event_id=f"ing_error_{frappe.utils.now()}",
                webhook_type="ing_checkout_payment",
                raw_payload=raw_str,
                status="error",
                error_details=str(e),
            )
        frappe.local.response["http_status_code"] = 500
        return {"status": "error", "message": "Internal server error"}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@public_api(operation_type=OperationType.WEBHOOK_PROCESSING)
def handle_mandate():
    """
    Handle Pay.nl exchange notifications for SEPA Direct Debit mandates.

    This endpoint receives POST requests from Pay.nl when mandate status changes.

    Returns:
        JSON response with status
    """
    raw_payload = None
    try:
        # STEP 0: Rate limiting (before any expensive operations)
        ip_address = frappe.local.request_ip if hasattr(frappe.local, "request_ip") else "unknown"
        webhook_id = frappe.form_dict.get("id") if frappe.form_dict else None

        rate_limiter = get_webhook_rate_limiter()
        is_allowed, reason = rate_limiter.check_rate_limit(ip_address, webhook_id)

        if not is_allowed:
            frappe.log_error(
                f"ING Checkout mandate webhook rate limited: IP={ip_address}, webhook_id={webhook_id}, reason={reason}",
                "ING Checkout Webhook Rate Limit",
            )
            raise WebhookRateLimitExceeded(f"Rate limit exceeded: {reason}")

        raw_payload = frappe.request.get_data()
        if not raw_payload:
            frappe.local.response["http_status_code"] = 400
            return {"status": "error", "message": "Empty request body"}

        # Verify webhook signature
        signature = frappe.request.headers.get("X-Pay-Signature") or frappe.request.headers.get("Signature")
        try:
            verify_ing_checkout_webhook(raw_payload, signature)
        except INGCheckoutWebhookError as e:
            frappe.log_error(
                title="ING Checkout mandate webhook signature failed",
                message=f"{e.message}\nDetails: {e.details}",
            )
            frappe.local.response["http_status_code"] = 401
            return {"status": "error", "message": "Signature verification failed"}

        # Parse payload
        try:
            payload = json.loads(
                raw_payload.decode("utf-8") if isinstance(raw_payload, bytes) else raw_payload
            )
        except json.JSONDecodeError:
            frappe.local.response["http_status_code"] = 400
            return {"status": "error", "message": "Invalid JSON payload"}

        raw_payload_str = raw_payload.decode("utf-8") if isinstance(raw_payload, bytes) else str(raw_payload)

        # Extract event ID
        mandate_id = (
            payload.get("id") or payload.get("object", {}).get("id") or f"mandate_{frappe.utils.now()}"
        )

        # Check for duplicate webhook
        if is_duplicate_webhook(mandate_id, raw_payload_str):
            frappe.logger().info(f"Duplicate ING Checkout mandate webhook ignored: {mandate_id}")
            return {"status": "duplicate", "message": "Webhook already processed"}

        mandate_object = payload.get("object", {})
        status = mandate_object.get("status")

        frappe.logger().info(f"ING Checkout mandate webhook: mandate={mandate_id}, status={status}")

        # Process mandate status update with savepoint
        savepoint_name = f"ing_mandate_{mandate_id}"
        try:
            frappe.db.savepoint(savepoint_name)
            result = _process_mandate_webhook(mandate_id, payload)

            log_webhook(
                event_id=mandate_id,
                webhook_type="ing_checkout_mandate",
                raw_payload=raw_payload_str,
                status="success",
                processing_result=json.dumps(result, default=str),
            )

            return {"status": "processed", "mandate_id": mandate_id, "result": result}

        except Exception:
            frappe.db.rollback(save_point=savepoint_name)
            raise

    except WebhookRateLimitExceeded as e:
        # Return 429 to signal Pay.nl to retry later
        frappe.local.response["http_status_code"] = 429
        return {"status": "rate_limited", "message": str(e)}

    except Exception as e:
        frappe.logger().error(f"ING Checkout mandate webhook error: {e}")
        frappe.log_error(
            title="ING Checkout Mandate Webhook Error",
            message=f"Error processing mandate webhook: {str(e)}",
        )
        if raw_payload:
            raw_str = raw_payload.decode("utf-8") if isinstance(raw_payload, bytes) else str(raw_payload)
            log_webhook(
                event_id=f"mandate_error_{frappe.utils.now()}",
                webhook_type="ing_checkout_mandate",
                raw_payload=raw_str,
                status="error",
                error_details=str(e),
            )
        frappe.local.response["http_status_code"] = 500
        return {"status": "error", "message": "Internal server error"}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@public_api(operation_type=OperationType.WEBHOOK_PROCESSING)
def handle_direct_debit():
    """
    Handle Pay.nl exchange notifications for direct debit transactions.

    Returns:
        JSON response with status
    """
    raw_payload = None
    try:
        # STEP 0: Rate limiting (before any expensive operations)
        ip_address = frappe.local.request_ip if hasattr(frappe.local, "request_ip") else "unknown"
        webhook_id = frappe.form_dict.get("id") if frappe.form_dict else None

        rate_limiter = get_webhook_rate_limiter()
        is_allowed, reason = rate_limiter.check_rate_limit(ip_address, webhook_id)

        if not is_allowed:
            frappe.log_error(
                f"ING Checkout direct debit webhook rate limited: IP={ip_address}, webhook_id={webhook_id}, reason={reason}",
                "ING Checkout Webhook Rate Limit",
            )
            raise WebhookRateLimitExceeded(f"Rate limit exceeded: {reason}")

        raw_payload = frappe.request.get_data()
        if not raw_payload:
            frappe.local.response["http_status_code"] = 400
            return {"status": "error", "message": "Empty request body"}

        # Verify webhook signature
        signature = frappe.request.headers.get("X-Pay-Signature") or frappe.request.headers.get("Signature")
        try:
            verify_ing_checkout_webhook(raw_payload, signature)
        except INGCheckoutWebhookError as e:
            frappe.log_error(
                title="ING Checkout direct debit webhook signature failed",
                message=f"{e.message}\nDetails: {e.details}",
            )
            frappe.local.response["http_status_code"] = 401
            return {"status": "error", "message": "Signature verification failed"}

        # Parse payload
        try:
            payload = json.loads(
                raw_payload.decode("utf-8") if isinstance(raw_payload, bytes) else raw_payload
            )
        except json.JSONDecodeError:
            frappe.local.response["http_status_code"] = 400
            return {"status": "error", "message": "Invalid JSON payload"}

        raw_payload_str = raw_payload.decode("utf-8") if isinstance(raw_payload, bytes) else str(raw_payload)

        # Extract event ID
        reference_id = (
            payload.get("id") or payload.get("object", {}).get("id") or f"debit_{frappe.utils.now()}"
        )

        # Check for duplicate webhook
        if is_duplicate_webhook(reference_id, raw_payload_str):
            frappe.logger().info(f"Duplicate ING Checkout debit webhook ignored: {reference_id}")
            return {"status": "duplicate", "message": "Webhook already processed"}

        debit_object = payload.get("object", {})
        status = debit_object.get("status")

        frappe.logger().info(f"ING Checkout debit webhook: reference={reference_id}, status={status}")

        # Process with savepoint
        savepoint_name = f"ing_debit_{reference_id}"
        try:
            frappe.db.savepoint(savepoint_name)
            result = _process_direct_debit_webhook(reference_id, payload)

            log_webhook(
                event_id=reference_id,
                webhook_type="ing_checkout_direct_debit",
                raw_payload=raw_payload_str,
                status="success",
                processing_result=json.dumps(result, default=str),
            )

            return {"status": "processed", "reference_id": reference_id, "result": result}

        except Exception:
            frappe.db.rollback(save_point=savepoint_name)
            raise

    except WebhookRateLimitExceeded as e:
        # Return 429 to signal Pay.nl to retry later
        frappe.local.response["http_status_code"] = 429
        return {"status": "rate_limited", "message": str(e)}

    except Exception as e:
        frappe.logger().error(f"ING Checkout direct debit webhook error: {e}")
        frappe.log_error(
            title="ING Checkout Direct Debit Webhook Error",
            message=f"Error processing direct debit webhook: {str(e)}",
        )
        if raw_payload:
            raw_str = raw_payload.decode("utf-8") if isinstance(raw_payload, bytes) else str(raw_payload)
            log_webhook(
                event_id=f"debit_error_{frappe.utils.now()}",
                webhook_type="ing_checkout_direct_debit",
                raw_payload=raw_str,
                status="error",
                error_details=str(e),
            )
        frappe.local.response["http_status_code"] = 500
        return {"status": "error", "message": "Internal server error"}


def _process_payment_webhook(order_id: str, payload: dict) -> Dict[str, Any]:
    """
    Process payment webhook and update/create transaction.

    Uses proper reference parsing and validates documents exist.

    Args:
        order_id: Pay.nl order ID
        payload: Full webhook payload

    Returns:
        Dict with processing result
    """
    from verenigingen.verenigingen_payments.doctype.ing_checkout_transaction.ing_checkout_transaction import (
        get_or_create_transaction,
    )

    order_object = payload.get("object", {})
    reference = order_object.get("reference", "")
    amount_data = order_object.get("amount", {})
    # Convert cents to EUR using Decimal for precision
    amount = float(Decimal(amount_data.get("value", 0)) / Decimal(100))

    # Parse reference to get doctype and name
    reference_doctype, reference_name = _parse_reference(reference)

    # Get or create transaction
    transaction = get_or_create_transaction(
        transaction_id=order_id,
        reference_doctype=reference_doctype,
        reference_name=reference_name,
        amount=amount,
        payment_method="iDEAL",
    )

    # Update from webhook (uses savepoint internally for Payment Entry creation)
    transaction.update_from_webhook(payload)

    return {
        "transaction_name": transaction.name,
        "status": transaction.status,
        "reference_doctype": reference_doctype,
        "reference_name": reference_name,
        "payment_entry": transaction.payment_entry,
    }


def _parse_reference(reference: str) -> tuple:
    """
    Parse Pay.nl reference to extract DocType and document name.

    Supports formats:
    - New format: "DOCTYPE_CODE:DOCUMENT_NAME" (e.g., "SINV:ACC-SINV-2025-00001")
    - Legacy format: Direct document name (e.g., "ACC-SINV-2025-00001")

    Args:
        reference: Reference string from Pay.nl

    Returns:
        Tuple of (reference_doctype, reference_name) or (None, None)
    """
    if not reference:
        return None, None

    # DocType code mapping
    DOCTYPE_MAP = {
        "SINV": "Sales Invoice",
        "MEM": "Member",
        "PINV": "Purchase Invoice",
    }

    # New format: DOCTYPE_CODE:DOCUMENT_NAME
    if ":" in reference:
        parts = reference.split(":", 1)
        if len(parts) == 2:
            doctype_code, doc_name = parts
            doctype = DOCTYPE_MAP.get(doctype_code.upper())
            if doctype:
                if frappe.db.exists(doctype, doc_name):
                    return doctype, doc_name
                else:
                    frappe.logger().warning(
                        f"Document not found: {doctype} '{doc_name}' from reference '{reference}'"
                    )
                    return None, None
            else:
                frappe.logger().warning(f"Unknown doctype code: {doctype_code}")
                # Fall through to legacy parsing

    # Legacy format: Try to find document directly
    for doctype in ["Sales Invoice", "Member"]:
        if frappe.db.exists(doctype, reference):
            return doctype, reference

    # Legacy prefix-based mapping (for backwards compatibility)
    legacy_prefix_map = {
        "SAL-INV": "Sales Invoice",
        "ACC-SINV": "Sales Invoice",
        "SINV": "Sales Invoice",
        "MEM": "Member",
    }

    for prefix, doctype in legacy_prefix_map.items():
        if reference.startswith(prefix):
            if frappe.db.exists(doctype, reference):
                return doctype, reference

    frappe.logger().debug(f"Could not match reference '{reference}' to any document")
    return None, None


def _process_mandate_webhook(mandate_id: str, payload: dict) -> Dict[str, Any]:
    """
    Process mandate webhook and update mandate status.

    Args:
        mandate_id: Pay.nl mandate ID
        payload: Full webhook payload

    Returns:
        Dict with processing result
    """
    mandate_object = payload.get("object", {})
    status = mandate_object.get("status", "")

    # Find existing mandate
    existing_mandate = frappe.db.get_value(
        "ING Checkout Mandate",
        {"mandate_id": mandate_id},
        "name",
    )

    if not existing_mandate:
        frappe.logger().warning(f"No ING Checkout Mandate found for mandate_id: {mandate_id}")
        return {"handled": True, "action": "logged", "reason": "mandate_not_found"}

    # Map Pay.nl status to our status
    from verenigingen.verenigingen_payments.doctype.ing_checkout_mandate.ing_checkout_mandate import (
        MANDATE_STATUS_MAP,
    )

    status_lower = status.lower() if status else ""
    if status_lower in MANDATE_STATUS_MAP:
        mandate_doc = frappe.get_doc("ING Checkout Mandate", existing_mandate)
        old_status = mandate_doc.status
        mandate_doc.status = MANDATE_STATUS_MAP[status_lower]
        mandate_doc.raw_response = frappe.as_json(payload)
        # Webhook user has write permission on ING Checkout Mandate (added 2026-01-10)
        mandate_doc.save()

        return {
            "handled": True,
            "action": "status_updated",
            "old_status": old_status,
            "new_status": mandate_doc.status,
        }

    return {"handled": True, "action": "logged", "reason": "unknown_status"}


def _process_direct_debit_webhook(reference_id: str, payload: dict) -> Dict[str, Any]:
    """
    Process direct debit webhook.

    Args:
        reference_id: Pay.nl debit reference ID
        payload: Full webhook payload

    Returns:
        Dict with processing result
    """
    debit_object = payload.get("object", {})
    _status = debit_object.get("status", "")  # noqa: F841 - extracted for future use

    # Find associated transaction
    existing_transaction = frappe.db.get_value(
        "ING Checkout Transaction",
        {"transaction_id": reference_id},
        "name",
    )

    if existing_transaction:
        # Update existing transaction
        transaction = frappe.get_doc("ING Checkout Transaction", existing_transaction)
        transaction.update_from_webhook(payload)
        return {
            "handled": True,
            "action": "transaction_updated",
            "transaction_name": transaction.name,
            "status": transaction.status,
        }

    # No existing transaction - log for review
    frappe.logger().info(f"Direct debit webhook for unknown transaction: {reference_id}")
    return {"handled": True, "action": "logged", "reason": "transaction_not_found"}
