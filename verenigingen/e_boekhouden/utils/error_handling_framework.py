#!/usr/bin/env python3
"""
Error Handling Framework for eBoekhouden Integration

Provides consistent error handling patterns across all eBoekhouden functions.
Eliminates the current mix of throwing errors, returning None, using fallbacks, etc.

Design Principles:
1. Fail Fast: Critical errors should stop processing immediately
2. Graceful Degradation: Non-critical errors should be logged but allow continuation
3. User-Friendly: Error messages should guide users to solutions
4. Consistent: Same error types handled the same way everywhere
"""

import json
import traceback
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Union

import frappe


class ErrorSeverity(Enum):
    """Error severity levels for consistent handling."""

    CRITICAL = "critical"  # Stop processing immediately
    HIGH = "high"  # Log and continue with error state
    MEDIUM = "medium"  # Log warning and continue
    LOW = "low"  # Debug log only


class EBoekhoudenError(Exception):
    """Base exception for eBoekhouden integration errors."""

    def __init__(
        self,
        message: str,
        severity: ErrorSeverity = ErrorSeverity.CRITICAL,
        context: Dict = None,
        suggestions: List[str] = None,
    ):
        self.message = message
        self.severity = severity
        self.context = context or {}
        self.suggestions = suggestions or []
        super().__init__(self.message)


class ConfigurationError(EBoekhoudenError):
    """Raised when system configuration is invalid or missing."""

    pass


class DataValidationError(EBoekhoudenError):
    """Raised when data validation fails."""

    pass


class ExternalAPIError(EBoekhoudenError):
    """Raised when external API calls fail."""

    pass


class ErrorHandler:
    """Centralized error handling with consistent behavior."""

    def __init__(self, component_name: str):
        self.component_name = component_name
        self.error_log = []

    def handle_error(self, error: Exception, context: Dict = None) -> bool:
        """
        Handle error according to severity level.

        Returns:
            bool: True if processing can continue, False if should stop
        """
        context = context or {}

        if isinstance(error, EBoekhoudenError):
            return self._handle_eboekhouden_error(error, context)
        else:
            return self._handle_generic_error(error, context)

    def _handle_eboekhouden_error(self, error: EBoekhoudenError, context: Dict) -> bool:
        """Handle eBoekhouden-specific errors."""
        error_info = {
            "component": self.component_name,
            "message": error.message,
            "severity": error.severity.value,
            "context": {**error.context, **context},
            "suggestions": error.suggestions,
            "traceback": traceback.format_exc(),
        }

        self.error_log.append(error_info)

        if error.severity == ErrorSeverity.CRITICAL:
            # Log and throw for immediate stopping
            frappe.log_error(
                json.dumps(error_info, indent=2), f"eBoekhouden Critical Error - {self.component_name}"
            )
            frappe.throw(
                error.message
                + (
                    "\n\nSuggestions:\n" + "\n".join(f"• {s}" for s in error.suggestions)
                    if error.suggestions
                    else ""
                ),
                title="eBoekhouden Integration Error",
            )
            return False

        elif error.severity == ErrorSeverity.HIGH:
            # Log error but continue processing
            frappe.log_error(json.dumps(error_info, indent=2), f"eBoekhouden Error - {self.component_name}")
            return True

        elif error.severity == ErrorSeverity.MEDIUM:
            # Log as warning
            frappe.logger().warning(f"eBoekhouden Warning - {self.component_name}: {error.message}")
            return True

        else:  # LOW
            # Debug log only
            frappe.logger().debug(f"eBoekhouden Debug - {self.component_name}: {error.message}")
            return True

    def _handle_generic_error(self, error: Exception, context: Dict) -> bool:
        """Handle unexpected errors."""
        error_info = {
            "component": self.component_name,
            "error_type": type(error).__name__,
            "message": str(error),
            "context": context,
            "traceback": traceback.format_exc(),
        }

        self.error_log.append(error_info)
        frappe.log_error(
            json.dumps(error_info, indent=2), f"eBoekhouden Unexpected Error - {self.component_name}"
        )

        # Generic errors are treated as critical
        frappe.throw(f"Unexpected error in eBoekhouden integration: {str(error)}", title="System Error")
        return False

    def require_configuration(self, condition: bool, message: str, suggestions: List[str] = None) -> None:
        """Require a configuration condition to be met."""
        if not condition:
            raise ConfigurationError(message, severity=ErrorSeverity.CRITICAL, suggestions=suggestions or [])

    def require_data(self, data: Any, field_name: str, context: str = "") -> None:
        """Require data to be present and valid."""
        if not data:
            raise DataValidationError(
                f"Required field '{field_name}' is missing or empty{(' in ' + context) if context else ''}",
                severity=ErrorSeverity.CRITICAL,
                context={"field": field_name, "context": context},
            )

    def validate_choice(self, value: Any, valid_choices: List[Any], field_name: str) -> None:
        """Validate that value is in allowed choices."""
        if value not in valid_choices:
            raise DataValidationError(
                f"Invalid value '{value}' for field '{field_name}'. Valid choices: {valid_choices}",
                severity=ErrorSeverity.CRITICAL,
                context={"field": field_name, "value": value, "valid_choices": valid_choices},
            )

    def get_error_summary(self) -> Dict:
        """Get summary of all errors encountered."""
        severity_counts = {}
        for error in self.error_log:
            severity = error.get("severity", "unknown")
            severity_counts[severity] = severity_counts.get(severity, 0) + 1

        return {
            "total_errors": len(self.error_log),
            "by_severity": severity_counts,
            "recent_errors": self.error_log[-5:] if self.error_log else [],
        }


