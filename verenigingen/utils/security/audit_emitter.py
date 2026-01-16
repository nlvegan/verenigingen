"""
Audit Emitter for API Security Framework

Provides a simplified interface for emitting security audit events.
Wraps the existing SEPAAuditLogger for consistent audit trail generation.

DEPENDENCY RULES:
- MAY import from types.py, audit_logging.py
- MAY use Frappe for context information
- MUST NOT import from api_security_framework.py (to avoid circular imports)
"""

from typing import Any, Callable, Dict, List, Optional

import frappe

from verenigingen.utils.security.types import AuditEventType, AuditSeverity, SecurityLevel


class AuditEmitter:
    """
    Emit security audit events consistently.

    This class provides a simplified interface for the API security framework
    to log audit events. It delegates to SEPAAuditLogger for actual storage.

    INVARIANTS:
    - All security events are logged with consistent structure
    - Read-only operations skip audit logging unless HIGH/CRITICAL
    - Failed operations are always logged regardless of level
    """

    # Read-only function prefixes that can skip audit logging
    READ_ONLY_PREFIXES = [
        "get_",
        "list_",
        "check_",
        "validate_",
        "test_",
        "analyze_",
        "can_",
        "has_",
        "is_",
        "show_",
        "display_",
        "view_",
        "fetch_",
    ]

    # Functions that never need audit logging (status checks)
    SKIP_AUDIT_FUNCTIONS = [
        "can_suspend_member",
        "get_suspension_status",
        "can_terminate_member",
        "is_chapter_management_enabled",
        "check_donor_exists",
        "get_member_termination_status",
        "check_sepa_mandate_status",
    ]

    def __init__(self):
        """Initialize audit emitter with lazy logger loading."""
        self._audit_logger = None

    def _get_audit_logger(self):
        """Lazily initialize audit logger to avoid circular dependency."""
        if self._audit_logger is None:
            from verenigingen.utils.security.audit_logging import get_audit_logger

            self._audit_logger = get_audit_logger()
        return self._audit_logger

    def should_log_operation(
        self,
        func: Callable,
        security_level: SecurityLevel,
        success: bool,
    ) -> bool:
        """
        Determine if an operation should be audit logged.

        Args:
            func: The function being called
            security_level: Security level of the operation
            success: Whether the operation succeeded

        Returns:
            True if the operation should be logged
        """
        # Always log failed operations
        if not success:
            return True

        func_name = func.__name__.lower()

        # Skip specific functions that never need logging
        if func_name in self.SKIP_AUDIT_FUNCTIONS:
            return False

        # Check if it's a read-only function
        is_read_only = any(func_name.startswith(prefix) for prefix in self.READ_ONLY_PREFIXES)

        if is_read_only:
            # Only log read-only operations for HIGH/CRITICAL levels
            return security_level in [SecurityLevel.CRITICAL, SecurityLevel.HIGH]

        # Log all other operations
        return True

    def log_access_granted(
        self,
        user: str,
        operation: str,
        auth_path: str,
        security_level: SecurityLevel,
        execution_time: Optional[float] = None,
        **context,
    ):
        """
        Log successful access grant.

        Args:
            user: User who was granted access
            operation: Operation that was performed
            auth_path: Authorization path that granted access
            security_level: Security level of the operation
            execution_time: Execution time in seconds
            **context: Additional context for the audit log
        """
        details = {
            "operation": operation,
            "security_level": security_level.value,
            "auth_path": auth_path,
            "user": user,
            **context,
        }

        if execution_time is not None:
            details["execution_time_ms"] = round(execution_time * 1000, 2)

        self._get_audit_logger().log_event(
            "api_call_success",
            AuditSeverity.INFO,
            user=user,
            details=details,
        )

    def log_access_denied(
        self,
        user: str,
        operation: str,
        reason: str,
        security_level: SecurityLevel,
        **context,
    ):
        """
        Log access denial.

        Args:
            user: User who was denied access
            operation: Operation that was attempted
            reason: Reason for denial
            security_level: Security level of the operation
            **context: Additional context for the audit log
        """
        details = {
            "operation": operation,
            "security_level": security_level.value,
            "denial_reason": reason,
            "user": user,
            **context,
        }

        self._get_audit_logger().log_event(
            AuditEventType.UNAUTHORIZED_ACCESS_ATTEMPT,
            AuditSeverity.WARNING,
            user=user,
            details=details,
        )

    def log_rate_limit_exceeded(
        self,
        user: str,
        operation: str,
        current_count: int,
        max_calls: int,
        **context,
    ):
        """
        Log rate limit exceeded event.

        Args:
            user: User who exceeded the limit
            operation: Operation that was rate limited
            current_count: Current request count
            max_calls: Maximum allowed calls
            **context: Additional context for the audit log
        """
        details = {
            "operation": operation,
            "current_count": current_count,
            "max_calls": max_calls,
            "user": user,
            **context,
        }

        self._get_audit_logger().log_event(
            AuditEventType.RATE_LIMIT_EXCEEDED,
            AuditSeverity.WARNING,
            user=user,
            details=details,
        )

    def log_validation_failure(
        self,
        user: str,
        operation: str,
        errors: List[str],
        **context,
    ):
        """
        Log input validation failure.

        Args:
            user: User whose input failed validation
            operation: Operation that failed validation
            errors: List of validation error messages
            **context: Additional context for the audit log
        """
        details = {
            "operation": operation,
            "validation_errors": errors,
            "error_count": len(errors),
            "user": user,
            **context,
        }

        self._get_audit_logger().log_event(
            AuditEventType.VALIDATION_FAILED,
            AuditSeverity.WARNING,
            user=user,
            details=details,
        )

    def log_csrf_failure(
        self,
        user: str,
        operation: str,
        error: str,
        **context,
    ):
        """
        Log CSRF validation failure.

        Args:
            user: User whose CSRF validation failed
            operation: Operation that failed CSRF validation
            error: Error message
            **context: Additional context for the audit log
        """
        details = {
            "operation": operation,
            "error": error,
            "user": user,
            "ip": getattr(frappe.local, "request_ip", "unknown"),
            "method": frappe.request.method if frappe.request else "unknown",
            **context,
        }

        self._get_audit_logger().log_event(
            AuditEventType.CSRF_VALIDATION_FAILED,
            AuditSeverity.WARNING,
            user=user,
            details=details,
        )

    def log_api_call(
        self,
        func: Callable,
        security_level: SecurityLevel,
        success: bool,
        execution_time: Optional[float] = None,
        error: Optional[str] = None,
        **context,
    ):
        """
        Log an API call event (success or failure).

        This is the main method called by the security framework after
        each API call completes.

        Args:
            func: The function that was called
            security_level: Security level of the operation
            success: Whether the call succeeded
            execution_time: Execution time in seconds
            error: Error message if call failed
            **context: Additional context for the audit log
        """
        # Check if we should log this operation
        if not self.should_log_operation(func, security_level, success):
            return

        event_type = "api_call_success" if success else "api_call_failed"
        severity = AuditSeverity.INFO if success else AuditSeverity.ERROR

        details = {
            "function": func.__name__,
            "module": func.__module__,
            "security_level": security_level.value,
            **context,
        }

        if execution_time is not None:
            details["execution_time_ms"] = round(execution_time * 1000, 2)

        if error:
            details["error"] = str(error)

        self._get_audit_logger().log_event(event_type, severity, details=details)


# Singleton instance for convenience
_audit_emitter: Optional[AuditEmitter] = None


def get_audit_emitter() -> AuditEmitter:
    """Get singleton AuditEmitter instance."""
    global _audit_emitter
    if _audit_emitter is None:
        _audit_emitter = AuditEmitter()
    return _audit_emitter
