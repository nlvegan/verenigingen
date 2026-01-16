"""
Standardized Error Handling and Exception Management

This module provides comprehensive error handling capabilities for the Verenigingen
association management system. It establishes consistent error handling patterns,
structured logging, custom exception hierarchies, and defensive programming utilities
to ensure system reliability and operational excellence.

Key Features:
- Comprehensive custom exception hierarchy for domain-specific errors
- Standardized error logging with structured context and audit trails
- API error handling decorators for consistent error responses
- Defensive programming utilities for safe data access and validation
- Performance-optimized caching with TTL support
- Batch processing with robust error handling and recovery
- Permission validation and access control utilities

Business Context:
Error handling is critical for maintaining system reliability and user experience
in the association management system. This module addresses:
- SEPA payment processing failures requiring compliance audit trails
- Member data validation errors needing user-friendly messaging
- Permission violations requiring security audit logging
- Integration failures with external systems (eBoekhouden, banking)
- Batch processing errors needing partial recovery capabilities

Architecture:
This utility integrates with:
- Frappe's exception and validation framework
- System monitoring and alerting infrastructure
- Audit logging and compliance tracking systems
- API response standardization for frontend integration
- Development debugging and operational troubleshooting tools

Exception Hierarchy:
- VerenigingenException: Base exception for all application errors
- MembershipError: Member management and lifecycle errors
- PaymentError: Payment processing and financial errors
- SEPAError: SEPA direct debit compliance and processing errors
- VolunteerError: Volunteer management and coordination errors
- ChapterError: Chapter operations and regional management errors
- PermissionError: Access control and authorization failures
- ValidationError: Data validation and business rule violations
- ConfigurationError: System configuration and setup issues

Error Handling Patterns:
- API decorators for consistent error responses and logging
- Safe database access with fallback values and error recovery
- Batch processing with partial failure recovery and retry logic
- Permission validation with user-friendly error messages
- Validation utilities for common data formats and business rules

Development Utilities:
- Caching decorators for performance optimization
- Validation helpers for common patterns (email, postal codes)
- Permission checking utilities for access control
- Entity existence validation for defensive programming
- Structured logging for debugging and operational awareness

Author: Development Team
Date: 2025-08-02
Version: 1.0
"""

import time
import traceback
from functools import wraps
from typing import Any, Callable, Dict, Optional, Union

import frappe
from frappe import _


class VerenigingenException(frappe.ValidationError):
    """Base exception class for Verenigingen-specific errors"""

    pass


class MembershipError(VerenigingenException):
    """Raised when membership-related operations fail"""

    pass


class PaymentError(VerenigingenException):
    """Raised when payment processing fails"""

    pass


class SEPAError(PaymentError):
    """Raised when SEPA direct debit operations fail"""

    pass


class VolunteerError(VerenigingenException):
    """Raised when volunteer-related operations fail"""

    pass


class ChapterError(VerenigingenException):
    """Raised when chapter-related operations fail"""

    pass


class PermissionError(VerenigingenException):
    """Raised when user lacks required permissions"""

    pass


class ValidationError(VerenigingenException):
    """Raised when data validation fails"""

    pass


class ConfigurationError(VerenigingenException):
    """Raised when system configuration is invalid"""

    pass


def get_logger(module_name: str):
    """
    Get a standardized logger for a module

    Args:
        module_name: Name of the module (e.g., 'verenigingen.api.member_management')

    Returns:
        Configured logger instance
    """
    return frappe.logger(module_name, allow_site=True, file_count=50)


def log_error(error: Exception, context: Dict[str, Any] = None, module: str = None):
    """
    Log an error with standardized formatting and context

    Args:
        error: The exception that occurred
        context: Additional context information
        module: Module name where error occurred
    """
    logger = get_logger(module or "verenigingen.error")

    error_context = {
        "user": frappe.session.user if frappe.session else "System",
        "site": frappe.local.site if frappe.local else "Unknown",
        "error_type": type(error).__name__,
        "error_message": str(error),
    }

    # Add context without overwriting logging's reserved fields
    if context:
        for key, value in context.items():
            # Avoid reserved logging fields that could cause conflicts
            if key not in [
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
            ]:
                error_context[f"ctx_{key}"] = value

    # Log the error with safe context
    logger.error(f"Error in {module}: {str(error)}", extra=error_context, exc_info=True)

    # Also create a Frappe Error Log entry for tracking
    frappe.log_error(
        title=f"{module}: {type(error).__name__}", message=f"Error: {str(error)}\nContext: {error_context}"
    )


