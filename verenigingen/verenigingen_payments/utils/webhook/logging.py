# Copyright (c) 2026, Verenigingen
# License: MIT

"""
Unified webhook logging for all PSP integrations.

This module consolidates webhook logging functionality previously duplicated
across Ponto (api/webhook.py) and ING Checkout (utils/webhook_security.py).

Provides:
- Consistent SHA256 hashing for webhook idempotency
- Standardized Webhook Processing Log creation
- Duplicate detection across all PSPs

Webhook Types:
- Mollie: payment, subscription, customer, chargeback
- Ponto: ponto_sync, ponto_payment, ponto_account
- ING Checkout: ing_checkout_payment, ing_checkout_mandate, ing_checkout_direct_debit
"""

import hashlib
from typing import Any, Dict, Optional

import frappe
from frappe.utils import now_datetime


def compute_webhook_hash(webhook_id: str, payload: str) -> str:
    """
    Compute a unique hash for a webhook event for idempotency.

    Uses SHA256 to create a deterministic hash from webhook ID and payload.
    This allows duplicate detection even if the same webhook is received
    multiple times (e.g., due to retries from the PSP).

    Args:
        webhook_id: Unique identifier for the webhook (e.g., event ID from PSP)
        payload: Raw webhook payload as string

    Returns:
        SHA256 hash string (64 characters hex)

    Example:
        >>> compute_webhook_hash("tr_123abc", '{"id": "tr_123abc"}')
        'a1b2c3...'
    """
    return hashlib.sha256(f"{webhook_id}:{payload}".encode()).hexdigest()


def is_duplicate_webhook(webhook_id: str, payload: str) -> bool:
    """
    Check if this webhook has already been processed (idempotency check).

    Uses Webhook Processing Log to track processed webhooks. Should be called
    early in webhook processing to avoid unnecessary work on duplicates.

    Args:
        webhook_id: Unique identifier for the webhook
        payload: Raw webhook payload as string

    Returns:
        True if webhook has already been processed, False otherwise

    Example:
        >>> if is_duplicate_webhook(event_id, raw_payload):
        ...     return {"status": "duplicate", "message": "Already processed"}
    """
    webhook_hash = compute_webhook_hash(webhook_id, payload)
    return bool(frappe.db.exists("Webhook Processing Log", {"webhook_hash": webhook_hash}))


def create_webhook_log(
    webhook_id: str,
    webhook_type: str,
    raw_payload: str,
    status: str = "success",
    processing_result: Optional[str] = None,
    error_details: Optional[str] = None,
    webhook_hash: Optional[str] = None,
    auto_commit: bool = True,
) -> Optional[str]:
    """
    Create a Webhook Processing Log entry.

    Unified logging function for all PSP webhooks. Handles:
    - Duplicate detection via webhook hash
    - Field truncation to avoid database errors
    - Graceful error handling to not break webhook processing

    Args:
        webhook_id: Unique identifier for the webhook (e.g., event ID from PSP)
        webhook_type: Type of webhook. Must be one of:
            - Mollie: "payment", "subscription", "customer", "chargeback"
            - Ponto: "ponto_sync", "ponto_payment", "ponto_account"
            - ING: "ing_checkout_payment", "ing_checkout_mandate", "ing_checkout_direct_debit"
        raw_payload: Original webhook payload as string (for debugging/replay)
        status: Processing status - "success", "error", or "ignored"
        processing_result: JSON string with processing result details
        error_details: Error message if status is "error"
        webhook_hash: Pre-computed hash (if None, will be computed)
        auto_commit: Whether to commit after insert (default True)

    Returns:
        Name of created log document (e.g., "WEBHOOK-00001") or None if:
        - Logging failed due to error
        - Webhook is a duplicate (already exists)

    Example:
        >>> log_name = create_webhook_log(
        ...     webhook_id="tr_ABC123",
        ...     webhook_type="payment",
        ...     raw_payload='{"id": "tr_ABC123", "status": "paid"}',
        ...     status="success",
        ...     processing_result='{"payment_entry": "PE-001"}'
        ... )
    """
    try:
        # Compute hash if not provided
        if not webhook_hash:
            webhook_hash = compute_webhook_hash(webhook_id, raw_payload)

        # Check for duplicate (race condition protection)
        existing = frappe.db.exists("Webhook Processing Log", {"webhook_hash": webhook_hash})
        if existing:
            frappe.logger().debug(f"Duplicate webhook detected: {webhook_id}")
            return None

        # Create log document
        log = frappe.new_doc("Webhook Processing Log")
        log.webhook_id = _truncate_field(webhook_id, 140, "unknown")
        log.webhook_type = webhook_type
        log.webhook_hash = webhook_hash
        log.processed_at = now_datetime()
        log.status = status
        log.raw_payload = raw_payload

        if processing_result:
            log.processing_result = processing_result

        if error_details:
            # Text field limit in MariaDB
            log.error_details = _truncate_field(error_details, 65535)

        # Webhook user has create permission on Webhook Processing Log
        log.insert()

        if auto_commit:
            frappe.db.commit()

        return log.name

    except Exception as e:
        frappe.logger().error(f"Failed to create webhook log for {webhook_id}: {e}")
        return None


def update_webhook_log(
    log_name: str,
    status: Optional[str] = None,
    processing_result: Optional[str] = None,
    error_details: Optional[str] = None,
    auto_commit: bool = True,
) -> bool:
    """
    Update an existing webhook log entry.

    Useful when processing happens in stages and you need to update
    the log with final status or add error details.

    Args:
        log_name: Name of the webhook log document
        status: New status (if changing)
        processing_result: Processing result to set/append
        error_details: Error details to set
        auto_commit: Whether to commit after save

    Returns:
        True if update succeeded, False otherwise
    """
    try:
        log = frappe.get_doc("Webhook Processing Log", log_name)

        if status:
            log.status = status

        if processing_result:
            log.processing_result = processing_result

        if error_details:
            log.error_details = _truncate_field(error_details, 65535)

        log.save()

        if auto_commit:
            frappe.db.commit()

        return True

    except Exception as e:
        frappe.logger().error(f"Failed to update webhook log {log_name}: {e}")
        return False


def get_webhook_log_by_hash(webhook_id: str, payload: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve a webhook log entry by computing its hash.

    Useful for checking previous processing results when handling
    potential duplicates.

    Args:
        webhook_id: Webhook identifier
        payload: Raw webhook payload

    Returns:
        Dict with webhook log data or None if not found
    """
    webhook_hash = compute_webhook_hash(webhook_id, payload)

    log_name = frappe.db.get_value("Webhook Processing Log", {"webhook_hash": webhook_hash}, "name")

    if log_name:
        return frappe.get_doc("Webhook Processing Log", log_name).as_dict()

    return None


def _truncate_field(value: Optional[str], max_length: int, default: str = "") -> str:
    """
    Safely truncate a field value to fit database constraints.

    Args:
        value: Value to truncate
        max_length: Maximum allowed length
        default: Default value if input is None/empty

    Returns:
        Truncated string value
    """
    if not value:
        return default

    if len(value) > max_length:
        return value[:max_length]

    return value
