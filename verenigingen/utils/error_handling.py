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

import re
import time
import traceback
from functools import wraps
from typing import Any, Callable, Dict, Optional, Union

import frappe
from frappe import _

from verenigingen.utils.constants import Roles
from verenigingen.utils.transaction_errors import NON_RESUMABLE_DB_ERRORS


class VerenigingenException(frappe.ValidationError):
    """
    Base exception class for Verenigingen-specific errors.

    Supports structured error information for monitoring, logging, and API responses.

    Attributes:
        error_code: Structured error code for monitoring/alerting (e.g., "MEM_001")
        http_status: HTTP status code for API responses (e.g., 400, 404, 500)
        details: Additional context dictionary for debugging

    Examples:
        >>> raise VerenigingenException(
        ...     "Validation failed",
        ...     error_code="VALIDATION_001",
        ...     http_status=400,
        ...     details={"field": "email"}
        ... )
    """

    def __init__(
        self,
        message: str = None,
        error_code: str = None,
        http_status: int = None,
        details: Dict[str, Any] = None,
    ):
        super().__init__(message or "An error occurred")
        self.error_code = error_code
        self.http_status = http_status
        self.details = details or {}


class MembershipError(VerenigingenException):
    """Raised when membership-related operations fail"""

    def __init__(
        self,
        message: str = None,
        error_code: str = None,
        http_status: int = None,
        details: Dict[str, Any] = None,
    ):
        super().__init__(
            message or "Membership operation failed",
            error_code=error_code or "MEMBERSHIP_ERROR",
            http_status=http_status or 400,
            details=details,
        )


class PaymentError(VerenigingenException):
    """Raised when payment processing fails"""

    def __init__(
        self,
        message: str = None,
        error_code: str = None,
        http_status: int = None,
        details: Dict[str, Any] = None,
    ):
        super().__init__(
            message or "Payment processing failed",
            error_code=error_code or "PAYMENT_ERROR",
            http_status=http_status or 400,
            details=details,
        )


class SEPAError(PaymentError):
    """Raised when SEPA direct debit operations fail"""

    def __init__(
        self,
        message: str = None,
        error_code: str = None,
        http_status: int = None,
        details: Dict[str, Any] = None,
    ):
        super().__init__(
            message or "SEPA operation failed",
            error_code=error_code or "SEPA_ERROR",
            http_status=http_status or 400,
            details=details,
        )


class VolunteerError(VerenigingenException):
    """Raised when volunteer-related operations fail"""

    def __init__(
        self,
        message: str = None,
        error_code: str = None,
        http_status: int = None,
        details: Dict[str, Any] = None,
    ):
        super().__init__(
            message or "Volunteer operation failed",
            error_code=error_code or "VOLUNTEER_ERROR",
            http_status=http_status or 400,
            details=details,
        )


class ChapterError(VerenigingenException):
    """Raised when chapter-related operations fail"""

    def __init__(
        self,
        message: str = None,
        error_code: str = None,
        http_status: int = None,
        details: Dict[str, Any] = None,
    ):
        super().__init__(
            message or "Chapter operation failed",
            error_code=error_code or "CHAPTER_ERROR",
            http_status=http_status or 400,
            details=details,
        )


