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

from verenigingen.utils.error_handling import (
    ConfigurationError,
    mask_iban,
    sanitize_audit_details,
    sanitize_error_for_audit,
)

# =============================================================================
# Impersonation Stack - Prevents nested impersonation attacks
# =============================================================================
# Thread-local storage for tracking active impersonations
import threading

_impersonation_stack = threading.local()


def _get_impersonation_stack() -> list:
    """Get the current thread's impersonation stack."""
    if not hasattr(_impersonation_stack, "stack"):
        _impersonation_stack.stack = []
    return _impersonation_stack.stack


def _is_nested_impersonation() -> bool:
    """Check if we're already in an impersonation context."""
    return len(_get_impersonation_stack()) > 0


# =============================================================================
# Observability Metrics
# =============================================================================
# Simple counters for monitoring - can be exported to Prometheus/StatsD

_metrics = threading.local()


def _get_metrics() -> dict:
    """Get thread-local metrics counters."""
    if not hasattr(_metrics, "counters"):
        _metrics.counters = {
            "retries": 0,
            "impersonations": 0,
            "bypass_used": 0,
            "escalation_denied": 0,
            "bypass_denied": 0,
        }
    return _metrics.counters


def increment_metric(name: str, value: int = 1):
    """Increment a metric counter and log it."""
    counters = _get_metrics()
    if name in counters:
        counters[name] += value
        # Log for observability tools that scrape logs
        frappe.logger("verenigingen.secure_ops.metrics").info(
            f"METRIC:{name}={counters[name]} increment={value}"
        )

# =============================================================================
# Security Configuration
# =============================================================================

# Roles allowed to trigger system user escalation
# These roles represent trusted internal staff who can request elevated operations
ESCALATION_ALLOWED_ROLES = frozenset(
    [
        "System Manager",
        "Verenigingen Administrator",
        "Verenigingen System Administrator",
        "Verenigingen Staff",
        "Verenigingen Treasurer",
    ]
)

# Roles allowed to use bypass_validations parameter
# This is more restrictive than escalation - only technical staff who understand
# the security implications should be allowed to bypass validations
BYPASS_VALIDATION_ALLOWED_ROLES = frozenset(
    [
        "System Manager",
        "Verenigingen System Administrator",
    ]
)

# Minimum justification length for audit compliance
MIN_JUSTIFICATION_LENGTH = 10

# Maximum justification length to prevent abuse
MAX_JUSTIFICATION_LENGTH = 500


def verify_document_integrity(doc, bypass_validations: List[str] = None) -> List[str]:
    """
    Verify document integrity after a save operation that used bypass_validations.

    This function checks for common integrity issues that might have been
    introduced by bypassing validations, such as broken links.

    Args:
        doc: Document that was saved with bypass
        bypass_validations: List of validations that were bypassed

    Returns:
        List of integrity violation messages (empty if document is valid)
    """
    violations = []

    if not bypass_validations:
        return violations

    try:
        # If link validation was bypassed, verify links are actually valid
        if "link_validation" in bypass_validations:
            # Check all Link fields in the document
            meta = frappe.get_meta(doc.doctype)
            for df in meta.get_link_fields():
                field_value = doc.get(df.fieldname)
                if field_value:
                    # Verify the linked document exists
                    if not frappe.db.exists(df.options, field_value):
                        violations.append(
                            f"Broken link in {df.fieldname}: {df.options} '{field_value}' does not exist"
                        )

            # Check child tables for broken links
            for df in meta.get_table_fields():
                child_table = doc.get(df.fieldname) or []
                child_meta = frappe.get_meta(df.options)
                for i, row in enumerate(child_table):
                    for child_df in child_meta.get_link_fields():
                        field_value = row.get(child_df.fieldname)
                        if field_value:
                            if not frappe.db.exists(child_df.options, field_value):
                                violations.append(
                                    f"Broken link in {df.fieldname}[{i}].{child_df.fieldname}: "
                                    f"{child_df.options} '{field_value}' does not exist"
                                )

        if violations:
            frappe.logger().warning(
                f"INTEGRITY_VIOLATION: Document {doc.doctype}:{doc.name} has {len(violations)} "
                f"integrity issues after bypass: {violations}"
            )

    except Exception as e:
        frappe.logger().error(f"Error during integrity verification: {e}")
        violations.append(f"Integrity verification failed: {str(e)}")

    return violations