def handle_api_error(func: Callable) -> Callable:
    """
    Decorator to provide standardized error handling for API endpoints

    Usage:
        @frappe.whitelist()
        @handle_api_error
        def my_api_function():
            # Function implementation
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except VerenigingenException as e:
            # Known application errors - return structured error
            log_error(e, context={"function": func.__name__}, module=func.__module__)
            return {
                "success": False,
                "error": {
                    "type": type(e).__name__,
                    "message": str(e),
                    "code": getattr(e, "error_code", "VALIDATION_ERROR"),
                },
            }
        except frappe.PermissionError as e:
            # Permission errors
            log_error(e, context={"function": func.__name__}, module=func.__module__)
            return {
                "success": False,
                "error": {
                    "type": "PermissionError",
                    "message": _("Access denied: {0}").format(str(e)),
                    "code": "PERMISSION_DENIED",
                },
            }
        except frappe.ValidationError as e:
            # Frappe validation errors
            log_error(e, context={"function": func.__name__}, module=func.__module__)
            return {
                "success": False,
                "error": {"type": "ValidationError", "message": str(e), "code": "VALIDATION_ERROR"},
            }
        except Exception as e:
            # Unexpected errors - log with full traceback
            log_error(
                e,
                context={
                    "function": func.__name__,
                    "args": str(args)[:200],  # Limit arg length
                    "kwargs": str(kwargs)[:200],
                    "traceback": traceback.format_exc(),
                },
                module=func.__module__,
            )

            return {
                "success": False,
                "error": {
                    "type": "SystemError",
                    "message": _("An unexpected error occurred. Please contact support."),
                    "code": "SYSTEM_ERROR",
                },
            }

    return wrapper


def validate_required_fields(data: Dict[str, Any], required_fields: list) -> None:
    """
    Validate that required fields are present in data

    Args:
        data: Dictionary to validate
        required_fields: List of required field names

    Raises:
        ValidationError: If any required fields are missing
    """
    missing_fields = [field for field in required_fields if not data.get(field)]

    if missing_fields:
        raise ValidationError(_("Required fields missing: {0}").format(", ".join(missing_fields)))


def validate_email(email: str) -> None:
    """
    Validate email format

    Args:
        email: Email address to validate

    Raises:
        ValidationError: If email format is invalid
    """
    if not email or "@" not in email:
        raise ValidationError(_("Invalid email address: {0}").format(email))


def validate_postal_code(postal_code: str, country: str = "NL") -> None:
    """
    Validate postal code format for specific countries

    Args:
        postal_code: Postal code to validate
        country: Country code (default: NL for Netherlands)

    Raises:
        ValidationError: If postal code format is invalid
    """
    if country == "NL":
        # Dutch postal code format: 1234AB
        import re

        if not re.match(r"^\d{4}[A-Z]{2}$", postal_code.upper().replace(" ", "")):
            raise ValidationError(_("Invalid Dutch postal code format. Expected format: 1234AB"))
    # Add other country validations as needed


def require_permission(permission_type: str, throw: bool = True) -> bool:
    """
    Check if current user has required permission

    Args:
        permission_type: Type of permission to check
        throw: Whether to throw exception if permission denied

    Returns:
        True if user has permission

    Raises:
        PermissionError: If user lacks permission and throw=True
    """
    # Implementation depends on specific permission system
    # This is a placeholder for the actual permission checking logic

    has_perm = True  # Replace with actual permission check

    if not has_perm and throw:
        raise PermissionError(_("Access denied. Required permission: {0}").format(permission_type))

    return has_perm


def safe_get_doc(doctype: str, name: str, for_update: bool = False) -> Optional[Any]:
    """
    Safely get a document with proper error handling

    Args:
        doctype: Document type
        name: Document name
        for_update: Whether document will be updated

    Returns:
        Document instance or None if not found

    Raises:
        PermissionError: If user lacks read permission
    """
    try:
        return frappe.get_doc(doctype, name, for_update=for_update)
    except frappe.DoesNotExistError:
        return None
    except frappe.PermissionError as e:
        raise PermissionError(_("Access denied to {0} {1}").format(doctype, name)) from e


def safe_db_get_value(
    doctype: str, filters: Union[str, Dict], fieldname: Union[str, list], default: Any = None
) -> Any:
    """
    Safely get database value with error handling

    Args:
        doctype: Document type
        filters: Filters for the query
        fieldname: Field name(s) to retrieve
        default: Default value if not found

    Returns:
        Field value(s) or default
    """
    try:
        result = frappe.db.get_value(doctype, filters, fieldname)
        return result if result is not None else default
    except Exception as e:
        log_error(
            e,
            context={"doctype": doctype, "filters": str(filters), "fieldname": fieldname},
            module="verenigingen.utils.error_handling",
        )
        return default


def batch_process_with_error_handling(
    items: list, process_function: Callable, batch_size: int = 100
) -> Dict[str, Any]:
    """
    Process items in batches with comprehensive error handling

    Args:
        items: List of items to process
        process_function: Function to process each item
        batch_size: Number of items to process per batch

    Returns:
        Dictionary with success/error counts and failed items
    """
    results = {"total": len(items), "processed": 0, "errors": 0, "failed_items": []}

    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]

        for item in batch:
            try:
                process_function(item)
                results["processed"] += 1
            except Exception as e:
                results["errors"] += 1
                results["failed_items"].append(
                    {"item": str(item), "error": str(e), "error_type": type(e).__name__}
                )

                log_error(
                    e,
                    context={
                        "item": str(item),
                        "batch_index": i // batch_size,
                        "item_index": results["processed"] + results["errors"],
                    },
                    module="verenigingen.utils.error_handling",
                )

        # Commit after each batch to avoid large transactions
        frappe.db.commit()

    return results


# Configuration for error handling
ERROR_HANDLING_CONFIG = {
    "max_error_message_length": 1000,
    "log_sensitive_data": False,
    "include_stack_trace": True,
    "error_notification_roles": ["System Manager", "Verenigingen System Admin"],
    "critical_error_threshold": 10,  # Number of errors before alerting
}


def cache_with_ttl(ttl=300):
    """
    Decorator to cache function results with time-to-live

    Args:
        ttl: Time to live in seconds (default: 5 minutes)

    Usage:
        @cache_with_ttl(ttl=600)
        def expensive_function():
            # Function implementation
    """

    def decorator(func):
        cache = {}

        @wraps(func)
        def wrapper(*args, **kwargs):
            # Create cache key from function name and arguments
            cache_key = f"{func.__name__}:{hash(str(args) + str(sorted(kwargs.items())))}"
            current_time = time.time()

            # Check if we have a cached result that's still valid
            if cache_key in cache:
                cached_result, cached_time = cache[cache_key]
                if current_time - cached_time < ttl:
                    return cached_result

            # Execute function and cache result
            result = func(*args, **kwargs)
            cache[cache_key] = (result, current_time)

            # Clean up old cache entries (simple cleanup)
            keys_to_remove = []
            for key, (cached_result, cached_time) in cache.items():
                if current_time - cached_time >= ttl:
                    keys_to_remove.append(key)

            for key in keys_to_remove:
                del cache[key]

            return result

        return wrapper

    return decorator


def setup_error_monitoring():
    """
    Set up error monitoring and alerting
    Called during app initialization
    """
    # This would set up error monitoring, alerting, etc.
    # Implementation depends on monitoring infrastructure
    pass


def require_permission_decorator(
    doctype: str, perm_type: str = "read", custom_message: str = None
) -> Callable:
    """
    Decorator to require specific permissions for page access - development helper

    Args:
        doctype: DocType to check permission for
        perm_type: Type of permission (read, write, create, delete)
        custom_message: Custom error message
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not frappe.has_permission(doctype, perm_type):
                message = custom_message or f"You don't have {perm_type} permission for {doctype}"
                frappe.throw(_(message), frappe.PermissionError)
            return func(*args, **kwargs)

        return wrapper

    return decorator