class PermissionError(VerenigingenException, frappe.PermissionError):
    """Raised when user lacks required permissions.

    Multi-inherits from both:
      * ``VerenigingenException`` — for structured error metadata + the
        existing ``except VerenigingenException`` catch site in
        ``handle_api_error`` (``error_handling.py:480``).
      * ``frappe.PermissionError`` — so ``except frappe.PermissionError``
        (used in Frappe core at ``client.py:488``, ``permissions.py:892``
        and 6+ sites in this codebase) actually catches our exception.
        Previously only inherited from ``frappe.ValidationError`` via
        ``VerenigingenException``, which routed permission denials to
        the wrong branch and wrong HTTP status at the transport layer.

    Both parents have empty ``__init__`` (just bare ``pass``), so there
    is no cooperative-inheritance hazard — ``super().__init__()`` chains
    cleanly through ``VerenigingenException`` to ``Exception``.

    The explicit ``http_status_code = 403`` overrides the 417 inherited
    via ``VerenigingenException → frappe.ValidationError``. Frappe's
    request handler (``apps/frappe/frappe/app.py:346``) reads the class
    attribute via ``getattr(e, "http_status_code", 500)`` to set the
    response code. The previous ``self.http_status = 403`` (instance
    attribute, *different name*) was never read by Frappe — it was only
    consumed inside ``handle_api_error`` below. Both attributes coexist
    and both now resolve to 403; the class attribute is what fixes the
    HTTP response on uncaught raises.

    ``isinstance(e, frappe.ValidationError)`` is still True via the MRO,
    so ``except frappe.ValidationError`` sites that previously caught
    us continue to do so unchanged.
    """

    http_status_code = 403

    def __init__(
        self,
        message: str = None,
        error_code: str = None,
        http_status: int = None,
        details: Dict[str, Any] = None,
    ):
        super().__init__(
            message or "Permission denied",
            error_code=error_code or "PERMISSION_DENIED",
            http_status=http_status or 403,
            details=details,
        )


class ValidationError(VerenigingenException):
    """Raised when data validation fails"""

    def __init__(
        self,
        message: str = None,
        error_code: str = None,
        http_status: int = None,
        details: Dict[str, Any] = None,
    ):
        super().__init__(
            message or "Validation failed",
            error_code=error_code or "VALIDATION_ERROR",
            http_status=http_status or 400,
            details=details,
        )


class ConfigurationError(VerenigingenException):
    """Raised when system configuration is invalid"""

    def __init__(
        self,
        message: str = None,
        error_code: str = None,
        http_status: int = None,
        details: Dict[str, Any] = None,
    ):
        super().__init__(
            message or "Configuration error",
            error_code=error_code or "CONFIG_ERROR",
            http_status=http_status or 500,
            details=details,
        )


def get_logger(module_name: str):
    """
    Get a standardized logger for a module

    Args:
        module_name: Name of the module (e.g., 'verenigingen.api.member_management')

    Returns:
        Configured logger instance
    """
    return frappe.logger(module_name, allow_site=True, file_count=50)


# Regex pattern for sensitive key matching
# Uses word boundaries to avoid false positives (e.g., "secretary" won't match "secret")
# Matches keys like: api_key, apiKey, API-KEY, x-api-key, access_token, etc.
SENSITIVE_KEY_PATTERN = re.compile(
    r"(^|[^a-z0-9])"  # Start of string or non-alphanumeric before
    r"("
    r"authorization|"
    r"api[_-]?key|"
    r"token|"
    r"access[_-]?token|"
    r"refresh[_-]?token|"
    r"bearer|"
    r"password|"
    r"passwd|"
    r"secret[_-]?key|"  # secret_key, secretKey, but not "secretary"
    r"card[_-]?number|"
    r"cvv|"
    r"cvc|"
    r"ssn|"
    r"social[_-]?security|"
    r"private[_-]?key"
    r")"
    r"([^a-z0-9]|$)",  # Non-alphanumeric after or end of string
    re.IGNORECASE,
)

# Exact match keys that should always be redacted (common standalone names)
SENSITIVE_EXACT_KEYS = frozenset(
    {
        "token",
        "secret",
        "password",
        "passwd",
        "apikey",
        "api_key",
        "authorization",
        "bearer",
        "cvv",
        "cvc",
        "ssn",
    }
)