def validate_justification(justification: str, operation: str) -> str:
    """
    Validate and sanitize justification string for audit compliance.

    Args:
        justification: The justification string to validate
        operation: Operation name for error messages

    Returns:
        Sanitized justification string

    Raises:
        frappe.ValidationError: If justification is invalid
    """
    if not justification:
        raise frappe.ValidationError(_("Justification is required for operation '{0}'").format(operation))

    # Strip whitespace
    justification = justification.strip()

    if len(justification) < MIN_JUSTIFICATION_LENGTH:
        raise frappe.ValidationError(
            _("Justification must be at least {0} characters for operation '{1}'").format(
                MIN_JUSTIFICATION_LENGTH, operation
            )
        )

    if len(justification) > MAX_JUSTIFICATION_LENGTH:
        # Truncate with indicator rather than rejecting
        justification = justification[: MAX_JUSTIFICATION_LENGTH - 3] + "..."
        frappe.logger().warning(
            f"Justification truncated to {MAX_JUSTIFICATION_LENGTH} chars for operation {operation}"
        )

    return justification


def can_request_system_escalation(user: str = None) -> bool:
    """
    Check if the specified user is allowed to request system user escalation.

    This prevents unprivileged users from triggering operations that would
    run with elevated system user permissions.

    Args:
        user: Username to check (defaults to current session user)

    Returns:
        True if user can request escalation, False otherwise
    """
    if user is None:
        user = frappe.session.user

    # Administrator can always escalate (but won't be used as fallback anymore)
    if user == "Administrator":
        return True

    try:
        user_roles = set(frappe.get_roles(user))
        return bool(user_roles & ESCALATION_ALLOWED_ROLES)
    except Exception as e:
        frappe.logger().warning(f"Could not check escalation permissions for user {user}: {e}")
        return False


