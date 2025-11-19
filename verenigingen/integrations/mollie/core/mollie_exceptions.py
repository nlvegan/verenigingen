"""
Mollie Integration Exceptions

Centralized exception hierarchy for all Mollie integration errors.
"""

from typing import Dict, Optional


class MollieIntegrationError(Exception):
    """Base exception for all Mollie integration errors."""

    def __init__(self, message: str, details: Optional[Dict] = None):
        super().__init__(message)
        self.details = details or {}


class MollieAPIError(MollieIntegrationError):
    """Exception for Mollie API errors."""

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
    """Exception for configuration issues."""

    pass


class MollieValidationError(MollieIntegrationError):
    """Exception for data validation errors."""

    pass


class MollieWebhookError(MollieIntegrationError):
    """Exception for webhook processing errors."""

    pass


class MollieSecurityError(MollieIntegrationError):
    """Exception for security-related errors."""

    pass
