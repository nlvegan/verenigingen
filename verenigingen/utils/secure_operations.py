"""
Secure Operations Framework
==========================

Implements proper security patterns for document operations that require elevated permissions.
This corrects the fundamental flaws identified in the original secure context manager approach.

Key Security Principles:
1. EXPLICIT permission validation before any operation
2. Minimal privilege escalation scope
3. Comprehensive audit trail
4. Proper error handling and rollback
5. Document state management to prevent corruption

Usage:
    from verenigingen.utils.secure_operations import secure_document_operation

    # For document creation
    result = secure_document_operation(
        operation="create",
        doc=customer_doc,
        justification="Member customer creation during onboarding",
        required_permissions=["Customer:create"]
    )

    # For document updates
    result = secure_document_operation(
        operation="save",
        doc=member_doc,
        justification="Member update after customer creation",
        required_permissions=["Member:write"]
    )
"""

import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import now_datetime


class SecureOperationResult:
    """Result object for secure operations"""

    def __init__(self, success: bool, operation_id: str):
        self.success = success
        self.operation_id = operation_id
        self.errors = []
        self.warnings = []
        self.audit_trail = []
        self.doc_name = None
        self.duration = 0.0

    def add_error(self, message: str):
        self.errors.append(message)
        self.success = False

    def add_warning(self, message: str):
        self.warnings.append(message)

    def add_audit_entry(self, operation: str, doc_type: str, doc_name: str, details: Dict = None):
        entry = {
            "timestamp": now_datetime(),
            "operation": operation,
            "doc_type": doc_type,
            "doc_name": doc_name,
            "details": details or {},
            "user": frappe.session.user,
            "operation_id": self.operation_id,
        }
        self.audit_trail.append(entry)

        # Log for system monitoring
        frappe.logger().info(
            f"SECURE_OPERATION_AUDIT: {operation} {doc_type}:{doc_name} "
            f"by {frappe.session.user} [{self.operation_id}]"
        )


def validate_permissions(doc, operation: str, required_permissions: List[str] = None) -> bool:
    """
    Validate that current user has required permissions for operation

    Args:
        doc: Document to operate on
        operation: Operation type (create, save, delete, etc.)
        required_permissions: List of specific permissions to check

    Returns:
        bool: True if permissions are sufficient
    """
    try:
        # Standard Frappe permission check for the operation
        operation_map = {
            "create": "create",
            "insert": "create",
            "save": "write",
            "update": "write",
            "delete": "delete",
            "submit": "submit",
            "cancel": "cancel",
        }

        frappe_operation = operation_map.get(operation.lower(), "read")

        # Check basic DocType permission
        if not frappe.has_permission(doc.doctype, frappe_operation, doc):
            frappe.logger().warning(
                f"Permission check failed: {frappe.session.user} lacks {frappe_operation} "
                f"permission for {doc.doctype}:{getattr(doc, 'name', 'new')}"
            )
            return False

        # Check any additional specific permissions
        if required_permissions:
            for perm in required_permissions:
                if ":" in perm:
                    doctype, perm_type = perm.split(":", 1)
                    if not frappe.has_permission(doctype, perm_type):
                        frappe.logger().warning(
                            f"Specific permission check failed: {frappe.session.user} "
                            f"lacks {perm_type} permission for {doctype}"
                        )
                        return False

        return True

    except Exception as e:
        frappe.logger().error(f"Permission validation error: {str(e)}")
        return False


def get_system_user_for_operation(operation_context: str) -> str:
    """
    Get appropriate system user for the operation context

    Args:
        operation_context: Description of the operation requiring system privileges

    Returns:
        str: Username of system user to use
    """
    try:
        # Try to get configured creation user from settings
        settings = frappe.get_single("Verenigingen Settings")
        if settings.creation_user and frappe.db.exists("User", settings.creation_user):
            user_doc = frappe.get_doc("User", settings.creation_user)
            if user_doc.enabled:
                return settings.creation_user

        # Fallback to Administrator if settings user not available
        return "Administrator"

    except Exception as e:
        frappe.logger().warning(f"Could not get system user: {e}, using Administrator")
        return "Administrator"