def can_use_bypass_validations(user: str = None) -> bool:
    """
    Check if the specified user is allowed to use bypass_validations.

    This is more restrictive than escalation permissions - only technical staff
    who understand the security implications of bypassing validations should be
    allowed to use this feature.

    Args:
        user: Username to check (defaults to current session user)

    Returns:
        True if user can use bypass_validations, False otherwise
    """
    if user is None:
        user = frappe.session.user

    # Administrator can always bypass validations
    if user == "Administrator":
        return True

    try:
        user_roles = set(frappe.get_roles(user))
        return bool(user_roles & BYPASS_VALIDATION_ALLOWED_ROLES)
    except Exception as e:
        frappe.logger().warning(f"Could not check bypass_validations permissions for user {user}: {e}")
        return False


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
        # Sanitize details to remove PII and sensitive data
        sanitized_details = sanitize_audit_details(details) if details else {}

        entry = {
            "timestamp": now_datetime(),
            "operation": operation,
            "doc_type": doc_type,
            "doc_name": doc_name,
            "details": sanitized_details,
            "user": frappe.session.user,
            "operation_id": self.operation_id,
        }
        self.audit_trail.append(entry)

        # Log for system monitoring (doc_name may contain PII, but this goes to
        # application logs which are access-controlled, not user-visible)
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

        # Higher retry count for high-contention documents during bulk operations
        # Bulk Operation Tracker sees extreme concurrent access during parallel batch processing
        max_retries = 10 if doc.doctype == "Bulk Operation Tracker" else 5
        retry_count = 0

        while retry_count <= max_retries:
            try:
                doc.save()
                break  # Success - exit retry loop
            except frappe.TimestampMismatchError as e:
                retry_count += 1
                increment_metric("retries")  # Track retry attempts for observability

                # Handle concurrent updates gracefully for monitoring/tracking DocTypes
                # These are non-critical updates that can tolerate stale data
                if doc.doctype in ["Bulk Operation Tracker", "API Audit Log"]:
                    if retry_count <= max_retries:
                        frappe.logger().warning(
                            f"Timestamp mismatch on {doc.doctype} {doc.name} (attempt {retry_count}/{max_retries}) "
                            f"during concurrent updates, reloading and retrying"
                        )
                        try:
                            doc.reload()
                        except Exception as reload_error:
                            frappe.logger().error(
                                f"Failed to reload {doc.doctype} {doc.name} after timestamp mismatch: {reload_error}"
                            )
                            raise frappe.ValidationError(
                                f"Document {doc.doctype} {doc.name} could not be reloaded after concurrent update"
                            ) from reload_error

                        # Exponential backoff with jitter for bulk operations
                        # Standard: Retry 1: ~1s, Retry 2: ~2s, Retry 3: ~4s, Retry 4: ~8s, Retry 5: ~16s
                        # Bulk Operation Tracker gets extended backoff to handle extreme contention
                        import random
                        import time

                        if doc.doctype == "Bulk Operation Tracker":
                            # More aggressive backoff with higher jitter for high-contention tracker
                            # Prevents synchronized retry storms when many batches complete simultaneously
                            base_delay = min(2 ** (retry_count - 1), 32)  # Cap at 32s
                            jitter = random.uniform(0, base_delay)  # Full jitter (0-100%)
                        else:
                            base_delay = 2 ** (retry_count - 1)  # 1, 2, 4, 8, 16 seconds
                            jitter = random.uniform(0, 0.5 * base_delay)  # Add up to 50% jitter

                        sleep_time = base_delay + jitter

                        frappe.logger().info(
                            f"Waiting {sleep_time:.1f}s before retry {retry_count}/{max_retries} for {doc.doctype} {doc.name}"
                        )
                        time.sleep(sleep_time)
                    else:
                        # Max retries exceeded - log and fail
                        frappe.logger().error(
                            f"Max retries ({max_retries}) exceeded for {doc.doctype} {doc.name} due to persistent timestamp conflicts"
                        )
                        raise frappe.ValidationError(
                            f"Document {doc.doctype} {doc.name} has persistent concurrent update conflicts. "
                            f"Failed after {max_retries} retry attempts."
                        ) from e
                else:
                    # For critical documents, re-raise immediately with context
                    raise frappe.ValidationError(
                        f"Document {doc.doctype} {doc.name} was modified by another process. "
                        f"Please reload and try again."
                    ) from e
    elif operation == "update_child_table":
        # Specialized operation for child table updates that need to bypass
        # specific problematic validations while maintaining security

        # SECURITY: Only skip version control for data updates (not structural changes)
        doc.flags.ignore_version = True

        # SECURITY: Instead of blanket ignore_links, we'll catch and handle
        # specific link validation errors for known problematic fields
        try:
            doc.save()
        except (frappe.LinkValidationError, frappe.ValidationError) as e:
            error_msg = str(e)
            # Check if this is a link validation error that should be bypassed
            is_link_validation_error = (
                "Chapter:" in error_msg and "Could not find Row" in error_msg
            ) or "Reference DocType must be set first" in error_msg

            if is_link_validation_error:
                # Check if link validation bypass is explicitly allowed
                if bypass_validations and "link_validation" in bypass_validations:
                    # Temporarily bypass links for this specific case with monitoring
                    try:
                        doc.flags.ignore_links = True

                        # CRITICAL: Reload the current modified timestamp from DB
                        # The first save attempt updated the DB timestamp, so we need to reload it
                        # before retry. Frappe's set_user_and_timestamp() will then use this current
                        # value instead of the stale one, preventing timestamp mismatch errors.
                        current_modified = frappe.db.get_value(doc.doctype, doc.name, "modified")
                        if current_modified:
                            doc.modified = current_modified
                            # Also update doc_before_save if it exists to prevent other conflicts
                            if hasattr(doc, "_doc_before_save") and doc._doc_before_save:
                                doc._doc_before_save.modified = current_modified

                        frappe.logger().warning(f"SECURITY: Bypassing link validation: {error_msg}")
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
                # Re-raise for other validation errors
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

                    # SECURITY FIX: Pass document context when checking permissions
                    # for the same DocType as the operation document. This ensures
                    # owner-based and document-specific permissions are respected.
                    perm_doc = doc if doctype == doc.doctype else None
                    if not frappe.has_permission(doctype, perm_type, doc=perm_doc):
                        frappe.logger().warning(
                            f"Specific permission check failed: {frappe.session.user} "
                            f"lacks {perm_type} permission for {doctype}"
                            f"{' (with doc context)' if perm_doc else ''}"
                        )
                        return False

        return True

    except Exception as e:
        frappe.logger().error(f"Permission validation error: {str(e)}")
        return False


