"""
Unified Exception Hierarchy for Verenigingen

This module provides a comprehensive exception hierarchy for consistent error
handling across the application. All custom exceptions extend VerenigingenError
or frappe.ValidationError for domain-specific errors.

Architecture:
    - Base exception with HTTP status codes and error details
    - Specific exception types for different error categories
    - Integration with service_error_handler for backward compatibility
    - Type hints for better IDE support

Usage:
    from verenigingen.utils.exceptions import ValidationError, NotFoundError

    # Raise with context
    raise ValidationError("Invalid email format", field="email")

    # Catch specific errors
    try:
        process_member(data)
    except ValidationError as e:
        return {"error": str(e), "field": e.details.get("field")}
"""

from typing import Any, Dict, Optional

import frappe


class InvalidDuesRateError(frappe.ValidationError):
    """Raised when dues rate validation fails"""

    pass


class MembershipTypeMismatchError(frappe.ValidationError):
    """Raised when membership type consistency validation fails"""

    pass


class InvalidStatusTransitionError(frappe.ValidationError):
    """Raised when an invalid status transition is attempted"""

    pass


class BillingFrequencyConflictError(frappe.ValidationError):
    """Raised when billing frequency conflicts are detected"""

    pass


class DuplicateScheduleError(frappe.ValidationError):
    """Raised when attempting to create duplicate dues schedules"""

    pass


class ScheduleGenerationError(frappe.ValidationError):
    """Raised when invoice generation fails validation"""

    pass


# ==============================================================================
# UNIFIED EXCEPTION HIERARCHY
# ==============================================================================