def validate_admin_access(custom_message: str = None) -> None:
    """
    Validate user has admin access - development utility

    Args:
        custom_message: Custom error message
    """
    if "System Manager" not in frappe.get_roles():
        message = custom_message or "You don't have permission to access this page"
        frappe.throw(_(message), frappe.PermissionError)


def validate_entity_exists(doctype: str, name: str, custom_message: str = None) -> str:
    """
    Validate that an entity exists and return its name - development helper

    Args:
        doctype: DocType to check
        name: Entity name/ID to validate
        custom_message: Custom error message

    Returns:
        Entity name if found

    Raises:
        DoesNotExistError: If entity not found
    """
    if not name:
        message = custom_message or f"{doctype} parameter is required"
        frappe.throw(_(message), frappe.ValidationError)

    try:
        # Verify entity exists by trying to get its name
        existing_name = frappe.db.get_value(doctype, name, "name")
        if not existing_name:
            message = custom_message or f"{doctype} not found"
            frappe.throw(_(message), frappe.DoesNotExistError)
        return existing_name
    except frappe.DoesNotExistError:
        message = custom_message or f"{doctype} not found"
        frappe.throw(_(message), frappe.DoesNotExistError)


def validate_user_logged_in(custom_message: str = None) -> str:
    """
    Validate user is logged in and return user email - development helper

    Args:
        custom_message: Custom error message

    Returns:
        User email

    Raises:
        PermissionError: If user is guest
    """
    if frappe.session.user == "Guest":
        message = custom_message or "Please login to access this page"
        frappe.throw(_(message), frappe.PermissionError)
    return frappe.session.user


