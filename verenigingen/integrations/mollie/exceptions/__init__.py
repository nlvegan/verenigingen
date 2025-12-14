"""
Mollie Integration Exception Classes

Consolidated exception hierarchy for all Mollie payment processing errors.
This is the canonical location for Mollie exceptions.

Exception Hierarchy:
    MollieIntegrationError (base)
    ├── MollieAPIError - API communication errors
    ├── MollieConfigurationError - Settings/configuration issues
    ├── MollieWebhookError - Webhook processing errors
    │   ├── MollieSecurityError - Signature validation failures
    │   ├── MolliePaymentError - Payment processing failures
    │   ├── MollieValidationError - Payload validation errors
    │   └── MollieIdempotencyError - Duplicate processing detection

Usage:
    from verenigingen.integrations.mollie.exceptions import (
        MolliePaymentError,
        MollieSecurityError,
        MollieValidationError,
    )
"""

from typing import Dict, Optional


class MollieIntegrationError(Exception):
    """
    Base exception for all Mollie integration errors.

    All Mollie-specific exceptions should inherit from this class.
    """

    def __init__(self, message: str, details: Optional[Dict] = None):
        super().__init__(message)
        self.details = details or {}


class MollieAPIError(MollieIntegrationError):
    """
    Exception for Mollie API communication errors.

    Raised when API calls fail due to network issues, authentication errors,
    or Mollie service errors.
    """

    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        status_code: Optional[int] = None,
        details: Optional[Dict] = None,
    ):
        super().__init__(message, details)
        self.error_code = error_code
        self.status_code = status_code


class MollieConfigurationError(MollieIntegrationError):
    """
    Exception for configuration issues.

    Raised when Mollie Settings are missing, invalid, or incomplete.
    """

    pass


class MollieWebhookError(MollieIntegrationError):
    """
    Base exception for Mollie webhook processing errors.

    Raised when webhook processing fails for any reason.
    """

    def __init__(
        self,
        message: str,
        payment_id: Optional[str] = None,
        original_error: Optional[Exception] = None,
        details: Optional[Dict] = None,
    ):
        super().__init__(message, details)
        self.payment_id = payment_id
        self.original_error = original_error


class MollieSecurityError(MollieWebhookError):
    """
    Raised when webhook signature validation fails.

    This indicates a potential security issue - the webhook may not
    have originated from Mollie.
    """

    pass


class MolliePaymentError(MollieWebhookError):
    """
    Raised when payment processing fails.

    This covers errors in creating Payment Entries, updating donations,
    or other payment-related operations.
    """

    pass


class MollieValidationError(MollieWebhookError):
    """
    Raised when webhook payload validation fails.

    This indicates the webhook data is malformed or missing required fields.
    """

    pass


class MollieIdempotencyError(MollieWebhookError):
    """
    Raised when duplicate webhook processing is detected.

    This is generally not an error condition - it indicates the payment
    has already been processed successfully.
    """

    pass


# Convenience exports for common use cases
__all__ = [
    "MollieIntegrationError",
    "MollieAPIError",
    "MollieConfigurationError",
    "MollieWebhookError",
    "MollieSecurityError",
    "MolliePaymentError",
    "MollieValidationError",
    "MollieIdempotencyError",
]
