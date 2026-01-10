# Copyright (c) 2026, Verenigingen
# License: MIT

"""
Base Idempotency Manager for PSP Webhook Processing.

Provides a standardized interface for webhook idempotency checks across all PSPs.
Uses Webhook Processing Log for tracking with SHA256 hash-based duplicate detection.

This module consolidates the hash-based idempotency pattern used by Ponto and
ING Checkout into a reusable class. Mollie's more advanced UnifiedIdempotencyManager
can optionally compose with this for basic webhook duplicate detection.

Usage:
    from verenigingen.verenigingen_payments.core.idempotency import (
        BaseIdempotencyManager,
        IdempotencyResult,
        get_idempotency_manager,
    )

    # Get PSP-specific manager instance
    manager = get_idempotency_manager("ponto")

    # Check if webhook already processed
    result = manager.check_duplicate(event_id, raw_payload)
    if result.is_duplicate:
        return {"status": "duplicate", "original_log": result.original_log_name}

    # Process webhook...

    # Mark as processed
    manager.mark_processed(
        event_id=event_id,
        payload=raw_payload,
        webhook_type="ponto_sync",
        status="success",
        processing_result={"transaction_count": 5}
    )

Architecture:
    - `BaseIdempotencyManager`: Core idempotency logic (hash, check, mark)
    - `IdempotencyResult`: Structured result from duplicate check
    - `get_idempotency_manager()`: Factory for PSP-specific instances

    Advanced PSPs (like Mollie) can extend this with additional features
    like Payment Entry tracking, refund state, etc.
"""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import frappe
from frappe.utils import now_datetime

from verenigingen.utils.webhook.logging import (
    compute_webhook_hash,
    create_webhook_log,
    get_webhook_log_by_hash,
    is_duplicate_webhook,
    update_webhook_log,
)


@dataclass
class IdempotencyResult:
    """
    Structured result from idempotency check.

    Provides clear information about whether a webhook is a duplicate
    and, if so, details about the original processing.
    """

    is_duplicate: bool
    webhook_hash: str
    original_log_name: Optional[str] = None
    original_status: Optional[str] = None
    original_processed_at: Optional[str] = None
    original_result: Optional[Dict[str, Any]] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "is_duplicate": self.is_duplicate,
            "webhook_hash": self.webhook_hash,
            "original_log_name": self.original_log_name,
            "original_status": self.original_status,
            "original_processed_at": self.original_processed_at,
            "original_result": self.original_result,
        }


