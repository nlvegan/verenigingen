"""
Mollie Error Handler
Standardized error handling for Mollie operations

Provides consistent error messaging, logging, and user notification across all
Mollie integration operations.
"""

from typing import Any, Callable, Dict, Optional

import frappe
from frappe import _


class MollieErrorHandler:
    """
    Centralized error handling for Mollie operations

    Features:
    - Consistent error messaging via templates
    - Multi-channel logging (audit trail, error log, user notification)
    - Context enrichment for debugging
    - Severity classification
    - Operation wrapping for consistent error handling

    Usage:
        # Direct error handling
        try:
            response = self.get(f"settlements/{settlement_id}")
        except Exception as e:
            self.error_handler.handle_error(
                error_type="api_connection",
                error=e,
                context={"settlement_id": settlement_id},
                audit_trail=self.audit_trail
            )

        # Wrapped operations
        result = self.error_handler.wrap_operation(
            operation_name="get_settlement",
            operation_callable=lambda: self.get(f"settlements/{settlement_id}"),
            error_type="api_connection",
            context={"settlement_id": settlement_id},
            audit_trail=self.audit_trail
        )
    """

    # Error type definitions with templates and behavior configuration
    ERROR_TEMPLATES = {
        "api_connection": {
            "message": "Failed to connect to Mollie API: {error}",
            "user_message": "Could not connect to Mollie. Please check your internet connection and try again.",
            "severity": "error",
            "log_to_error_log": True,
            "notify_user": True,
        },
        "api_authentication": {
            "message": "Authentication failed with Mollie API: {error}",
            "user_message": "Mollie API authentication failed. Please check your API key configuration in Mollie Settings.",
            "severity": "critical",
            "log_to_error_log": True,
            "notify_user": True,
        },
        "api_rate_limit": {
            "message": "Mollie API rate limit exceeded: {error}",
            "user_message": "Mollie API rate limit exceeded. Please try again in a few minutes.",
            "severity": "warning",
            "log_to_error_log": False,  # Don't clutter error log with rate limits
            "notify_user": True,
        },
        "api_validation": {
            "message": "Mollie API validation failed: {error}",
            "user_message": "Invalid data sent to Mollie: {error}",
            "severity": "error",
            "log_to_error_log": True,
            "notify_user": True,
        },
        "configuration_missing": {
            "message": "Mollie configuration incomplete: {field}",
            "user_message": "Mollie is not properly configured. Missing: {field}. Please configure in Mollie Settings.",
            "severity": "critical",
            "log_to_error_log": True,
            "notify_user": True,
        },
        "resource_not_found": {
            "message": "Mollie resource not found: {resource_type} {resource_id}",
            "user_message": "The requested {resource_type} was not found in Mollie.",
            "severity": "warning",
            "log_to_error_log": False,  # Expected scenario, not an error
            "notify_user": True,
        },
        "data_validation": {
            "message": "Data validation failed: {error}",
            "user_message": "Invalid data: {error}",
            "severity": "error",
            "log_to_error_log": True,
            "notify_user": True,
        },
        "operation_failed": {
            "message": "Operation failed: {operation} - {error}",
            "user_message": "Operation '{operation}' failed. Please try again or contact support.",
            "severity": "error",
            "log_to_error_log": True,
            "notify_user": True,
        },
        "settlement_processing": {
            "message": "Settlement processing failed: {error}",
            "user_message": "Could not process settlement. Please check the settlement status in Mollie dashboard.",
            "severity": "error",
            "log_to_error_log": True,
            "notify_user": True,
        },
        "balance_operation": {
            "message": "Balance operation failed: {error}",
            "user_message": "Could not retrieve balance information. Please try again later.",
            "severity": "error",
            "log_to_error_log": True,
            "notify_user": True,
        },
        "payment_operation": {
            "message": "Payment operation failed: {error}",
            "user_message": "Could not process payment operation. Please check payment status in Mollie dashboard.",
            "severity": "error",
            "log_to_error_log": True,
            "notify_user": True,
        },
    }

    @classmethod
    def handle_error(
        cls,
        error_type: str,
        error: Exception,
        context: Optional[Dict[str, Any]] = None,
        severity_override: Optional[str] = None,
        audit_trail: Optional[Any] = None,
    ) -> None:
        """
        Handle an error with standardized logging and notification

        This method provides centralized error handling with:
        - Template-based error messages for consistency
        - Multi-channel logging (audit trail, error log, user notification)
        - Context preservation for debugging
        - Severity classification

        Args:
            error_type: Error type from ERROR_TEMPLATES (e.g., "api_connection", "configuration_missing")
            error: The exception that occurred
            context: Additional context dict for message formatting and debugging
                    e.g., {"settlement_id": "stl_123", "operation": "reconcile"}
            severity_override: Override default severity ("warning", "error", "critical")
            audit_trail: Optional AuditTrail instance for compliance logging

        Raises:
            The original exception after logging (preserves stack trace)

        Example:
            try:
                response = self.get(f"settlements/{settlement_id}")
            except Exception as e:
                self.error_handler.handle_error(
                    error_type="api_connection",
                    error=e,
                    context={"settlement_id": settlement_id, "operation": "get_settlement"},
                    audit_trail=self.audit_trail
                )
                # Exception is re-raised after logging
        """
        # Get error template, fallback to generic if not found
        if error_type not in cls.ERROR_TEMPLATES:
            frappe.logger().warning(
                f"Unknown error_type '{error_type}' in MollieErrorHandler, using 'operation_failed' fallback"
            )
            error_type = "operation_failed"

        template = cls.ERROR_TEMPLATES[error_type]
        context = context or {}

        # Format messages with error and context
        try:
            internal_message = template["message"].format(error=str(error), **context)
            user_message = template["user_message"].format(error=str(error), **context)
        except KeyError as e:
            # Handle missing context keys gracefully
            frappe.logger().warning(f"Missing context key in error template: {e}")
            internal_message = f"{template['message']} | Error: {error} | Context: {context}"
            user_message = template["user_message"]

        # Determine severity
        severity = severity_override or template["severity"]

        # Log to Frappe error log if configured
        if template["log_to_error_log"]:
            frappe.log_error(
                title=f"Mollie {error_type}: {type(error).__name__}",
                message=f"{internal_message}\n\nContext: {context}\n\n{frappe.get_traceback()}",
            )

        # Log to audit trail if available
        if audit_trail:
            try:
                from verenigingen.verenigingen_payments.core.compliance.audit_trail import (
                    AuditEventType,
                    AuditSeverity,
                )

                severity_map = {
                    "warning": AuditSeverity.WARNING,
                    "error": AuditSeverity.ERROR,
                    "critical": AuditSeverity.CRITICAL,
                }

                audit_trail.log_event(
                    AuditEventType.ERROR_OCCURRED,
                    severity_map.get(severity, AuditSeverity.ERROR),
                    internal_message,
                    details={
                        "error_type": error_type,
                        "exception_type": type(error).__name__,
                        "context": context,
                    },
                )
            except Exception as audit_error:
                # Don't let audit trail errors prevent error handling
                frappe.logger().warning(f"Failed to log to audit trail: {audit_error}")

        # Notify user if configured
        if template["notify_user"]:
            indicator = "red" if severity in ["error", "critical"] else "orange"
            try:
                frappe.msgprint(_(user_message), indicator=indicator, alert=True)
            except Exception as msg_error:
                # Don't let msgprint errors prevent error handling
                frappe.logger().warning(f"Failed to show user message: {msg_error}")

        # Re-raise original exception to preserve stack trace
        # This ensures the exception propagates to the caller after logging
        raise error

    @classmethod
    def wrap_operation(
        cls,
        operation_name: str,
        operation_callable: Callable,
        error_type: str = "operation_failed",
        context: Optional[Dict[str, Any]] = None,
        audit_trail: Optional[Any] = None,
        fallback_value: Any = None,
        suppress_errors: bool = False,
    ) -> Any:
        """
        Wrap an operation with standardized error handling

        This method wraps a callable operation with consistent error handling,
        optionally suppressing errors and returning a fallback value.

        Args:
            operation_name: Name of operation for logging (e.g., "get_settlement", "list_payments")
            operation_callable: Function/lambda to execute
            error_type: Error type from ERROR_TEMPLATES
            context: Additional context dict for error handling
            audit_trail: Optional AuditTrail instance
            fallback_value: Value to return on error (if suppress_errors=True)
            suppress_errors: If True, return fallback_value instead of raising
                           If False (default), exception is raised after logging

        Returns:
            Result of operation_callable or fallback_value on error (if suppress_errors=True)

        Raises:
            Exception if suppress_errors=False (default)

        Example:
            # With error suppression (returns empty list on failure)
            settlements = self.error_handler.wrap_operation(
                operation_name="list_settlements",
                operation_callable=lambda: self.get("settlements", paginated=True),
                error_type="settlement_processing",
                context={"filters": filters},
                audit_trail=self.audit_trail,
                fallback_value=[],
                suppress_errors=True
            )

            # Without suppression (raises exception after logging)
            settlement = self.error_handler.wrap_operation(
                operation_name="get_settlement",
                operation_callable=lambda: self.get(f"settlements/{settlement_id}"),
                error_type="settlement_processing",
                context={"settlement_id": settlement_id},
                audit_trail=self.audit_trail
            )
        """
        context = context or {}
        context["operation"] = operation_name

        try:
            return operation_callable()
        except Exception as e:
            try:
                cls.handle_error(error_type, e, context, audit_trail=audit_trail)
            except Exception:
                if suppress_errors:
                    frappe.logger().info(
                        f"Suppressing error in '{operation_name}', returning fallback value: {fallback_value}"
                    )
                    return fallback_value
                raise

    @classmethod
    def get_error_template(cls, error_type: str) -> Optional[Dict[str, Any]]:
        """
        Get error template for a specific error type

        Args:
            error_type: Error type key

        Returns:
            Error template dict or None if not found
        """
        return cls.ERROR_TEMPLATES.get(error_type)

    @classmethod
    def get_available_error_types(cls) -> list[str]:
        """
        Get list of available error types

        Returns:
            List of error type keys
        """
        return list(cls.ERROR_TEMPLATES.keys())