def get_system_user_for_operation(operation_context: str) -> str:
    """
    Get appropriate system user for the operation context.

    SECURITY: This function no longer falls back to Administrator.
    If creation_user is not properly configured, operations will fail
    with a clear error message rather than silently elevating to Administrator.

    Args:
        operation_context: Description of the operation requiring system privileges

    Returns:
        str: Username of system user to use

    Raises:
        ConfigurationError: If creation_user is not configured or invalid
    """
    try:
        settings = frappe.get_single("Verenigingen Settings")

        if not settings.creation_user:
            frappe.logger().error(
                f"SECURITY: creation_user not configured in Verenigingen Settings. "
                f"Operation '{operation_context}' cannot proceed with system privileges."
            )
            raise ConfigurationError(
                _(
                    "System user for automated operations is not configured. "
                    "Please set 'Creation User' in Verenigingen Settings."
                )
            )

        if not frappe.db.exists("User", settings.creation_user):
            frappe.logger().error(
                f"SECURITY: Configured creation_user '{settings.creation_user}' does not exist. "
                f"Operation '{operation_context}' cannot proceed."
            )
            raise ConfigurationError(
                _(
                    "Configured system user '{0}' does not exist. "
                    "Please update 'Creation User' in Verenigingen Settings."
                ).format(settings.creation_user)
            )

        user_doc = frappe.get_doc("User", settings.creation_user)
        if not user_doc.enabled:
            frappe.logger().error(
                f"SECURITY: Configured creation_user '{settings.creation_user}' is disabled. "
                f"Operation '{operation_context}' cannot proceed."
            )
            raise ConfigurationError(
                _(
                    "Configured system user '{0}' is disabled. "
                    "Please enable this user or update 'Creation User' in Verenigingen Settings."
                ).format(settings.creation_user)
            )

        return settings.creation_user

    except ConfigurationError:
        # Re-raise configuration errors without wrapping
        raise
    except Exception as e:
        frappe.logger().error(f"SECURITY: Failed to get system user for operation '{operation_context}': {e}")
        raise ConfigurationError(
            _(
                "Could not determine system user for operation. "
                "Please check Verenigingen Settings configuration."
            )
        ) from e


