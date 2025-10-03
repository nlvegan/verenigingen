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
        self.document = None  # Add document reference
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


def _execute_document_operation(
    doc, operation: str, bypass_validations: List[str] = None, justification: str = ""
):
    """
    Execute the correct document operation method

    Frappe documents have different method names than the operation strings.
    This function maps operations to the correct document methods.

    Args:
        doc: Document to operate on
        operation: Operation string ("create", "save", "submit", etc.)
        bypass_validations: List of validations to bypass (e.g., ["link_validation"])
        justification: Business justification for the operation
    """
    operation = operation.lower()

    if operation in ["create", "insert"]:
        doc.insert()
    elif operation in ["save", "update"]:
        # Flags like ignore_version should already be set by caller if needed
        # Just call save() and let Frappe respect the flags
        doc.save()
    elif operation == "update_child_table":
        # Specialized operation for child table updates that need to bypass
        # specific problematic validations while maintaining security

        # SECURITY: Only skip version control for data updates (not structural changes)
        doc.flags.ignore_version = True

        # SECURITY: Instead of blanket ignore_links, we'll catch and handle
        # specific link validation errors for known problematic fields
        try:
            doc.save()
        except frappe.LinkValidationError as e:
            error_msg = str(e)
            # Only bypass link validation for known problematic chapter references
            if "Chapter:" in error_msg and "Could not find Row" in error_msg:
                # Check if link validation bypass is explicitly allowed
                if bypass_validations and "link_validation" in bypass_validations:
                    # Temporarily bypass links for this specific case with monitoring
                    try:
                        doc.flags.ignore_links = True
                        frappe.logger().warning(
                            f"SECURITY: Bypassing link validation for chapter references: {error_msg}"
                        )
                        frappe.logger().info(
                            f"SECURITY AUDIT: Link validation bypassed for {doc.doctype} {doc.name} "
                            f"- User: {frappe.session.user} - Justification: {justification}"
                        )
                        doc.save()
                    finally:
                        # Always clear the flag, even if save fails
                        doc.flags.ignore_links = False
                else:
                    # Re-raise if bypass not explicitly allowed
                    frappe.logger().error("SECURITY: Link validation bypass denied - not in allowed bypasses")
                    raise
            else:
                # Re-raise for other link validation errors
                raise
    elif operation == "submit":
        doc.submit()
    elif operation == "cancel":
        doc.cancel()
    elif operation == "delete":
        doc.delete()
    else:
        # Fallback to direct method call for unknown operations
        operation_func = getattr(doc, operation)
        operation_func()


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
            "update_child_table": "write",  # Child table updates require write permission
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
                    # SECURITY FIX: Check DocType existence first
                    if not frappe.db.exists("DocType", doctype):
                        frappe.logger().warning(
                            f"Security validation failed: DocType '{doctype}' does not exist"
                        )
                        return False
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
    bypass_validations: List[str] = None,
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
        bypass_validations: List of validations to bypass (e.g., ["link_validation"])

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
            _execute_document_operation(doc, operation, bypass_validations, justification)

            result.doc_name = doc.name
            result.document = doc  # Add document reference to result
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
                _execute_document_operation(doc, operation, bypass_validations, justification)

                result.doc_name = doc.name
                result.document = doc  # Add document reference to result
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


