# Copyright (c) 2026, Verenigingen
# License: MIT

"""
Standardized API Response Formats for PSP Integrations.

This module provides consistent response structures and helpers for all
Payment Service Provider (PSP) API endpoints. It complements the exception
hierarchy in `core/exceptions/` by handling how errors are communicated
to API consumers.

Design Principles:
1. **Exceptions for flow control**: Use exceptions (from core/exceptions) to
   signal errors within the service/business logic layer
2. **Structured responses for APIs**: Convert exceptions to consistent
   response dicts at API boundaries
3. **Correlation IDs for tracing**: Include correlation IDs in all responses
   for distributed tracing and debugging
4. **Security-aware**: Hide sensitive details from non-admin users

Usage:
    from verenigingen.verenigingen_payments.core.responses import (
        APIResponse,
        create_success_response,
        create_error_response,
        handle_psp_exception,
    )

    # In an API endpoint:
    try:
        result = process_payment(payment_id)
        return create_success_response("Payment processed", data={"payment_id": result.id})
    except PSPIntegrationError as e:
        return handle_psp_exception(e)

Standard Response Format:
    {
        "status": "success|error|validation_error|business_error|system_error",
        "message": "Human-readable message",
        "correlation_id": "abc12345",  # For tracing
        "timestamp": "2026-01-11 12:00:00",
        "data": {...},  # Optional: additional response data
        "error_code": "...",  # Optional: machine-readable error code
        "details": {...},  # Optional: additional context (hidden in production for system errors)
    }

HTTP Status Code Mapping:
    - success → 200
    - validation_error → 400
    - business_error → 400 or 422
    - system_error → 500
    - rate_limited → 429
    - unauthorized → 401
    - forbidden → 403
"""

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

import frappe
from frappe.utils import now


class ResponseStatus(str, Enum):
    """Standard status values for API responses."""

    SUCCESS = "success"
    ERROR = "error"
    VALIDATION_ERROR = "validation_error"
    BUSINESS_ERROR = "business_error"
    SYSTEM_ERROR = "system_error"
    RATE_LIMITED = "rate_limited"
    DUPLICATE = "duplicate"
    IGNORED = "ignored"

    @property
    def http_status_code(self) -> int:
        """Get the appropriate HTTP status code for this response status."""
        mapping = {
            ResponseStatus.SUCCESS: 200,
            ResponseStatus.ERROR: 400,
            ResponseStatus.VALIDATION_ERROR: 400,
            ResponseStatus.BUSINESS_ERROR: 422,
            ResponseStatus.SYSTEM_ERROR: 500,
            ResponseStatus.RATE_LIMITED: 429,
            ResponseStatus.DUPLICATE: 200,
            ResponseStatus.IGNORED: 200,
        }
        return mapping.get(self, 500)


@dataclass
class APIResponse:
    """
    Structured API response container.

    Provides a type-safe way to build responses with consistent structure.
    Can be converted to dict for JSON serialization.
    """

    status: ResponseStatus
    message: str
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: str = field(default_factory=lambda: str(now()))
    data: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None
    details: Optional[Dict[str, Any]] = None

    def to_dict(self, hide_internal_details: bool = True) -> Dict[str, Any]:
        """Convert to dictionary for JSON response."""
        response = {
            "status": self.status.value,
            "message": self.message,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp,
        }

        if self.data:
            response["data"] = self.data

        if self.error_code:
            response["error_code"] = self.error_code

        if self.details:
            if (
                hide_internal_details
                and self.status == ResponseStatus.SYSTEM_ERROR
                and not frappe.conf.get("developer_mode")
            ):
                pass
            else:
                response["details"] = self.details

        return response

    @property
    def http_status_code(self) -> int:
        """Get the appropriate HTTP status code."""
        return self.status.http_status_code

    @property
    def is_success(self) -> bool:
        """Check if this is a success response."""
        return self.status in (
            ResponseStatus.SUCCESS,
            ResponseStatus.DUPLICATE,
            ResponseStatus.IGNORED,
        )

    @property
    def is_error(self) -> bool:
        """Check if this is an error response."""
        return not self.is_success


def generate_correlation_id() -> str:
    """Generate a new correlation ID for request tracing."""
    return str(uuid.uuid4())[:8]