def scrub_metadata(value: Any) -> Any:
    """
    Scrub sensitive keys from metadata before logging or returning in API responses.

    This function prevents accidental leakage of secrets, tokens, and other
    sensitive data that may be passed in metadata dictionaries. It recursively
    processes nested dicts and lists.

    Key matching uses word-boundary-aware regex to avoid false positives
    (e.g., "secretary" won't be redacted because it contains "secret").

    Args:
        value: Value to scrub (dict, list, or primitive)

    Returns:
        New structure with sensitive values redacted

    Examples:
        >>> scrub_metadata({"user": "john", "token": "secret123"})
        {'user': 'john', 'token': '***REDACTED***'}

        >>> scrub_metadata({"Authorization": "Bearer xyz"})
        {'Authorization': '***REDACTED***'}

        >>> scrub_metadata({"secretary": "Jane"})  # Not redacted - false positive avoided
        {'secretary': 'Jane'}

        >>> scrub_metadata([{"api_key": "xyz"}, {"name": "test"}])
        [{'api_key': '***REDACTED***'}, {'name': 'test'}]
    """
    if value is None:
        return {}

    if isinstance(value, dict):
        result = {}
        for key, val in value.items():
            key_lower = key.lower()
            # Check exact match first (faster), then regex pattern
            if key_lower in SENSITIVE_EXACT_KEYS or SENSITIVE_KEY_PATTERN.search(key):
                result[key] = "***REDACTED***"
            else:
                result[key] = scrub_metadata(val)
        return result

    if isinstance(value, (list, tuple)):
        return [scrub_metadata(item) for item in value]

    # Primitives (str, int, float, bool, None) pass through unchanged
    return value


def log_error(error: Exception, context: Dict[str, Any] = None, module: str = None) -> str:
    """
    Log an error with standardized formatting, context, and trace ID.

    Args:
        error: The exception that occurred
        context: Additional context information
        module: Module name where error occurred

    Returns:
        trace_id: Unique identifier for correlating logs and API responses
    """
    import uuid

    logger = get_logger(module or "verenigingen.error")

    # Generate or extract trace_id for correlation
    trace_id = (context or {}).get("trace_id") or uuid.uuid4().hex[:16]

    # Scrub sensitive data from context before logging
    safe_context = scrub_metadata(context or {})

    error_context = {
        "trace_id": trace_id,
        "user": frappe.session.user if frappe.session else "System",
        "site": frappe.local.site if frappe.local else "Unknown",
        "error_type": type(error).__name__,
        "error_message": str(error),
    }

    # Add context without overwriting logging's reserved fields
    for key, value in safe_context.items():
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
            "trace_id",  # Already added above
        ]:
            error_context[f"ctx_{key}"] = value

    # Log the error with safe context
    logger.error(
        f"[trace_id={trace_id}] Error in {module}: {str(error)}",
        extra=error_context,
        exc_info=True,
    )

    # Also create a Frappe Error Log entry for tracking
    frappe.log_error(
        title=f"{module}: {type(error).__name__} [trace_id={trace_id}]",
        message=f"Error: {str(error)}\nTrace ID: {trace_id}\nContext: {error_context}",
    )

    return trace_id