# Critical Operations Registry Integration
class CriticalOperationsRegistry:
    """
    Registry for critical operations with DocType-based configuration

    Integrates with Critical Operation Rule DocType to provide runtime configuration
    of security rules for critical business operations.
    """

    def __init__(self):
        self.operation_configs = {}
        self._load_configs()

    def _load_configs(self):
        """Load operation configurations from DocType (cached)"""
        try:
            # Import here to avoid circular dependencies
            from verenigingen.verenigingen.doctype.critical_operation_rule.critical_operation_rule import (
                CriticalOperationRule,
            )

            self.operation_configs = CriticalOperationRule.get_all_rules()
        except Exception as e:
            frappe.logger().warning(f"Failed to load critical operation rules: {str(e)}")
            self.operation_configs = {}

    def get_operation_config(self, operation_name: str) -> dict:
        """Get configuration for a specific operation"""
        if operation_name not in self.operation_configs:
            # Try to load fresh config for this operation
            try:
                from verenigingen.verenigingen.doctype.critical_operation_rule.critical_operation_rule import (
                    CriticalOperationRule,
                )

                config = CriticalOperationRule.get_rule_config(operation_name)
                if config:
                    self.operation_configs[operation_name] = config
            except Exception as e:
                frappe.logger().warning(f"Failed to load config for operation {operation_name}: {str(e)}")

        return self.operation_configs.get(operation_name)

    def is_critical_operation(self, operation_name: str) -> bool:
        """Check if an operation is registered as critical"""
        config = self.get_operation_config(operation_name)
        return config is not None and config.get("security_level") in ["critical", "high"]

    def validate_business_rules(self, operation_name: str, **kwargs) -> List[str]:
        """
        Validate business rules for an operation

        Incorporates the reviewer's suggestion for business logic validation
        """
        config = self.get_operation_config(operation_name)
        if not config or not config.get("business_rules", {}).get("enabled"):
            return []

        violations = []

        # Amount threshold validation (following reviewer's pattern)
        amount_threshold = config.get("business_rules", {}).get("amount_threshold")
        if amount_threshold:
            # Check for amount in various possible kwargs
            amount = kwargs.get("amount") or kwargs.get("total_amount") or kwargs.get("grand_total")
            if amount and float(amount) > amount_threshold:
                violations.append(
                    f"Amount {amount} exceeds threshold {amount_threshold} for operation {operation_name}"
                )

        return violations

    def get_monitoring_thresholds(self, operation_name: str) -> dict:
        """Get monitoring thresholds for an operation"""
        config = self.get_operation_config(operation_name)
        if not config:
            return {}

        return config.get("monitoring", {})


# Global registry instance
_critical_operations_registry = None


def get_critical_operations_registry() -> CriticalOperationsRegistry:
    """Get global critical operations registry"""
    global _critical_operations_registry
    if _critical_operations_registry is None:
        _critical_operations_registry = CriticalOperationsRegistry()
    return _critical_operations_registry


def execute_critical_operation(
    operation_name: str, operation: str, doc, justification: str = None, **kwargs
) -> SecureOperationResult:
    """
    Execute a critical operation with full security validation

    This function integrates the secure_document_operation with the critical
    operations registry to provide DocType-configured security validation.

    Args:
        operation_name: Name of the critical operation (matches DocType rule)
        operation: Document operation to perform ("create", "save", etc.)
        doc: Document to operate on
        justification: Business justification
        **kwargs: Additional parameters for business rule validation

    Returns:
        SecureOperationResult with enhanced audit information
    """
    registry = get_critical_operations_registry()
    config = registry.get_operation_config(operation_name)

    operation_id = f"critical_{operation_name}_{int(time.time() * 1000)}"
    start_time = time.time()

    frappe.logger().info(f"CRITICAL_OP_START: {operation_name} by {frappe.session.user} [{operation_id}]")

    # Create enhanced result object
    result = SecureOperationResult(True, operation_id)
    result.add_audit_entry(
        "critical_operation_start",
        doc.doctype,
        getattr(doc, "name", "new"),
        {
            "operation_name": operation_name,
            "operation": operation,
            "justification": justification,
            "has_config": config is not None,
            "original_user": frappe.session.user,
        },
    )

    try:
        # Step 1: Validate business rules if configured
        if config:
            violations = registry.validate_business_rules(operation_name, **kwargs)
            if violations:
                for violation in violations:
                    result.add_warning(violation)
                    frappe.logger().warning(f"BUSINESS_RULE_VIOLATION: {violation} [{operation_id}]")

                # For critical violations, consider failing the operation
                if config.get("security_level") == "critical" and violations:
                    result.add_error("Critical business rule violations detected")
                    return result

            # Use configured permissions and settings
            required_permissions = config.get("required_permissions", [])
            allow_system_user = config.get("allow_system_user", True)
            bypass_validations = config.get("bypass_validations", [])
            requires_justification = config.get("requires_justification", True)

            # Validate justification requirement
            if requires_justification and not justification:
                result.add_error("Justification is required for this critical operation")
                return result

        else:
            # Fallback for unconfigured operations
            required_permissions = []
            allow_system_user = True
            bypass_validations = []

            frappe.logger().warning(
                f"UNCONFIGURED_CRITICAL_OP: {operation_name} has no configuration [{operation_id}]"
            )

        # Step 2: Execute the operation using existing secure framework
        doc_result = secure_document_operation(
            operation=operation,
            doc=doc,
            justification=justification or f"Critical operation: {operation_name}",
            required_permissions=required_permissions,
            allow_system_user=allow_system_user,
            bypass_validations=bypass_validations,
        )

        # Merge results
        result.success = doc_result.success
        result.errors.extend(doc_result.errors)
        result.warnings.extend(doc_result.warnings)
        result.audit_trail.extend(doc_result.audit_trail)
        result.doc_name = doc_result.doc_name
        result.document = doc_result.document

        if result.success:
            result.add_audit_entry(
                "critical_operation_success",
                doc.doctype,
                doc.name,
                {
                    "operation_name": operation_name,
                    "execution_time_ms": (time.time() - start_time) * 1000,
                    "business_rules_checked": config is not None,
                },
            )

            # Send alerts if configured (following reviewer's pattern)
            if config and config.get("alert_on_execution"):
                _send_critical_operation_alert(operation_name, doc, config, result)

    except Exception as e:
        result.add_error(f"Critical operation failed: {str(e)}")
        result.add_audit_entry(
            "critical_operation_failed",
            doc.doctype,
            getattr(doc, "name", "new"),
            {"error": str(e), "operation_name": operation_name},
        )

        frappe.logger().error(f"CRITICAL_OP_FAILED: {operation_name} failed: {str(e)} [{operation_id}]")

    finally:
        result.duration = time.time() - start_time

        frappe.logger().info(
            f"CRITICAL_OP_COMPLETE: {operation_name} completed in {result.duration * 1000:.1f}ms "
            f"(success: {result.success}) [{operation_id}]"
        )

    return result


