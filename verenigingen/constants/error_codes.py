# Copyright (c) 2025, Verenigingen
# For license information, please see license.txt

"""
Centralized Error Codes for Verenigingen Services

This module defines all error codes used across the application for consistent
error handling and observability. Each error code should be unique and documented.

Error Code Format: {MODULE}_{CATEGORY}_{NUMBER}
- MODULE: Short identifier for the service/module (e.g., CHAP, LIFECYCLE, MEMBER_ID)
- CATEGORY: Type of error (e.g., API, VAL for validation, OP for operation)
- NUMBER: Sequential number within the category (001, 002, etc.)

IMPORTANT: Do not reuse error codes. When adding new codes, use the next
available number in the appropriate category.

Usage:
    from verenigingen.constants.error_codes import ErrorCodes

    return OperationResult.fail(
        "Error message",
        error_code=ErrorCodes.LIFECYCLE_APPROVAL_FAILED,
    )
"""


class ErrorCodes:
    """Centralized error codes for observability and debugging."""

    # =========================================================================
    # Chapter API Errors (CHAP_API_xxx)
    # =========================================================================
    CHAP_API_PERMISSION_DENIED = "CHAP_API_001"
    CHAP_API_FETCH_CHAPTERS_FAILED = "CHAP_API_002"
    CHAP_API_FETCH_NAMES_FAILED = "CHAP_API_003"
    CHAP_API_DISPLAY_HTML_FAILED = "CHAP_API_004"

    # =========================================================================
    # Member Lifecycle Errors (LIFECYCLE_xxx)
    # =========================================================================
    LIFECYCLE_APPROVAL_FAILED = "LIFECYCLE_001"
    LIFECYCLE_REJECTION_FAILED = "LIFECYCLE_002"
    LIFECYCLE_MEMBER_NOT_FOUND = "LIFECYCLE_003"
    LIFECYCLE_ALREADY_APPROVED = "LIFECYCLE_004"
    LIFECYCLE_ALREADY_PROCESSED = "LIFECYCLE_005"

    # =========================================================================
    # Member ID Service Errors (MEMBER_ID_xxx)
    # =========================================================================
    MEMBER_ID_LOCK_FAILED = "MEMBER_ID_001"
    MEMBER_ID_GENERATION_FAILED = "MEMBER_ID_002"
    MEMBER_ID_ALREADY_EXISTS = "MEMBER_ID_003"
    MEMBER_ID_NOT_ELIGIBLE = "MEMBER_ID_004"

    # =========================================================================
    # Validation Errors (VALIDATION_xxx)
    # =========================================================================
    VALIDATION_FAILED = "VALIDATION_001"
    VALIDATION_DURATION_CALC_FAILED = "VALIDATION_DUR"

    # =========================================================================
    # Before Save Errors (BEFORE_SAVE_xxx)
    # =========================================================================
    BEFORE_SAVE_FAILED = "BEFORE_SAVE_001"
    BEFORE_SAVE_OPTIMIZATION_FAILED = "BEFORE_SAVE_OPT"
    BEFORE_SAVE_CHAPTER_DISPLAY_FAILED = "BEFORE_SAVE_CHAP"
    BEFORE_SAVE_ADDRESS_FAILED = "BEFORE_SAVE_ADDR"
    BEFORE_SAVE_STATUS_DEFAULTS_FAILED = "BEFORE_SAVE_STAT"


# Mapping of error codes to user-friendly messages (for API responses)
ERROR_MESSAGES = {
    ErrorCodes.CHAP_API_PERMISSION_DENIED: "Permission denied",
    ErrorCodes.CHAP_API_FETCH_CHAPTERS_FAILED: "An error occurred fetching chapters",
    ErrorCodes.CHAP_API_FETCH_NAMES_FAILED: "An error occurred fetching chapter names",
    ErrorCodes.CHAP_API_DISPLAY_HTML_FAILED: "An error occurred generating chapter display",
    ErrorCodes.LIFECYCLE_APPROVAL_FAILED: "Application approval failed",
    ErrorCodes.LIFECYCLE_REJECTION_FAILED: "Application rejection failed",
    ErrorCodes.LIFECYCLE_MEMBER_NOT_FOUND: "Member not found",
    ErrorCodes.LIFECYCLE_ALREADY_APPROVED: "Application is already approved",
    ErrorCodes.LIFECYCLE_ALREADY_PROCESSED: "Application has already been processed",
    ErrorCodes.MEMBER_ID_LOCK_FAILED: "Another bulk operation is in progress. Please try again later.",
    ErrorCodes.MEMBER_ID_GENERATION_FAILED: "Failed to generate member ID",
    ErrorCodes.MEMBER_ID_ALREADY_EXISTS: "Member already has an ID",
    ErrorCodes.MEMBER_ID_NOT_ELIGIBLE: "Member is not eligible for a member ID",
}


def get_safe_error_message(error_code: str, default: str = "An error occurred") -> str:
    """Get a user-safe error message for an error code.

    Args:
        error_code: The error code to look up
        default: Default message if code not found

    Returns:
        User-safe error message (never exposes internal details)
    """
    return ERROR_MESSAGES.get(error_code, default)