def handle_api_error(func: Callable) -> Callable:
    """
    Decorator to provide standardized error handling for API endpoints.

    Returns OperationResult for consistent API responses across the application.

    Usage:
        @frappe.whitelist()
        @handle_api_error
        def my_api_function():
            # Function implementation

    Note:
        This decorator returns OperationResult objects, which can be converted
        to dict via .to_dict() by the standard_api decorator or similar wrappers.

        The ONE exception is a non-resumable DB error (MariaDB 1205/1213): those roll
        back and propagate instead of becoming a return value, because a caller cannot
        retry what it cannot distinguish and the alternative is Frappe committing
        half-applied work at request end (#481). Callers that treat every failure as a
        returned OperationResult must handle the raise.
    """
    from verenigingen.utils.operation_result import OperationResult

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except NON_RESUMABLE_DB_ERRORS as e:
            # #481, the sixth boundary of the #470/#475 class. A 1205/1213 must not become a
            # return value here: with nothing propagating, the request ends on its SUCCESS
            # path and Frappe commits whatever the endpoint already wrote -- six of the 50
            # endpoints wearing this decorator write in-frame, one of them the public
            # membership form. Hence the rollback, which is for the half-applied work and NOT
            # for the log_error below it: tabError Log is MyISAM and therefore
            # non-transactional, so that row lands either way (measured on test_site_1).
            #
            # Then re-raise, so the caller can tell a retryable deadlock from an ordinary
            # failure. Every frame above this one was checked before relying on that: the
            # api_security_framework wrapper backing critical_api/high_security_api/
            # standard_api/public_api logs its audit event and re-raises
            # (api_security_framework.py:1044), and no other decorator in the stack catches
            # the wrapped call -- so this really does reach the client.
            frappe.db.rollback()
            log_error(
                e,
                context={
                    "function": func.__name__,
                    "args": str(args)[:200],
                    "kwargs": str(kwargs)[:200],
                    "traceback": traceback.format_exc(),
                },
                module=func.__module__,
            )
            raise
        except VerenigingenException as e:
            # Known application errors - return structured OperationResult
            # Capture trace_id for correlation between logs and API responses
            trace_id = log_error(e, context={"function": func.__name__}, module=func.__module__)
            return OperationResult.fail(
                message=str(e),
                error_code=getattr(e, "error_code", "VALIDATION_ERROR"),
                http_status=getattr(e, "http_status", 400),
                errors=[type(e).__name__],
                details=getattr(e, "details", {}),
                trace_id=trace_id,
            )
        except frappe.PermissionError as e:
            # Permission errors
            trace_id = log_error(e, context={"function": func.__name__}, module=func.__module__)
            return OperationResult.fail(
                message=_("Access denied: {0}").format(str(e)),
                error_code="PERMISSION_DENIED",
                http_status=403,
                errors=["PermissionError"],
                trace_id=trace_id,
            )
        except frappe.ValidationError as e:
            # Frappe validation errors
            trace_id = log_error(e, context={"function": func.__name__}, module=func.__module__)
            return OperationResult.fail(
                message=str(e),
                error_code="VALIDATION_ERROR",
                http_status=400,
                errors=["ValidationError"],
                trace_id=trace_id,
            )
        except Exception as e:
            # Unexpected errors - log with full traceback
            trace_id = log_error(
                e,
                context={
                    "function": func.__name__,
                    "args": str(args)[:200],  # Limit arg length
                    "kwargs": str(kwargs)[:200],
                    "traceback": traceback.format_exc(),
                },
                module=func.__module__,
            )

            return OperationResult.from_exception(
                e,
                message=_("An unexpected error occurred. Please contact support."),
                error_code="SYSTEM_ERROR",
                http_status=500,
                trace_id=trace_id,
            )

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
    "error_notification_roles": [Roles.SYSTEM_MANAGER, "Verenigingen System Admin"],
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

        # Expose the backing store so callers/tests can invalidate it, mirroring
        # functools.lru_cache().cache_clear(). The cache is an in-process dict
        # (NOT frappe.cache()/Redis), so frappe.cache().delete_value(...) does
        # NOT clear it — use this instead.
        wrapper.cache_clear = cache.clear
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
    if Roles.SYSTEM_MANAGER not in frappe.get_roles():
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

# PII patterns for sanitization
_EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE_PATTERN = re.compile(r"\+?\d{10,15}|\d{2,4}[\s-]?\d{3,4}[\s-]?\d{3,4}")
# IBAN pattern: 2 letter country code + 2 check digits + 10-30 alphanumeric (BBAN)
# Uses explicit character class without spaces to avoid over-matching
# Matches: NL91ABNA0417164300, DE89370400440532013000, etc.
_IBAN_PATTERN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b", re.IGNORECASE)

# Sensitive keyword patterns that indicate internal system information
_SENSITIVE_KEYWORDS = frozenset(
    [
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
    ]
)

# API key patterns (Mollie, Stripe, etc.)
_API_KEY_PATTERNS = ["test_", "live_", "sk_", "pk_", "bearer "]