@contextmanager
def secure_user_context_with_validation(target_user: str, operation_description: str):
    """
    Secure context manager that switches users WITH proper permission validation.

    This corrects the fundamental flaw in the original implementation by ensuring
    permission validation occurs within the secure context.

    Security Features:
    - Prevents nested impersonation attacks
    - Restores full session state (not just user)
    - Emits observability metrics
    - Comprehensive audit logging
    """
    operation_id = f"{operation_description}_{int(time.time() * 1000)}"
    original_user = frappe.session.user
    start_time = time.time()

    # SECURITY: Prevent nested impersonation attacks
    # Nested impersonation can lead to privilege confusion and audit trail issues
    if _is_nested_impersonation():
        current_stack = _get_impersonation_stack()
        frappe.logger().error(
            f"SECURITY: Nested impersonation attempt blocked. "
            f"Current stack: {current_stack}, attempted: {target_user} [{operation_id}]"
        )
        raise frappe.PermissionError(
            _("Nested impersonation is not allowed. Complete the current operation first.")
        )

    # Capture full session state for restoration
    original_session_data = {
        "user": frappe.session.user,
        "sid": getattr(frappe.session, "sid", None),
        "data": dict(frappe.session.data) if hasattr(frappe.session, "data") else {},
    }

    frappe.logger().info(
        f"SECURE_CONTEXT_START: {original_user} -> {target_user} "
        f"for {operation_description} [{operation_id}]"
    )

    # Track this impersonation in the stack
    impersonation_entry = {
        "original_user": original_user,
        "target_user": target_user,
        "operation_id": operation_id,
        "timestamp": time.time(),
    }
    _get_impersonation_stack().append(impersonation_entry)

    try:
        # Validate target user
        if not frappe.db.exists("User", target_user):
            raise frappe.ValidationError(f"Target user {target_user} does not exist")

        target_user_doc = frappe.get_doc("User", target_user)
        if not target_user_doc.enabled:
            raise frappe.ValidationError(f"Target user {target_user} is disabled")

        # Switch context
        frappe.set_user(target_user)

        # Emit impersonation metric
        increment_metric("impersonations")

        # Create result object for tracking
        result = SecureOperationResult(True, operation_id)

        yield result

    except Exception as e:
        frappe.logger().error(f"SECURE_CONTEXT_ERROR: {str(e)} [{operation_id}]")
        raise

    finally:
        # Always pop from impersonation stack
        stack = _get_impersonation_stack()
        if stack and stack[-1]["operation_id"] == operation_id:
            stack.pop()

        try:
            # Restore original user context
            frappe.set_user(original_session_data["user"])

            # Restore additional session data if it was present
            if original_session_data["sid"]:
                frappe.session.sid = original_session_data["sid"]

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
            frappe.session.user = original_session_data["user"]
            if original_session_data["sid"]:
                frappe.session.sid = original_session_data["sid"]


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
    5. Justification validation for audit compliance
    6. Role-based escalation gating
    7. Role-based bypass_validations gating

    Args:
        operation: Operation to perform ("create", "save", "delete", etc.)
        doc: Document to operate on
        justification: Business justification for the operation (min 10 chars required)
        required_permissions: Additional permissions to validate
        allow_system_user: Whether to fall back to system user if current user lacks permissions
        validate_business_rules: Whether to validate business rules before operation
        bypass_validations: List of validations to bypass (e.g., ["link_validation"]).
            SECURITY: Only System Manager and Verenigingen System Administrator roles
            can use this parameter.

    Returns:
        SecureOperationResult with success status and audit information

    Raises:
        frappe.ValidationError: If justification is invalid
        frappe.PermissionError: If user cannot request escalation or bypass_validations
        ConfigurationError: If system user is not properly configured
    """
    operation_id = f"{operation}_{doc.doctype}_{int(time.time() * 1000)}"
    start_time = time.time()
    original_user = frappe.session.user

    # Step 0: Validate justification upfront for audit compliance
    validated_justification = validate_justification(justification, operation)

    # Step 0.5: Validate role-gating for bypass_validations
    # Only System Manager and Verenigingen System Administrator can use bypass_validations
    if bypass_validations and not can_use_bypass_validations(original_user):
        increment_metric("bypass_denied")
        frappe.logger().warning(
            f"SECURITY: User {original_user} attempted to use bypass_validations={bypass_validations} "
            f"for {operation} on {doc.doctype} but lacks bypass privileges [{operation_id}]"
        )
        raise frappe.PermissionError(
            _(
                "You do not have permission to bypass validations. "
                "This feature is restricted to System Administrators."
            )
        )

    # Track bypass usage for metrics
    if bypass_validations:
        increment_metric("bypass_used")

    result = SecureOperationResult(True, operation_id)
    result.add_audit_entry(
        "operation_start",
        doc.doctype,
        getattr(doc, "name", "new"),
        {
            "operation": operation,
            "justification": validated_justification,
            "original_user": original_user,
            "bypass_validations": bypass_validations or [],  # AUDIT: Record bypasses
        },
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

            # SECURITY: Post-validation after bypass to verify document integrity
            if bypass_validations:
                integrity_violations = verify_document_integrity(doc, bypass_validations)
                for violation in integrity_violations:
                    result.add_warning(f"INTEGRITY: {violation}")

            result.doc_name = doc.name
            result.document = doc  # Add document reference to result
            result.add_audit_entry(
                "operation_success",
                doc.doctype,
                doc.name,
                {
                    "performed_by": frappe.session.user,
                    "permission_source": "current_user",
                    "bypass_validations": bypass_validations or [],
                    "integrity_warnings": len(integrity_violations) if bypass_validations else 0,
                },
            )

        elif allow_system_user:
            # Current user lacks permissions - check if they can request escalation
            if not can_request_system_escalation(original_user):
                increment_metric("escalation_denied")
                frappe.logger().warning(
                    f"SECURITY: User {original_user} attempted system escalation for "
                    f"{operation} on {doc.doctype} but lacks escalation privileges [{operation_id}]"
                )
                raise frappe.PermissionError(
                    _(
                        "You do not have permission to request elevated system operations. "
                        "Please contact an administrator."
                    )
                )

            # User is authorized to request escalation - get system user
            system_user = get_system_user_for_operation(validated_justification)

            frappe.logger().info(
                f"SECURE_OP: {original_user} lacks permissions, "
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

                # SECURITY: Post-validation after bypass to verify document integrity
                integrity_warnings_count = 0
                if bypass_validations:
                    integrity_violations = verify_document_integrity(doc, bypass_validations)
                    integrity_warnings_count = len(integrity_violations)
                    for violation in integrity_violations:
                        result.add_warning(f"INTEGRITY: {violation}")

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
                        "bypass_validations": bypass_validations or [],
                        "integrity_warnings": integrity_warnings_count,
                    },
                )
        else:
            # No system user fallback allowed - operation fails
            raise frappe.PermissionError(
                f"Insufficient permissions for {operation} on {doc.doctype}:{getattr(doc, 'name', 'new')} "
                f"and system user fallback not allowed"
            )

    except Exception as e:
        # Capture full traceback for debugging
        error_traceback = frappe.get_traceback()
        result.add_error(f"Operation failed: {str(e)}")
        result.add_audit_entry(
            "operation_failed",
            doc.doctype,
            getattr(doc, "name", "new"),
            {"error": str(e), "operation": operation, "traceback": error_traceback},
        )

        frappe.logger().error(
            f"SECURE_OP_FAILED: {operation} on {doc.doctype} failed: {str(e)} [{operation_id}]\n{error_traceback}"
        )

        # Also log to Error Log for visibility
        frappe.log_error(
            title=f"Secure Operation Failed: {operation} on {doc.doctype}",
            message=f"Operation: {operation}\nDocument: {doc.doctype} {getattr(doc, 'name', 'new')}\nError: {str(e)}\n\n{error_traceback}",
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
    """Send in-app alert for critical operation execution"""
    from frappe.utils import escape_html

    from verenigingen.utils.notification_helpers import create_system_notification

    try:
        recipients = config.get("notification_recipients", "")
        if not recipients:
            return

        # Parse recipients
        recipient_list = [r.strip() for r in recipients.split(",") if r.strip()]
        if not recipient_list:
            return

        # Escape user-controlled data to prevent XSS
        safe_operation = escape_html(operation_name or "")
        safe_doctype = escape_html(doc.doctype or "")
        safe_docname = escape_html(getattr(doc, "name", "New") or "New")
        safe_user = escape_html(frappe.session.user or "")

        # Escape warnings and errors
        safe_warnings = "<br>".join(escape_html(str(w)) for w in (result.warnings or []))
        safe_errors = "<br>".join(escape_html(str(e)) for e in (result.errors or []))

        # Create alert message
        subject = f"Critical Operation Executed: {safe_operation}"
        message = f"""
        <h3>Critical Operation Alert</h3>
        <p><strong>Operation:</strong> {safe_operation}</p>
        <p><strong>Document:</strong> {safe_doctype} - {safe_docname}</p>
        <p><strong>Executed By:</strong> {safe_user}</p>
        <p><strong>Execution Time:</strong> {result.duration * 1000:.1f}ms</p>
        <p><strong>Success:</strong> {'Yes' if result.success else 'No'}</p>
        <p><strong>Timestamp:</strong> {frappe.utils.now()}</p>

        {f'<p><strong>Warnings:</strong><br>{safe_warnings}</p>' if result.warnings else ''}
        {f'<p><strong>Errors:</strong><br>{safe_errors}</p>' if result.errors else ''}
        """

        create_system_notification(
            recipients=recipient_list,
            subject=subject,
            message=message,
            notification_type="Alert",
            document_type=doc.doctype,
            document_name=getattr(doc, "name", None),
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
