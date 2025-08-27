"""
Secure Context Manager for User Switching Operations
=====================================================

Implements secure context manager pattern for user switching as recommended by QCE review.
This ensures proper exception handling, guaranteed context restoration, and comprehensive
audit trail for all system context operations.

Usage:
    from verenigingen.utils.secure_context_manager import secure_user_context

    with secure_user_context("Administrator", "member creation") as context:
        member.insert()  # NO ignore_permissions=True
        context.log_operation("member", member.name)

Key Security Features:
- Guaranteed context restoration even on exceptions
- Comprehensive audit trail with operation tracking
- Performance monitoring for concurrent operations
- Proper error handling and logging
- Context validation and safety checks
"""

import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, Optional

import frappe
from frappe import _
from frappe.utils import now_datetime


class SecureContextManager:
    """Secure context manager for user switching operations"""

    def __init__(self, target_user: str, operation_description: str):
        self.target_user = target_user
        self.operation_description = operation_description
        self.original_user = None
        self.start_time = None
        self.operations_log = []
        self.context_id = f"{operation_description}_{int(time.time())}"

    def __enter__(self):
        """Enter secure context with user switching"""
        self.start_time = time.time()
        self.original_user = frappe.session.user

        # Validate target user exists and is enabled
        if not self._validate_target_user():
            raise frappe.ValidationError(f"Invalid target user for context switch: {self.target_user}")

        # Log context switch initiation
        frappe.logger().info(
            f"SECURITY: Initiating context switch - "
            f"From: {self.original_user} To: {self.target_user} "
            f"Operation: {self.operation_description} "
            f"Context ID: {self.context_id}"
        )

        # Perform user switch
        try:
            frappe.set_user(self.target_user)
            frappe.logger().info(f"SECURITY: Context switch successful - Context ID: {self.context_id}")
        except Exception as e:
            frappe.logger().error(
                f"SECURITY: Context switch failed - {str(e)} - Context ID: {self.context_id}"
            )
            raise

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit secure context with guaranteed restoration"""
        try:
            # Calculate operation duration
            duration = time.time() - self.start_time if self.start_time else 0

            # Log context restoration
            status = "SUCCESS" if exc_type is None else f"EXCEPTION: {exc_type.__name__}"

            frappe.logger().info(
                f"SECURITY: Restoring context - "
                f"From: {self.target_user} To: {self.original_user} "
                f"Status: {status} Duration: {duration:.3f}s "
                f"Operations: {len(self.operations_log)} "
                f"Context ID: {self.context_id}"
            )

            # Always restore original user context
            if self.original_user:
                frappe.set_user(self.original_user)

            # Log performance metrics for monitoring
            self._log_performance_metrics(duration, exc_type is None)

        except Exception as restore_error:
            # Critical error - log and attempt emergency restoration
            frappe.logger().error(
                f"CRITICAL: Context restoration failed - {str(restore_error)} - "
                f"Context ID: {self.context_id} - Attempting emergency restoration"
            )

            try:
                # Emergency restoration attempt
                frappe.session.user = self.original_user
                frappe.logger().info(
                    f"EMERGENCY: Context restored via direct session - Context ID: {self.context_id}"
                )
            except Exception as emergency_error:
                frappe.logger().critical(
                    f"CRITICAL: Emergency context restoration failed - {str(emergency_error)} - "
                    f"Context ID: {self.context_id} - Manual intervention required"
                )

    def log_operation(self, operation_type: str, record_name: str, additional_info: Optional[Dict] = None):
        """Log an operation performed within this context"""
        operation_record = {
            "timestamp": now_datetime(),
            "type": operation_type,
            "record": record_name,
            "user": frappe.session.user,
            "context_id": self.context_id,
        }

        if additional_info:
            operation_record.update(additional_info)

        self.operations_log.append(operation_record)

        frappe.logger().info(
            f"AUDIT: Operation logged - "
            f"Type: {operation_type} Record: {record_name} "
            f"User: {frappe.session.user} Context ID: {self.context_id}"
        )

    def _validate_target_user(self) -> bool:
        """Validate target user is suitable for context switch"""
        try:
            user_doc = frappe.get_doc("User", self.target_user)

            if not user_doc.enabled:
                frappe.logger().error(f"Target user {self.target_user} is disabled")
                return False

            if user_doc.user_type != "System User":
                frappe.logger().warning(f"Target user {self.target_user} is not System User type")

            return True

        except frappe.DoesNotExistError:
            frappe.logger().error(f"Target user {self.target_user} does not exist")
            return False
        except Exception as e:
            frappe.logger().error(f"Error validating target user {self.target_user}: {str(e)}")
            return False

    def _log_performance_metrics(self, duration: float, success: bool):
        """Log performance metrics for monitoring"""
        try:
            # Create performance log entry
            perf_data = {
                "context_id": self.context_id,
                "operation": self.operation_description,
                "duration": duration,
                "success": success,
                "operations_count": len(self.operations_log),
                "target_user": self.target_user,
                "timestamp": now_datetime(),
            }

            # Log to system for monitoring
            frappe.logger().info(f"PERFORMANCE: Context operation completed - {perf_data}")

            # If duration exceeds threshold, log warning
            if duration > 5.0:  # 5 second threshold
                frappe.logger().warning(
                    f"PERFORMANCE: Slow context operation detected - "
                    f"Duration: {duration:.3f}s Operation: {self.operation_description} "
                    f"Context ID: {self.context_id}"
                )

        except Exception as e:
            frappe.logger().error(f"Error logging performance metrics: {str(e)}")


@contextmanager
def secure_user_context(target_user: str, operation_description: str):
    """
    Secure context manager for user switching operations

    Args:
        target_user: User to switch to for the operation
        operation_description: Description of the operation for audit trail

    Usage:
        with secure_user_context("Administrator", "member creation") as ctx:
            member.insert()  # NO ignore_permissions=True
            ctx.log_operation("member", member.name)
    """
    context_manager = SecureContextManager(target_user, operation_description)

    with context_manager as ctx:
        yield ctx


def get_creation_user() -> str:
    """Get the configured creation user from Verenigingen Settings"""
    try:
        settings = frappe.get_single("Verenigingen Settings")
        return settings.creation_user or "Administrator"
    except Exception:
        # Fallback if settings not available
        return "Administrator"


# Legacy compatibility function for existing code
def save_with_system_context(doc, context_description="system operation"):
    """
    Legacy compatibility function - use secure_user_context context manager instead

    DEPRECATED: Use secure_user_context context manager for new code:

    # NEW PATTERN:
    with secure_user_context(get_creation_user(), context_description) as ctx:
        doc.save()
        ctx.log_operation(doc.doctype, doc.name)
    """
    with secure_user_context(get_creation_user(), context_description) as ctx:
        doc.save()
        ctx.log_operation(doc.doctype, doc.name)