def mask_iban(iban: str, style: str = "standard") -> str:
    """
    Centralized IBAN masking for audit logs, notifications, and error messages.

    This is the canonical IBAN masking function for the application. All IBAN
    masking should use this function to ensure consistency.

    Args:
        iban: The IBAN to mask
        style: Masking style - "standard" (country code + last 4) or
               "brief" (first 4 + last 4, for user notifications)

    Returns:
        Masked IBAN string

    Examples:
        >>> mask_iban("NL91ABNA0417164300")
        'NL**************4300'

        >>> mask_iban("NL91ABNA0417164300", style="brief")
        'NL91****4300'

        >>> mask_iban("DE89 3704 0044 0532 0130 00")
        'DE******************3000'
    """
    if not iban:
        return iban

    # Remove spaces for processing
    cleaned = iban.replace(" ", "").upper()

    if style == "brief":
        # Show first 4 + last 4 (user-friendly for notifications)
        if len(cleaned) < 8:
            return iban  # Too short to mask meaningfully
        return f"{cleaned[:4]}****{cleaned[-4:]}"
    else:
        # Standard: Show country code (2 chars) + masked middle + last 4 digits
        # This provides maximum security while maintaining country identification
        if len(cleaned) >= 6:
            return f"{cleaned[:2]}{'*' * (len(cleaned) - 6)}{cleaned[-4:]}"
        else:
            # Very short - mask entirely
            return "*" * len(cleaned)


def _redact_iban_match(match: re.Match) -> str:
    """Replacement function for IBAN pattern matches."""
    return mask_iban(match.group(0))


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
        redact_pii: Redact email addresses, phone numbers, and IBANs
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

        >>> sanitize_error_for_audit("IBAN NL91ABNA0417164300 invalid")
        'IBAN NL**************4300 invalid'

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

    # Step 4: Redact PII (emails, IBANs, and phone numbers)
    # IMPORTANT: Process IBANs BEFORE phone numbers because phone pattern
    # would otherwise match numeric portions of IBANs and corrupt them
    if redact_pii:
        error_str = _EMAIL_PATTERN.sub("[EMAIL REDACTED]", error_str)
        error_str = _IBAN_PATTERN.sub(_redact_iban_match, error_str)
        error_str = _PHONE_PATTERN.sub("[PHONE REDACTED]", error_str)

    # Step 5: Truncate to max length
    if len(error_str) > max_length:
        error_str = error_str[:max_length]

    return error_str.strip()


def sanitize_error_for_display(
    detailed_message: str,
    generic_message: str = "An error occurred. Please contact support.",
    admin_roles: tuple = (Roles.SYSTEM_MANAGER, "Administrator"),
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
            if Roles.SYSTEM_MANAGER in user_roles or "Administrator" in user_roles:
                return {
                    "message": sanitized or generic_message,
                    "error_type": type(error).__name__ if isinstance(error, Exception) else "Error",
                }
        except Exception:
            pass

    return {"message": generic_message}


def sanitize_audit_details(details: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitize audit details dictionary to remove/mask sensitive information.

    This ensures PII and sensitive data are not stored in audit logs.
    Use this function before writing audit entries to ensure compliance
    with data protection requirements.

    Args:
        details: Dictionary of audit details

    Returns:
        Sanitized dictionary safe for audit storage

    Examples:
        >>> sanitize_audit_details({"iban": "NL91ABNA0417164300", "amount": 100})
        {'iban': 'NL**************4300', 'amount': '100'}

        >>> sanitize_audit_details({"password": "secret123"})
        {'password': '[REDACTED]'}
    """
    if not details:
        return {}

    sanitized = {}
    for key, value in details.items():
        if value is None:
            sanitized[key] = None
            continue

        str_value = str(value)

        # Special handling for known sensitive fields
        if key in ("iban", "bank_account", "account_number"):
            sanitized[key] = mask_iban(str_value) if str_value else None
        elif key in ("error", "traceback", "message"):
            # Sanitize error messages
            sanitized[key] = sanitize_error_for_audit(
                str_value,
                max_length=500,
                remove_stack_trace=True,
                redact_pii=True,
            )
        elif key in ("password", "secret", "token", "api_key"):
            # Never store these
            sanitized[key] = "[REDACTED]"
        else:
            # General sanitization for other fields
            sanitized[key] = sanitize_error_for_audit(
                str_value,
                max_length=1000,
                remove_stack_trace=False,
                redact_pii=True,
            )

    return sanitized
