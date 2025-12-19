# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Ponto Integration Exception Hierarchy

Provides structured exception handling for the Ponto banking integration.
All exceptions inherit from PontoIntegrationError for consistent error handling.

Usage:
    from verenigingen.verenigingen_payments.ponto.exceptions import (
        PontoAPIError,
        PontoAuthenticationError,
        PontoRateLimitError,
    )

    try:
        client.get("/accounts")
    except PontoRateLimitError:
        # Handle rate limiting
    except PontoAPIError as e:
        # Handle API errors
"""

from typing import Any, Dict, Optional


class PontoIntegrationError(Exception):
    """
    Base exception for all Ponto integration errors.

    All Ponto-specific exceptions inherit from this class to enable
    broad exception catching when needed.

    Attributes:
        message: Human-readable error description
        details: Optional dict with additional context
    """

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} | Details: {self.details}"
        return self.message


class _MockResponse:
    """Mock response object for error recovery compatibility."""

    def __init__(self, status_code: Optional[int]):
        self.status_code = status_code


class PontoAPIError(PontoIntegrationError):
    """
    Exception for Ponto API errors (HTTP 4xx/5xx responses).

    Raised when the Ponto API returns an error response.

    Attributes:
        status_code: HTTP status code from the API
        error_code: Ponto-specific error code (from JSON:API error response)
        message: Error message
        response: Mock response object for error recovery compatibility
    """

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.status_code = status_code
        self.error_code = error_code
        # Compatibility with error_recovery._should_retry_error
        self.response = _MockResponse(status_code)
        super().__init__(message, details)

    def __str__(self) -> str:
        parts = [self.message]
        if self.status_code:
            parts.append(f"HTTP {self.status_code}")
        if self.error_code:
            parts.append(f"Code: {self.error_code}")
        if self.details:
            parts.append(f"Details: {self.details}")
        return " | ".join(parts)


class PontoAuthenticationError(PontoIntegrationError):
    """
    Exception for authentication/authorization failures.

    Raised when:
    - OAuth2 token fetch fails
    - Token refresh fails
    - Invalid credentials provided
    - Token expired and cannot be refreshed

    This exception typically requires user intervention to fix
    (e.g., updating credentials in Ponto Settings).
    """

    def __init__(
        self,
        message: str = "Ponto authentication failed",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message, details)


class PontoTokenExpiredError(PontoAuthenticationError):
    """
    Exception for expired OAuth2 tokens.

    Raised when the access token has expired and automatic
    refresh was not possible. The token manager typically
    handles refresh automatically, so this indicates a
    deeper authentication problem.
    """

    def __init__(
        self,
        message: str = "Ponto access token expired",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message, details)


class PontoRateLimitError(PontoIntegrationError):
    """
    Exception for rate limiting (HTTP 429).

    Raised when the Ponto API rate limit is exceeded.
    Manual sync has a 5-minute cooldown period.

    Attributes:
        retry_after: Seconds to wait before retrying (if provided by API)
    """

    def __init__(
        self,
        message: str = "Ponto API rate limit exceeded",
        retry_after: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.retry_after = retry_after
        if retry_after:
            details = details or {}
            details["retry_after_seconds"] = retry_after
        super().__init__(message, details)


class PontoWebhookError(PontoIntegrationError):
    """
    Exception for webhook processing errors.

    Raised when:
    - Webhook signature verification fails
    - Webhook payload is malformed
    - Webhook event type is unknown
    - Processing a webhook event fails
    """

    def __init__(
        self,
        message: str = "Ponto webhook processing failed",
        event_type: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.event_type = event_type
        if event_type:
            details = details or {}
            details["event_type"] = event_type
        super().__init__(message, details)


class PontoConfigurationError(PontoIntegrationError):
    """
    Exception for configuration errors.

    Raised when:
    - Required settings are missing (client_id, client_secret)
    - Linked account is not configured
    - Bank account mapping is invalid
    """

    def __init__(
        self,
        message: str = "Ponto configuration error",
        missing_fields: Optional[list] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.missing_fields = missing_fields or []
        if missing_fields:
            details = details or {}
            details["missing_fields"] = missing_fields
        super().__init__(message, details)


class PontoSyncError(PontoIntegrationError):
    """
    Exception for synchronization errors.

    Raised when:
    - Sync trigger fails
    - Sync times out
    - Sync returns error status
    """

    def __init__(
        self,
        message: str = "Ponto synchronization failed",
        sync_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.sync_id = sync_id
        if sync_id:
            details = details or {}
            details["sync_id"] = sync_id
        super().__init__(message, details)


class PontoTransactionImportError(PontoIntegrationError):
    """
    Exception for transaction import errors.

    Raised when:
    - Transaction data transformation fails
    - Bank Transaction creation fails
    - Bulk import encounters unrecoverable errors
    """

    def __init__(
        self,
        message: str = "Ponto transaction import failed",
        transaction_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.transaction_id = transaction_id
        if transaction_id:
            details = details or {}
            details["ponto_transaction_id"] = transaction_id
        super().__init__(message, details)


# Export all exceptions
__all__ = [
    "PontoIntegrationError",
    "PontoAPIError",
    "PontoAuthenticationError",
    "PontoTokenExpiredError",
    "PontoRateLimitError",
    "PontoWebhookError",
    "PontoConfigurationError",
    "PontoSyncError",
    "PontoTransactionImportError",
]
