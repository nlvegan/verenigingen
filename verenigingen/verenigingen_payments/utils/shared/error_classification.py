"""
Shared error classification utility for unified error handling.

Provides a generic `classify_error` function that categorizes exceptions
into standardized failure categories. This replaces duplicated error
categorization logic across sepa_error_handler and sepa_retry_manager.

Note: The BUSINESS category (handled via isinstance(SEPAError)) is
typically determined by callers, not this generic helper.
"""

from enum import Enum

import frappe


class FailureCategory(str, Enum):
    """Standardized failure categories for error handling"""

    TRANSIENT = "transient"
    RESOURCE = "resource"
    VALIDATION = "validation"
    AUTHORIZATION = "authorization"
    BUSINESS = "business"
    DATA = "data"
    SYSTEM = "system"


def classify_error(error: Exception) -> FailureCategory:
    """
    Classify an exception into a standardized failure category.

    Categories are checked in order (TRANSIENT, RESOURCE, VALIDATION,
    AUTHORIZATION, DATA → else SYSTEM). The first matching category is returned.

    Args:
        error: Exception to classify

    Returns:
        FailureCategory enum value

    Examples:
        >>> classify_error(Exception("connection reset"))
        <FailureCategory.TRANSIENT: 'transient'>
        >>> classify_error(ValueError("invalid input"))
        <FailureCategory.VALIDATION: 'validation'>
        >>> classify_error(frappe.PermissionError("denied"))
        <FailureCategory.AUTHORIZATION: 'authorization'>
    """
    error_message = str(error).lower()

    # Build keyword map as union of sepa_error_handler and sepa_retry_manager
    keywords_by_category = {
        FailureCategory.TRANSIENT: [
            "connection",
            "timeout",
            "temporary",
            "server",
            "network",
            "busy",
            "unavailable",
            "overload",
            "deadlock",
            "lock wait",
        ],
        FailureCategory.RESOURCE: [
            "resource",
            "limit exceeded",
        ],
        FailureCategory.VALIDATION: [
            "validation",
            "invalid",
            "missing",
            "format",
            "required",
            "constraint",
            "duplicate",
        ],
        FailureCategory.AUTHORIZATION: [
            "permission",
            "unauthorized",
            "access",
            "forbidden",
            "authentication",
        ],
        FailureCategory.DATA: [
            "not found",
            "does not exist",
            "empty",
            "null",
        ],
    }

    # Check RESOURCE first (more specific keywords)
    for keyword in keywords_by_category[FailureCategory.RESOURCE]:
        if keyword in error_message:
            return FailureCategory.RESOURCE

    # Check TRANSIENT second
    for keyword in keywords_by_category[FailureCategory.TRANSIENT]:
        if keyword in error_message:
            return FailureCategory.TRANSIENT

    # Check VALIDATION third
    for keyword in keywords_by_category[FailureCategory.VALIDATION]:
        if keyword in error_message:
            return FailureCategory.VALIDATION

    # isinstance checks for VALIDATION
    if isinstance(error, (ValueError, TypeError)):
        return FailureCategory.VALIDATION

    # Check AUTHORIZATION fourth
    for keyword in keywords_by_category[FailureCategory.AUTHORIZATION]:
        if keyword in error_message:
            return FailureCategory.AUTHORIZATION

    # isinstance check for AUTHORIZATION
    if isinstance(error, frappe.PermissionError):
        return FailureCategory.AUTHORIZATION

    # Check DATA fifth
    for keyword in keywords_by_category[FailureCategory.DATA]:
        if keyword in error_message:
            return FailureCategory.DATA

    # Default to SYSTEM
    return FailureCategory.SYSTEM