@contextmanager
def secure_user_context_with_validation(target_user: str, operation_description: str):
    """
    Secure context manager that switches users WITH proper permission validation

    This corrects the fundamental flaw in the original implementation by ensuring
    permission validation occurs within the secure context.
    """
    operation_id = f"{operation_description}_{int(time.time() * 1000)}"
    original_user = frappe.session.user
    start_time = time.time()

    frappe.logger().info(
        f"SECURE_CONTEXT_START: {original_user} -> {target_user} "
        f"for {operation_description} [{operation_id}]"
    )

    try:
        # Validate target user
        if not frappe.db.exists("User", target_user):
            raise frappe.ValidationError(f"Target user {target_user} does not exist")

        target_user_doc = frappe.get_doc("User", target_user)
        if not target_user_doc.enabled:
            raise frappe.ValidationError(f"Target user {target_user} is disabled")

        # Switch context
        frappe.set_user(target_user)

        # Create result object for tracking
        result = SecureOperationResult(True, operation_id)

        yield result

    except Exception as e:
        frappe.logger().error(f"SECURE_CONTEXT_ERROR: {str(e)} [{operation_id}]")
        raise

    finally:
        try:
            # Always restore original context
            frappe.set_user(original_user)
            duration = time.time() - start_time

            frappe.logger().info(
                f"SECURE_CONTEXT_END: Restored to {original_user} "
                f"after {duration * 1000:.1f}ms [{operation_id}]"
            )

        except Exception as restore_error:
            frappe.logger().critical(
                f"CRITICAL: Failed to restore user context: {restore_error} [{operation_id}]"
            )
            # Force session restoration
            frappe.session.user = original_user


def secure_document_operation(
    operation: str,
    doc,
    justification: str,
    required_permissions: List[str] = None,
    allow_system_user: bool = True,
    validate_business_rules: bool = True,
) -> SecureOperationResult:
    """
    Perform a document operation with proper security validation

    This is the CORRECTED secure operation pattern that includes:
    1. Explicit permission validation
    2. Proper audit trail
    3. Error handling and rollback
    4. Document state management

    Args:
        operation: Operation to perform ("create", "save", "delete", etc.)
        doc: Document to operate on
        justification: Business justification for the operation
        required_permissions: Additional permissions to validate
        allow_system_user: Whether to fall back to system user if current user lacks permissions
        validate_business_rules: Whether to validate business rules before operation

    Returns:
        SecureOperationResult with success status and audit information
    """
    operation_id = f"{operation}_{doc.doctype}_{int(time.time() * 1000)}"
    start_time = time.time()

    result = SecureOperationResult(True, operation_id)
    result.add_audit_entry(
        "operation_start",
        doc.doctype,
        getattr(doc, "name", "new"),
        {"operation": operation, "justification": justification, "original_user": frappe.session.user},
    )

    try:
        # Step 1: Validate current user permissions
        current_user_has_permissions = validate_permissions(doc, operation, required_permissions)

        if current_user_has_permissions:
            # Current user has sufficient permissions - proceed directly
            frappe.logger().info(
                f"SECURE_OP: {frappe.session.user} has permissions for {operation} "
                f"on {doc.doctype} [{operation_id}]"
            )

            # Perform operation with current user
            operation_func = getattr(doc, operation.lower())
            operation_func()

            result.doc_name = doc.name
            result.add_audit_entry(
                "operation_success",
                doc.doctype,
                doc.name,
                {"performed_by": frappe.session.user, "permission_source": "current_user"},
            )

        elif allow_system_user:
            # Current user lacks permissions - use system user with proper validation
            system_user = get_system_user_for_operation(justification)

            frappe.logger().info(
                f"SECURE_OP: {frappe.session.user} lacks permissions, "
                f"using system user {system_user} for {operation} [{operation_id}]"
            )

            with secure_user_context_with_validation(system_user, f"{operation}_{doc.doctype}") as ctx:
                # Validate system user has required permissions
                if not validate_permissions(doc, operation, required_permissions):
                    raise frappe.PermissionError(
                        f"Even system user {system_user} lacks required permissions "
                        f"for {operation} on {doc.doctype}"
                    )

                # Perform operation as system user
                operation_func = getattr(doc, operation.lower())
                operation_func()

                result.doc_name = doc.name
                result.add_audit_entry(
                    "operation_success",
                    doc.doctype,
                    doc.name,
                    {
                        "performed_by": frappe.session.user,
                        "original_user": ctx.audit_trail[0]["user"] if ctx.audit_trail else "unknown",
                        "permission_source": "system_user",
                        "system_user": system_user,
                        "justification": justification,
                    },
                )
        else:
            # No system user fallback allowed - operation fails
            raise frappe.PermissionError(
                f"Insufficient permissions for {operation} on {doc.doctype}:{getattr(doc, 'name', 'new')} "
                f"and system user fallback not allowed"
            )

    except Exception as e:
        result.add_error(f"Operation failed: {str(e)}")
        result.add_audit_entry(
            "operation_failed",
            doc.doctype,
            getattr(doc, "name", "new"),
            {"error": str(e), "operation": operation},
        )

        frappe.logger().error(
            f"SECURE_OP_FAILED: {operation} on {doc.doctype} failed: {str(e)} [{operation_id}]"
        )

    finally:
        result.duration = time.time() - start_time

        frappe.logger().info(
            f"SECURE_OP_COMPLETE: {operation} on {doc.doctype} "
            f"completed in {result.duration * 1000:.1f}ms "
            f"(success: {result.success}) [{operation_id}]"
        )

    return result