def create_success_response(
    message: str,
    data: Optional[Dict[str, Any]] = None,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a success response dict."""
    response = APIResponse(
        status=ResponseStatus.SUCCESS,
        message=message,
        correlation_id=correlation_id or generate_correlation_id(),
        data=data,
    )
    return response.to_dict()


def create_error_response(
    message: str,
    status: ResponseStatus = ResponseStatus.ERROR,
    error_code: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create an error response dict."""
    response = APIResponse(
        status=status,
        message=message,
        correlation_id=correlation_id or generate_correlation_id(),
        error_code=error_code,
        details=details,
    )
    return response.to_dict()


def create_validation_error_response(
    message: str,
    field: Optional[str] = None,
    validation_errors: Optional[list] = None,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a validation error response."""
    details = {}
    if field:
        details["field"] = field
    if validation_errors:
        details["validation_errors"] = validation_errors

    return create_error_response(
        message=message,
        status=ResponseStatus.VALIDATION_ERROR,
        error_code="VALIDATION_FAILED",
        details=details if details else None,
        correlation_id=correlation_id,
    )


def create_rate_limited_response(
    retry_after: Optional[int] = None,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a rate limit exceeded response."""
    details = {"retry_after": retry_after} if retry_after else None

    return create_error_response(
        message="Rate limit exceeded. Please retry later.",
        status=ResponseStatus.RATE_LIMITED,
        error_code="RATE_LIMIT_EXCEEDED",
        details=details,
        correlation_id=correlation_id,
    )


def create_duplicate_response(
    message: str = "Request already processed",
    original_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a duplicate/idempotency response."""
    response = APIResponse(
        status=ResponseStatus.DUPLICATE,
        message=message,
        correlation_id=correlation_id or generate_correlation_id(),
        data={"original_id": original_id} if original_id else None,
    )
    return response.to_dict()


def handle_psp_exception(
    exception: Exception,
    psp_name: str = "",
    correlation_id: Optional[str] = None,
    log_error: bool = True,
) -> Dict[str, Any]:
    """
    Convert a PSP exception to a standardized error response.

    This is the main bridge between the exception hierarchy (core/exceptions)
    and the API response format.
    """
    from verenigingen.verenigingen_payments.core.exceptions import (
        PSPAuthenticationError,
        PSPConfigurationError,
        PSPIntegrationError,
        PSPRateLimitError,
        PSPResourceNotFoundError,
        PSPValidationError,
        PSPWebhookError,
        PSPWebhookIdempotencyError,
        PSPWebhookSecurityError,
    )

    correlation_id = correlation_id or generate_correlation_id()

    if log_error:
        frappe.log_error(
            f"[{psp_name or 'PSP'}:{correlation_id}] {type(exception).__name__}: {str(exception)}",
            f"PSP Error [{correlation_id}]",
        )

    if isinstance(exception, PSPWebhookIdempotencyError):
        return create_duplicate_response(
            message=str(exception),
            original_id=exception.original_processed_at,
            correlation_id=correlation_id,
        )

    if isinstance(exception, PSPRateLimitError):
        return create_rate_limited_response(
            retry_after=exception.retry_after,
            correlation_id=correlation_id,
        )

    if isinstance(exception, PSPValidationError):
        return create_validation_error_response(
            message=str(exception),
            field=exception.field,
            validation_errors=exception.validation_errors,
            correlation_id=correlation_id,
        )

    if isinstance(exception, PSPAuthenticationError):
        return create_error_response(
            message="Authentication failed",
            status=ResponseStatus.ERROR,
            error_code="AUTH_FAILED",
            correlation_id=correlation_id,
        )

    if isinstance(exception, PSPWebhookSecurityError):
        return create_error_response(
            message="Security validation failed",
            status=ResponseStatus.ERROR,
            error_code="SECURITY_FAILED",
            correlation_id=correlation_id,
        )

    if isinstance(exception, PSPConfigurationError):
        return create_error_response(
            message="Service configuration error",
            status=ResponseStatus.SYSTEM_ERROR,
            error_code="CONFIG_ERROR",
            details={"config_field": exception.config_field} if exception.config_field else None,
            correlation_id=correlation_id,
        )

    if isinstance(exception, PSPResourceNotFoundError):
        return create_error_response(
            message=str(exception),
            status=ResponseStatus.BUSINESS_ERROR,
            error_code="NOT_FOUND",
            details={
                "resource_type": exception.resource_type,
                "resource_id": exception.resource_id,
            }
            if exception.resource_type
            else None,
            correlation_id=correlation_id,
        )

    if isinstance(exception, PSPWebhookError):
        return create_error_response(
            message=str(exception),
            status=ResponseStatus.BUSINESS_ERROR,
            error_code="WEBHOOK_ERROR",
            details={
                "webhook_id": exception.webhook_id,
                "webhook_type": exception.webhook_type,
            }
            if exception.webhook_id
            else None,
            correlation_id=correlation_id,
        )

    if isinstance(exception, PSPIntegrationError):
        return create_error_response(
            message=str(exception),
            status=ResponseStatus.BUSINESS_ERROR,
            error_code="PSP_ERROR",
            details=exception.details if exception.details else None,
            correlation_id=correlation_id,
        )

    return create_error_response(
        message="An internal error occurred",
        status=ResponseStatus.SYSTEM_ERROR,
        error_code="INTERNAL_ERROR",
        details={"error_type": type(exception).__name__} if frappe.conf.get("developer_mode") else None,
        correlation_id=correlation_id,
    )


def set_http_status_from_response(response: Dict[str, Any]) -> None:
    """Set the HTTP status code on the current Frappe response."""
    status_str = response.get("status", "error")
    try:
        status = ResponseStatus(status_str)
        frappe.local.response["http_status_code"] = status.http_status_code
    except ValueError:
        frappe.local.response["http_status_code"] = 500


__all__ = [
    "ResponseStatus",
    "APIResponse",
    "generate_correlation_id",
    "create_success_response",
    "create_error_response",
    "create_validation_error_response",
    "create_rate_limited_response",
    "create_duplicate_response",
    "handle_psp_exception",
    "set_http_status_from_response",
]
