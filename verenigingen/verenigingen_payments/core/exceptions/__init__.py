# Copyright (c) 2026, Verenigingen
# License: MIT

"""
Shared PSP Exception Hierarchy.

This module provides a consistent exception hierarchy for all Payment Service Provider
integrations (Mollie, Ponto, ING Checkout). It enables:

1. Consistent error handling across all PSPs
2. Rich context for debugging and logging
3. Clear distinction between error types (API, auth, rate limit, webhook, etc.)
4. Proper inheritance for catch blocks to work at appropriate granularity

Usage:
    from verenigingen.verenigingen_payments.core.exceptions import (
        PSPIntegrationError,
        PSPAPIError,
        PSPAuthenticationError,
        PSPRateLimitError,
        PSPValidationError,
        PSPConfigurationError,
        PSPWebhookError,
    )

    # Catch all PSP errors
    try:
        process_payment()
    except PSPIntegrationError as e:
        log_error(e.psp_name, e.message, e.details)

    # Catch specific error types
    try:
        call_api()
    except PSPRateLimitError as e:
        if e.retry_after:
            schedule_retry(e.retry_after)
    except PSPAuthenticationError:
        notify_admin("API key may be invalid")
"""

from typing import Any, Dict, Optional


class PSPIntegrationError(Exception):
    """
    Base exception for all PSP integration errors.

    All PSP-specific exceptions inherit from this class, allowing code to catch
    all integration errors with a single except clause while still providing
    rich context for debugging.

    Attributes:
        message: Human-readable error description
        psp_name: Name of the PSP ("mollie", "ponto", "ing_checkout")
        details: Additional context as a dictionary
        status_code: HTTP status code if applicable
        original_error: The underlying exception if wrapping another error
    """

    def __init__(
        self,
        message: str,
        psp_name: str = "",
        details: Optional[Dict[str, Any]] = None,
        status_code: Optional[int] = None,
        original_error: Optional[Exception] = None,
    ):
        self.message = message
        self.psp_name = psp_name
        self.details = details or {}
        self.status_code = status_code
        self.original_error = original_error
        super().__init__(self.message)

    def __str__(self) -> str:
        parts = [self.message]
        if self.psp_name:
            parts.insert(0, f"[{self.psp_name}]")
        if self.status_code:
            parts.append(f"(HTTP {self.status_code})")
        return " ".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for logging/serialization."""
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "psp_name": self.psp_name,
            "details": self.details,
            "status_code": self.status_code,
        }


# =============================================================================
# API Errors
# =============================================================================


class PSPAPIError(PSPIntegrationError):
    """
    General API communication error.

    Raised when API calls fail for reasons other than auth or rate limiting.
    Examples: network timeouts, invalid responses, server errors.
    """

    pass


class PSPAuthenticationError(PSPIntegrationError):
    """
    Authentication/authorization failure.

    Raised when API credentials are invalid, expired, or lack required permissions.
    Typically corresponds to HTTP 401 or 403 responses.
    """

    def __init__(self, message: str = "Authentication failed", **kwargs):
        super().__init__(message, **kwargs)


class PSPRateLimitError(PSPIntegrationError):
    """
    API rate limit exceeded.

    Raised when the PSP's rate limit is exceeded. Includes retry_after hint
    when available from the API response.

    Attributes:
        retry_after: Seconds to wait before retrying (from Retry-After header)
    """

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        retry_after: Optional[int] = None,
        **kwargs,
    ):
        self.retry_after = retry_after
        super().__init__(message, **kwargs)

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        result["retry_after"] = self.retry_after
        return result


class PSPValidationError(PSPIntegrationError):
    """
    Data validation failure from the PSP.

    Raised when the PSP rejects a request due to invalid data.
    Typically corresponds to HTTP 422 (Unprocessable Entity) responses.

    Attributes:
        field: Specific field that failed validation (if known)
        validation_errors: List of validation error details from PSP
    """

    def __init__(
        self,
        message: str = "Validation failed",
        field: Optional[str] = None,
        validation_errors: Optional[list] = None,
        **kwargs,
    ):
        self.field = field
        self.validation_errors = validation_errors or []
        super().__init__(message, **kwargs)

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        result["field"] = self.field
        result["validation_errors"] = self.validation_errors
        return result


# =============================================================================
# Configuration Errors
# =============================================================================


class PSPConfigurationError(PSPIntegrationError):
    """
    PSP configuration is missing or invalid.

    Raised when required configuration (API keys, webhook URLs, etc.) is missing
    or invalid. This is a setup issue that requires admin intervention.

    Attributes:
        config_field: Name of the missing/invalid configuration field
    """

    def __init__(
        self,
        message: str = "Configuration error",
        config_field: Optional[str] = None,
        **kwargs,
    ):
        self.config_field = config_field
        super().__init__(message, **kwargs)

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        result["config_field"] = self.config_field
        return result


# =============================================================================
# Webhook Errors
# =============================================================================


class PSPWebhookError(PSPIntegrationError):
    """
    General webhook processing error.

    Base class for webhook-specific errors. Raised when webhook processing fails
    for reasons other than security or idempotency issues.

    Attributes:
        webhook_id: ID of the webhook event that failed
        webhook_type: Type of webhook (payment, subscription, mandate, etc.)
    """

    def __init__(
        self,
        message: str = "Webhook processing error",
        webhook_id: Optional[str] = None,
        webhook_type: Optional[str] = None,
        **kwargs,
    ):
        self.webhook_id = webhook_id
        self.webhook_type = webhook_type
        super().__init__(message, **kwargs)

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        result["webhook_id"] = self.webhook_id
        result["webhook_type"] = self.webhook_type
        return result


class PSPWebhookSecurityError(PSPWebhookError):
    """
    Webhook security/authentication failure.

    Raised when webhook signature validation fails, indicating the request
    may not be from the legitimate PSP.

    Attributes:
        ip_address: Source IP of the failed request (for audit logging)
    """

    def __init__(
        self,
        message: str = "Webhook security validation failed",
        ip_address: Optional[str] = None,
        **kwargs,
    ):
        self.ip_address = ip_address
        super().__init__(message, **kwargs)

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        result["ip_address"] = self.ip_address
        return result


class PSPWebhookIdempotencyError(PSPWebhookError):
    """
    Duplicate webhook detected.

    Raised when a webhook with the same ID/hash has already been processed.
    This is expected behavior for PSP retries and should be handled gracefully.

    Attributes:
        webhook_hash: Hash of the webhook for duplicate detection
        original_processed_at: When the original webhook was processed
    """

    def __init__(
        self,
        message: str = "Duplicate webhook detected",
        webhook_hash: Optional[str] = None,
        original_processed_at: Optional[str] = None,
        **kwargs,
    ):
        self.webhook_hash = webhook_hash
        self.original_processed_at = original_processed_at
        super().__init__(message, **kwargs)

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        result["webhook_hash"] = self.webhook_hash
        result["original_processed_at"] = self.original_processed_at
        return result


# =============================================================================
# Resource Errors
# =============================================================================


class PSPResourceNotFoundError(PSPIntegrationError):
    """
    Requested resource not found in PSP.

    Raised when an API call references a resource that doesn't exist.
    Typically corresponds to HTTP 404 responses.

    Attributes:
        resource_type: Type of resource (payment, customer, mandate, etc.)
        resource_id: ID of the resource that wasn't found
    """

    def __init__(
        self,
        message: str = "Resource not found",
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        **kwargs,
    ):
        self.resource_type = resource_type
        self.resource_id = resource_id
        super().__init__(message, **kwargs)

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        result["resource_type"] = self.resource_type
        result["resource_id"] = self.resource_id
        return result


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Base
    "PSPIntegrationError",
    # API errors
    "PSPAPIError",
    "PSPAuthenticationError",
    "PSPRateLimitError",
    "PSPValidationError",
    # Configuration
    "PSPConfigurationError",
    # Webhook errors
    "PSPWebhookError",
    "PSPWebhookSecurityError",
    "PSPWebhookIdempotencyError",
    # Resource errors
    "PSPResourceNotFoundError",
]