class BaseIdempotencyManager:
    """
    Base idempotency manager using Webhook Processing Log.

    Provides standardized idempotency checks for webhook processing:
    - SHA256 hash-based duplicate detection
    - Webhook Processing Log storage
    - Structured result objects

    This is the base implementation used by Ponto and ING Checkout.
    Mollie's UnifiedIdempotencyManager provides additional features
    for tracking Payment Entries, refunds, and chargebacks.

    Attributes:
        psp_name: Name of the PSP (for logging context)
        logger: Frappe logger instance
    """

    def __init__(self, psp_name: str = ""):
        """
        Initialize the idempotency manager.

        Args:
            psp_name: Name of the PSP (e.g., "ponto", "ing_checkout", "mollie")
        """
        self.psp_name = psp_name
        self.logger = frappe.logger()

    def compute_hash(self, event_id: str, payload: str) -> str:
        """
        Compute a unique hash for a webhook event.

        Uses SHA256 to create a deterministic hash from event ID and payload.

        Args:
            event_id: Unique identifier for the webhook event
            payload: Raw webhook payload as string

        Returns:
            SHA256 hash string (64 characters hex)
        """
        return compute_webhook_hash(event_id, payload)

    def check_duplicate(self, event_id: str, payload: str) -> IdempotencyResult:
        """
        Check if this webhook has already been processed.

        This is the primary method for idempotency checks. Should be called
        early in webhook processing to avoid unnecessary work.

        Args:
            event_id: Unique identifier for the webhook event
            payload: Raw webhook payload as string

        Returns:
            IdempotencyResult with duplicate status and original processing details
        """
        webhook_hash = self.compute_hash(event_id, payload)

        # Check for existing log
        existing_log = get_webhook_log_by_hash(event_id, payload)

        if existing_log:
            self.logger.info(
                f"[{self.psp_name}:idempotency] Duplicate detected: {event_id} "
                f"(original: {existing_log.get('name')})"
            )

            # Parse original result if stored as JSON
            original_result = {}
            if existing_log.get("processing_result"):
                try:
                    original_result = json.loads(existing_log["processing_result"])
                except (json.JSONDecodeError, TypeError):
                    original_result = {"raw": existing_log.get("processing_result")}

            return IdempotencyResult(
                is_duplicate=True,
                webhook_hash=webhook_hash,
                original_log_name=existing_log.get("name"),
                original_status=existing_log.get("status"),
                original_processed_at=str(existing_log.get("processed_at")),
                original_result=original_result,
            )

        return IdempotencyResult(
            is_duplicate=False,
            webhook_hash=webhook_hash,
        )

    def is_duplicate(self, event_id: str, payload: str) -> bool:
        """
        Simple boolean check for duplicates.

        Convenience method for code that just needs a boolean answer.
        Use check_duplicate() when you need details about the original processing.

        Args:
            event_id: Unique identifier for the webhook event
            payload: Raw webhook payload as string

        Returns:
            True if webhook has already been processed
        """
        return is_duplicate_webhook(event_id, payload)

    def mark_processed(
        self,
        event_id: str,
        payload: str,
        webhook_type: str,
        status: str = "success",
        processing_result: Optional[Dict[str, Any]] = None,
        error_details: Optional[str] = None,
        auto_commit: bool = True,
    ) -> Optional[str]:
        """
        Mark a webhook as processed by creating a log entry.

        Creates a Webhook Processing Log entry with the hash for future
        duplicate detection. Should be called after successful processing.

        Args:
            event_id: Unique identifier for the webhook event
            payload: Raw webhook payload as string
            webhook_type: Type of webhook (e.g., "ponto_sync", "ing_checkout_payment")
            status: Processing status - "success", "error", or "ignored"
            processing_result: Dict with processing details (will be JSON-encoded)
            error_details: Error message if status is "error"
            auto_commit: Whether to commit after insert

        Returns:
            Name of created log document or None if creation failed/duplicate
        """
        result_json = None
        if processing_result:
            try:
                result_json = json.dumps(processing_result, default=str)
            except (TypeError, ValueError) as e:
                self.logger.warning(f"[{self.psp_name}:idempotency] Failed to serialize result: {e}")
                result_json = json.dumps({"serialization_error": str(e)})

        log_name = create_webhook_log(
            webhook_id=event_id,
            webhook_type=webhook_type,
            raw_payload=payload,
            status=status,
            processing_result=result_json,
            error_details=error_details,
            auto_commit=auto_commit,
        )

        if log_name:
            self.logger.debug(f"[{self.psp_name}:idempotency] Marked processed: {event_id} -> {log_name}")

        return log_name

    def update_status(
        self,
        log_name: str,
        status: Optional[str] = None,
        processing_result: Optional[Dict[str, Any]] = None,
        error_details: Optional[str] = None,
        auto_commit: bool = True,
    ) -> bool:
        """
        Update an existing webhook log entry.

        Useful for staged processing where initial log is created early
        and updated with final status later.

        Args:
            log_name: Name of the webhook log document
            status: New status (if changing)
            processing_result: Processing result to set (will be JSON-encoded)
            error_details: Error details to set
            auto_commit: Whether to commit after save

        Returns:
            True if update succeeded
        """
        result_json = None
        if processing_result:
            try:
                result_json = json.dumps(processing_result, default=str)
            except (TypeError, ValueError):
                result_json = None

        return update_webhook_log(
            log_name=log_name,
            status=status,
            processing_result=result_json,
            error_details=error_details,
            auto_commit=auto_commit,
        )


# PSP-specific manager instances (lazy initialization)
_managers: Dict[str, BaseIdempotencyManager] = {}


def get_idempotency_manager(psp_name: str) -> BaseIdempotencyManager:
    """
    Get or create an idempotency manager for a specific PSP.

    Factory function that returns PSP-specific manager instances.
    Managers are cached for reuse within the same request.

    Args:
        psp_name: Name of the PSP ("ponto", "ing_checkout", "mollie")

    Returns:
        BaseIdempotencyManager instance for the PSP

    Example:
        >>> manager = get_idempotency_manager("ponto")
        >>> if manager.is_duplicate(event_id, payload):
        ...     return {"status": "duplicate"}
    """
    global _managers

    if psp_name not in _managers:
        _managers[psp_name] = BaseIdempotencyManager(psp_name)

    return _managers[psp_name]


def clear_manager_cache():
    """
    Clear cached manager instances.

    Useful for testing or when you need fresh instances.
    """
    global _managers
    _managers = {}


# Export public API
__all__ = [
    "BaseIdempotencyManager",
    "IdempotencyResult",
    "get_idempotency_manager",
    "clear_manager_cache",
]