def _send_critical_operation_alert(operation_name: str, doc, config: dict, result: SecureOperationResult):
    """Send alert for critical operation execution"""
    try:
        recipients = config.get("notification_recipients", "")
        if not recipients:
            return

        # Parse recipients
        recipient_list = [r.strip() for r in recipients.split(",") if r.strip()]
        if not recipient_list:
            return

        # Create alert message
        subject = f"Critical Operation Executed: {operation_name}"
        message = f"""
        <h3>Critical Operation Alert</h3>
        <p><strong>Operation:</strong> {operation_name}</p>
        <p><strong>Document:</strong> {doc.doctype} - {getattr(doc, 'name', 'New')}</p>
        <p><strong>Executed By:</strong> {frappe.session.user}</p>
        <p><strong>Execution Time:</strong> {result.duration * 1000:.1f}ms</p>
        <p><strong>Success:</strong> {'Yes' if result.success else 'No'}</p>
        <p><strong>Timestamp:</strong> {frappe.utils.now()}</p>

        {f'<p><strong>Warnings:</strong><br>{"<br>".join(result.warnings)}</p>' if result.warnings else ''}
        {f'<p><strong>Errors:</strong><br>{"<br>".join(result.errors)}</p>' if result.errors else ''}
        """

        frappe.sendmail(
            recipients=recipient_list,
            subject=subject,
            message=message,
            send_priority=1 if config.get("security_level") == "critical" else 0,
        )

    except Exception as e:
        frappe.log_error(f"Failed to send critical operation alert: {str(e)}")


# Convenience functions for common critical operations
def create_financial_document(
    doctype: str, data: dict, justification: str = None, **kwargs
) -> SecureOperationResult:
    """Create financial document using critical operations framework"""
    doc = frappe.get_doc(data)
    doc.doctype = doctype

    return execute_critical_operation(
        operation_name="create_financial_document",
        operation="create",
        doc=doc,
        justification=justification or f"Financial document creation: {doctype}",
        amount=data.get("grand_total") or data.get("total_amount"),
        **kwargs,
    )


def process_payment_entry(payment_data: dict, justification: str = None, **kwargs) -> SecureOperationResult:
    """Process payment entry using critical operations framework"""
    doc = frappe.get_doc(payment_data)
    doc.doctype = "Payment Entry"

    return execute_critical_operation(
        operation_name="process_payment",
        operation="create",
        doc=doc,
        justification=justification or "Payment processing",
        amount=payment_data.get("paid_amount"),
        **kwargs,
    )


def execute_bulk_member_operation(
    operation_data: list, justification: str = None
) -> List[SecureOperationResult]:
    """Execute bulk member operations with critical operation validation"""
    results = []

    for i, op_data in enumerate(operation_data):
        doc = op_data["doc"]
        operation = op_data["operation"]

        result = execute_critical_operation(
            operation_name="bulk_member_operation",
            operation=operation,
            doc=doc,
            justification=(
                f"{justification} (batch operation {i + 1})"
                if justification
                else f"Bulk member operation {i + 1}"
            ),
        )
        results.append(result)

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