def with_error_handling(component_name: str):
    """Decorator to add consistent error handling to functions."""

    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            ErrorHandler(component_name)
            try:
                return func(*args, **kwargs)
            except EBoekhoudenError:
                # Re-raise eBoekhouden errors as-is
                raise
            except Exception as e:
                # Convert unexpected errors to eBoekhouden errors
                raise EBoekhoudenError(
                    f"Unexpected error in {func.__name__}: {str(e)}",
                    severity=ErrorSeverity.CRITICAL,
                    context={"function": func.__name__, "args": str(args)[:200]},
                ) from e

        return wrapper

    return decorator


def safe_get_value(
    doctype: str,
    filters: Dict,
    fieldname: str,
    error_handler: ErrorHandler,
    context: str = "",
    required: bool = True,
) -> Optional[Any]:
    """
    Safe database value retrieval with consistent error handling.

    Replaces dangerous empty dictionary patterns with proper validation.
    """
    try:
        if not filters:
            if required:
                error_handler.require_configuration(
                    False,
                    f"No filters provided for {doctype} lookup{(' in ' + context) if context else ''}",
                    suggestions=[f"Ensure {doctype} records exist and filters are properly configured"],
                )
            return None

        value = frappe.db.get_value(doctype, filters, fieldname, order_by="name")

        if required and not value:
            error_handler.require_configuration(
                False,
                f"No {doctype} found matching criteria{(' in ' + context) if context else ''}",
                suggestions=[
                    f"Create at least one {doctype} record",
                    f"Check that filters {filters} match existing records",
                ],
            )

        return value

    except Exception as e:
        if required:
            raise ConfigurationError(
                f"Database error retrieving {doctype}.{fieldname}: {str(e)}",
                severity=ErrorSeverity.CRITICAL,
                context={"doctype": doctype, "filters": filters, "fieldname": fieldname},
            )
        return None


def validate_prerequisites(company: str) -> Dict:
    """Validate all prerequisites using consistent error handling."""
    handler = ErrorHandler("Prerequisites Validation")

    try:
        # Check company exists
        handler.require_data(company, "company")

        company_doc = frappe.get_doc("Company", company)
        handler.require_data(company_doc.cost_center, "cost_center", "Company configuration")

        # Check master data exists
        customer_groups = frappe.db.count("Customer Group", {"is_group": 0})
        handler.require_configuration(
            customer_groups > 0,
            "No customer groups found",
            ["Create at least one Customer Group from Setup > CRM"],
        )

        territories = frappe.db.count("Territory", {"is_group": 0})
        handler.require_configuration(
            territories > 0, "No territories found", ["Create at least one Territory from Setup > CRM"]
        )

        supplier_groups = frappe.db.count("Supplier Group", {"is_group": 0})
        handler.require_configuration(
            supplier_groups > 0,
            "No supplier groups found",
            ["Create at least one Supplier Group from Setup > Buying"],
        )

        return {
            "valid": True,
            "message": "All prerequisites validated successfully",
            "error_summary": handler.get_error_summary(),
        }

    except EBoekhoudenError as e:
        return {
            "valid": False,
            "message": e.message,
            "suggestions": e.suggestions,
            "error_summary": handler.get_error_summary(),
        }


# Export main classes and functions
__all__ = [
    "ErrorSeverity",
    "EBoekhoudenError",
    "ConfigurationError",
    "DataValidationError",
    "ExternalAPIError",
    "ErrorHandler",
    "with_error_handling",
    "safe_get_value",
    "validate_prerequisites",
]