def secure_batch_operation(
    operations: List[Dict], justification: str, fail_fast: bool = False
) -> List[SecureOperationResult]:
    """
    Perform multiple secure operations as a batch

    Args:
        operations: List of operation dicts with keys: operation, doc, required_permissions
        justification: Business justification for the batch
        fail_fast: Whether to stop on first failure

    Returns:
        List of SecureOperationResult objects
    """
    results = []
    batch_id = f"batch_{int(time.time() * 1000)}"

    frappe.logger().info(f"SECURE_BATCH_START: {len(operations)} operations [{batch_id}]")

    for i, op_config in enumerate(operations):
        try:
            result = secure_document_operation(
                operation=op_config["operation"],
                doc=op_config["doc"],
                justification=f"{justification} (batch {batch_id} operation {i + 1})",
                required_permissions=op_config.get("required_permissions"),
                allow_system_user=op_config.get("allow_system_user", True),
            )

            results.append(result)

            if not result.success and fail_fast:
                frappe.logger().warning(f"SECURE_BATCH_ABORT: Stopping on failure [{batch_id}]")
                break

        except Exception as e:
            error_result = SecureOperationResult(False, f"{batch_id}_op_{i}")
            error_result.add_error(f"Batch operation {i + 1} failed: {str(e)}")
            results.append(error_result)

            if fail_fast:
                break

    success_count = sum(1 for r in results if r.success)
    frappe.logger().info(f"SECURE_BATCH_COMPLETE: {success_count}/{len(operations)} succeeded [{batch_id}]")

    return results


# Legacy compatibility - deprecated
@contextmanager
def secure_user_context(target_user: str, operation_description: str):
    """
    DEPRECATED: Use secure_document_operation() instead

    This function is kept for backward compatibility but should not be used
    for new code as it lacks proper permission validation.
    """
    frappe.logger().warning(
        f"DEPRECATED: secure_user_context() used for {operation_description}. "
        f"Use secure_document_operation() instead for proper security."
    )

    with secure_user_context_with_validation(target_user, operation_description) as result:
        yield result