def validate_member_for_user(user: str = None, custom_message: str = None) -> str:
    """
    Validate user has associated member record - development helper

    Args:
        user: User email (defaults to current user)
        custom_message: Custom error message

    Returns:
        Member name

    Raises:
        DoesNotExistError: If no member found
    """
    if not user:
        user = validate_user_logged_in()

    # Try multiple lookup methods
    member = frappe.db.get_value("Member", {"email": user}, "name") or frappe.db.get_value(
        "Member", {"user": user}, "name"
    )

    if not member:
        message = custom_message or "No member record found for your account"
        frappe.throw(_(message), frappe.DoesNotExistError)

    return member


# =============================================================================
# Error Message Sanitization Utilities
# =============================================================================
# These utilities provide consistent error sanitization across the application
# for audit logs, API responses, and user-facing error messages.

import re

# PII patterns for sanitization
_EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE_PATTERN = re.compile(r"\+?\d{10,15}|\d{2,4}[\s-]?\d{3,4}[\s-]?\d{3,4}")

# Sensitive keyword patterns that indicate internal system information
_SENSITIVE_KEYWORDS = frozenset([
    "traceback",
    "file",
    "line",
    "internal",
    "database",
    "sql",
    "query",
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
])

# API key patterns (Mollie, Stripe, etc.)
_API_KEY_PATTERNS = ["test_", "live_", "sk_", "pk_", "bearer "]