class VerenigingenError(Exception):
    """
    Base exception for all Verenigingen application errors.

    Attributes:
        message: Human-readable error message
        details: Additional error context (field names, resource IDs, etc.)
        http_status_code: HTTP status code for API responses
        error_code: Machine-readable error code for client handling

    Examples:
        >>> raise VerenigingenError("Something went wrong", details={"resource": "Member"})
        >>> try:
        ...     dangerous_operation()
        ... except VerenigingenError as e:
        ...     log_error(e.details)
    """

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        error_code: Optional[str] = None,
    ):
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.http_status_code = 500  # Default internal server error
        self.error_code = error_code or "INTERNAL_ERROR"

    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for API responses."""
        return {
            "error": self.message,
            "error_code": self.error_code,
            "details": self.details,
            "http_status_code": self.http_status_code,
        }


class ValidationError(VerenigingenError):
    """
    Validation error for invalid data or business rule violations.

    Use this when user input or data fails validation checks.

    Attributes:
        field: Name of the field that failed validation (optional)

    Examples:
        >>> raise ValidationError("Birth date cannot be in the future", field="birth_date")
        >>> raise ValidationError("Member must be at least 16 years old", field="birth_date")
    """

    def __init__(self, message: str, field: Optional[str] = None, **kwargs: Any):
        details = kwargs.pop("details", {})
        if field:
            details["field"] = field
        super().__init__(message, details=details, **kwargs)
        self.http_status_code = 400  # Bad Request
        self.error_code = kwargs.get("error_code", "VALIDATION_ERROR")
        self.field = field


class NotFoundError(VerenigingenError):
    """
    Resource not found error.

    Use when a requested resource doesn't exist.

    Examples:
        >>> raise NotFoundError("Member", "MEM-001")
        >>> raise NotFoundError("Volunteer", volunteer_id, details={"member": member_id})
    """

    def __init__(self, resource_type: str, resource_id: str, **kwargs: Any):
        message = f"{resource_type} '{resource_id}' not found"
        details = kwargs.pop("details", {})
        details.update({"resource_type": resource_type, "resource_id": resource_id})
        super().__init__(message, details=details, **kwargs)
        self.http_status_code = 404  # Not Found
        self.error_code = kwargs.get("error_code", "NOT_FOUND")
        self.resource_type = resource_type
        self.resource_id = resource_id


class PermissionError(VerenigingenError):
    """
    Permission denied error.

    Use when user lacks permission for an operation.

    Examples:
        >>> raise PermissionError("approve_application", "Member")
        >>> raise PermissionError("delete", "Chapter", user=current_user)
    """

    def __init__(self, operation: str, resource: str, **kwargs: Any):
        message = f"Permission denied for {operation} on {resource}"
        details = kwargs.pop("details", {})
        details.update({"operation": operation, "resource": resource})
        super().__init__(message, details=details, **kwargs)
        self.http_status_code = 403  # Forbidden
        self.error_code = kwargs.get("error_code", "PERMISSION_DENIED")
        self.operation = operation
        self.resource = resource


class BusinessRuleError(VerenigingenError):
    """
    Business rule violation error.

    Use when an operation violates business logic or domain rules.

    Attributes:
        rule: Name/description of the violated business rule

    Examples:
        >>> raise BusinessRuleError("Volunteers must be at least 16 years old", rule="min_volunteer_age")
        >>> raise BusinessRuleError("Cannot delete active membership", rule="active_membership_deletion")
    """

    def __init__(self, message: str, rule: str, **kwargs: Any):
        details = kwargs.pop("details", {})
        details["rule"] = rule
        super().__init__(message, details=details, **kwargs)
        self.http_status_code = 422  # Unprocessable Entity
        self.error_code = kwargs.get("error_code", "BUSINESS_RULE_VIOLATION")
        self.rule = rule


class DuplicateError(VerenigingenError):
    """
    Duplicate resource error.

    Use when trying to create a resource that already exists.

    Examples:
        >>> raise DuplicateError("Member", "email@example.com", field="email")
        >>> raise DuplicateError("SEPA Mandate", mandate_id)
    """

    def __init__(self, resource_type: str, identifier: str, field: Optional[str] = None, **kwargs: Any):
        message = f"{resource_type} with {field or 'identifier'} '{identifier}' already exists"
        details = kwargs.pop("details", {})
        details.update({
            "resource_type": resource_type,
            "identifier": identifier,
        })
        if field:
            details["field"] = field
        super().__init__(message, details=details, **kwargs)
        self.http_status_code = 409  # Conflict
        self.error_code = kwargs.get("error_code", "DUPLICATE_ERROR")


class ConfigurationError(VerenigingenError):
    """
    Configuration error.

    Use when system configuration is missing or invalid.

    Examples:
        >>> raise ConfigurationError("Mollie API key not configured", setting="mollie_api_key")
        >>> raise ConfigurationError("Invalid payment gateway configuration")
    """

    def __init__(self, message: str, setting: Optional[str] = None, **kwargs: Any):
        details = kwargs.pop("details", {})
        if setting:
            details["setting"] = setting
        super().__init__(message, details=details, **kwargs)
        self.http_status_code = 500  # Internal Server Error
        self.error_code = kwargs.get("error_code", "CONFIGURATION_ERROR")


class ExternalServiceError(VerenigingenError):
    """
    External service error.

    Use when an external API or service fails.

    Examples:
        >>> raise ExternalServiceError("Mollie API", "Payment creation failed", status_code=500)
        >>> raise ExternalServiceError("eBoekhouden", "Connection timeout")
    """

    def __init__(self, service_name: str, message: str, status_code: Optional[int] = None, **kwargs: Any):
        full_message = f"{service_name}: {message}"
        details = kwargs.pop("details", {})
        details["service_name"] = service_name
        if status_code:
            details["external_status_code"] = status_code
        super().__init__(full_message, details=details, **kwargs)
        self.http_status_code = 502  # Bad Gateway
        self.error_code = kwargs.get("error_code", "EXTERNAL_SERVICE_ERROR")
        self.service_name = service_name


class InsufficientFundsError(BusinessRuleError):
    """
    Insufficient funds for operation.

    Specific business rule error for financial operations.

    Examples:
        >>> raise InsufficientFundsError("Cannot process payment", amount=100.00, balance=50.00)
    """

    def __init__(self, message: str, amount: Optional[float] = None, balance: Optional[float] = None, **kwargs: Any):
        details = kwargs.pop("details", {})
        if amount is not None:
            details["amount"] = amount
        if balance is not None:
            details["balance"] = balance
        super().__init__(message, rule="insufficient_funds", details=details, **kwargs)
        self.error_code = "INSUFFICIENT_FUNDS"


# Backward compatibility alias
class ServiceError(VerenigingenError):
    """
    Legacy ServiceError for backward compatibility.

    New code should use specific exception types instead.

    Deprecated: Use specific exception types (ValidationError, NotFoundError, etc.)
    """

    def __init__(self, message: str, service_name: Optional[str] = None, context: Optional[Dict] = None, original_error: Optional[Exception] = None):
        details = context or {}
        if service_name:
            details["service_name"] = service_name
        if original_error:
            details["original_error"] = str(original_error)
        super().__init__(message, details=details)
        self.service_name = service_name
        self.context = context
        self.original_error = original_error
