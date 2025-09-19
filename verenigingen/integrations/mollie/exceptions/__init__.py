"""
Mollie Integration Exception Classes

Custom exceptions for Mollie payment processing to provide better error handling
and debugging capabilities.
"""


class MollieWebhookError(Exception):
    """Base exception for Mollie webhook processing errors."""

    def __init__(self, message: str, payment_id: str = None, original_error: Exception = None):
        self.payment_id = payment_id
        self.original_error = original_error
        super().__init__(message)


class MollieSecurityError(MollieWebhookError):
    """Raised when webhook signature validation fails."""

    pass


class MolliePaymentError(MollieWebhookError):
    """Raised when payment processing fails."""

    pass


class MollieValidationError(MollieWebhookError):
    """Raised when webhook payload validation fails."""

    pass


class MollieIdempotencyError(MollieWebhookError):
    """Raised when duplicate webhook processing is detected."""

    pass