def sanitize_error_for_audit(
    error: Union[str, Exception],
    max_length: int = 500,
    remove_stack_trace: bool = True,
    redact_pii: bool = True,
    filter_sensitive_keywords: bool = False,
    fallback_message: str = None,
) -> Optional[str]:
    """
    Sanitize error message for safe storage in audit logs.

    This is the primary utility for cleaning error messages before storing
    them in audit logs, displaying to users, or including in API responses.

    Args:
        error: Raw error message or Exception object
        max_length: Maximum character length (default: 500)
        remove_stack_trace: Remove multi-line stack traces, keep first line only
        redact_pii: Redact email addresses and phone numbers
        filter_sensitive_keywords: Replace messages containing sensitive keywords
                                   with generic message
        fallback_message: Message to use when sensitive keywords detected
                         (default: "Internal error - contact administrator")

    Returns:
        Sanitized error message safe for audit storage, or None if input is empty

    Examples:
        >>> sanitize_error_for_audit("Simple error")
        'Simple error'

        >>> sanitize_error_for_audit("Error\\n  File '/path/to/file.py'")
        'Error'

        >>> sanitize_error_for_audit("Failed for user@example.com")
        'Failed for [EMAIL REDACTED]'

        >>> sanitize_error_for_audit("Database query failed", filter_sensitive_keywords=True)
        'Internal error - contact administrator'
    """
    if error is None:
        return None

    # Convert Exception to string
    error_str = str(error) if isinstance(error, Exception) else str(error)

    if not error_str or not error_str.strip():
        return None

    # Step 1: Remove stack traces (keep first line only)
    if remove_stack_trace:
        error_str = error_str.split("\n")[0]

    # Step 2: Check for API key exposure
    error_lower = error_str.lower()
    for pattern in _API_KEY_PATTERNS:
        if pattern in error_lower:
            return fallback_message or "API authentication error - check configuration"

    # Step 3: Filter sensitive keywords if requested
    if filter_sensitive_keywords:
        if any(keyword in error_lower for keyword in _SENSITIVE_KEYWORDS):
            return fallback_message or "Internal error - contact administrator"

    # Step 4: Redact PII (emails and phone numbers)
    if redact_pii:
        error_str = _EMAIL_PATTERN.sub("[EMAIL REDACTED]", error_str)
        error_str = _PHONE_PATTERN.sub("[PHONE REDACTED]", error_str)

    # Step 5: Truncate to max length
    if len(error_str) > max_length:
        error_str = error_str[:max_length]

    return error_str.strip()


def sanitize_error_for_display(
    detailed_message: str,
    generic_message: str = "An error occurred. Please contact support.",
    admin_roles: tuple = ("System Manager", "Administrator"),
) -> str:
    """
    Return appropriate error message based on user permissions.

    System Managers and Administrators get detailed technical information
    for debugging. Regular users get a generic, user-friendly message to
    avoid exposing internal endpoints, API responses, or system details.

    Args:
        detailed_message: Full technical error message for admins
        generic_message: User-friendly message for regular users
        admin_roles: Tuple of roles that should see detailed messages

    Returns:
        Appropriate message based on user role

    Examples:
        >>> # For System Manager:
        >>> sanitize_error_for_display("Database connection timeout", "Service unavailable")
        'Database connection timeout'

        >>> # For regular user:
        >>> sanitize_error_for_display("Database connection timeout", "Service unavailable")
        'Service unavailable'
    """
    try:
        user_roles = frappe.get_roles()
        if any(role in user_roles for role in admin_roles):
            return detailed_message
        return generic_message
    except Exception:
        # If role check fails, return generic message for safety
        return generic_message


def sanitize_error_for_api_response(
    error: Union[str, Exception],
    include_details_for_admins: bool = True,
    generic_message: str = "An error occurred processing your request.",
) -> Dict[str, str]:
    """
    Prepare error information for API response with appropriate detail level.

    Args:
        error: Raw error message or Exception object
        include_details_for_admins: Include technical details for admin users
        generic_message: Message for non-admin users

    Returns:
        Dict with 'message' and optionally 'details' keys

    Examples:
        >>> sanitize_error_for_api_response(ValueError("Invalid IBAN"))
        {'message': 'Invalid IBAN'}  # For admin
        {'message': 'An error occurred processing your request.'}  # For user
    """
    error_str = str(error) if isinstance(error, Exception) else str(error)

    # Always sanitize for PII
    sanitized = sanitize_error_for_audit(
        error_str,
        max_length=1000,
        remove_stack_trace=True,
        redact_pii=True,
        filter_sensitive_keywords=False,
    )

    if include_details_for_admins:
        try:
            user_roles = frappe.get_roles()
            if "System Manager" in user_roles or "Administrator" in user_roles:
                return {
                    "message": sanitized or generic_message,
                    "error_type": type(error).__name__ if isinstance(error, Exception) else "Error",
                }
        except Exception:
            pass

    return {"message": generic_message}
