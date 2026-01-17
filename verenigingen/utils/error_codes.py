# Error Codes Registry for Verenigingen
#
# Centralized error code definitions for monitoring and alerting.
# Error codes follow the pattern: CATEGORY_NNN
#
# Categories:
# - HIST: History management operations
# - CLEANUP: Cleanup and integrity operations
# - DONOR: Donor-related operations
# - VOL: Volunteer-related operations
# - ASSIGN: Assignment-related operations

from typing import Dict

# History Management Error Codes
HISTORY_ERROR_CODES: Dict[str, str] = {
    "HIST_001": "Donation history sync failed",
    "HIST_002": "Payment reference prefetch failed",
    "HIST_003": "Dues payment history update failed",
    "HIST_004": "Invoice payment history update failed",
    "HIST_005": "Volunteer expense history update failed",
    "HIST_006": "Fee change history refresh failed",
    "HIST_007": "Member document save failed after history update",
    "HIST_008": "Volunteer expense cleanup failed",
}

# Cleanup and Integrity Error Codes
CLEANUP_ERROR_CODES: Dict[str, str] = {
    "CLEANUP_001": "Permission denied for cleanup operation",
    "CLEANUP_002": "Broken link cleanup failed",
    "CLEANUP_003": "Duplicate detection conflict - manual review required",
    "CLEANUP_004": "Child table update failed after cleanup",
    "CLEANUP_005": "Audit log creation failed",
}

# Donor Management Error Codes
DONOR_ERROR_CODES: Dict[str, str] = {
    "DONOR_001": "Multiple donors found for email - ambiguous mapping",
    "DONOR_002": "Donor record not found",
    "DONOR_003": "Invalid donor link on member",
}

# Volunteer Error Codes
VOLUNTEER_ERROR_CODES: Dict[str, str] = {
    "VOL_001": "Volunteer assignment query failed",
    "VOL_002": "Volunteer history query failed",
    "VOL_003": "Volunteer-employee mapping ambiguous",
}

# Assignment Error Codes
ASSIGNMENT_ERROR_CODES: Dict[str, str] = {
    "ASSIGN_001": "Assignment history add failed",
    "ASSIGN_002": "Assignment history complete failed",
    "ASSIGN_003": "Assignment history remove failed",
    "ASSIGN_004": "Duplicate assignment detected",
}

# Combined registry for lookup
ALL_ERROR_CODES: Dict[str, str] = {
    **HISTORY_ERROR_CODES,
    **CLEANUP_ERROR_CODES,
    **DONOR_ERROR_CODES,
    **VOLUNTEER_ERROR_CODES,
    **ASSIGNMENT_ERROR_CODES,
}


def get_error_description(error_code: str) -> str:
    """
    Get human-readable description for an error code.

    Args:
        error_code: The error code (e.g., "HIST_001")

    Returns:
        Description string, or "Unknown error" if code not found
    """
    return ALL_ERROR_CODES.get(error_code, f"Unknown error code: {error_code}")


def log_operation_error(
    error_code: str,
    context: str,
    exception: Exception = None,
    additional_info: dict = None,
) -> None:
    """
    Log an operation error with full context to Error Log.

    This creates a structured error log entry that can be used for
    monitoring and alerting.

    Args:
        error_code: Structured error code (e.g., "HIST_001")
        context: Context string (e.g., "member MEM-001")
        exception: Optional exception object for traceback
        additional_info: Optional dict with extra context
    """
    import frappe

    description = get_error_description(error_code)
    title = f"{error_code}: {description}"

    message_parts = [
        f"Error Code: {error_code}",
        f"Description: {description}",
        f"Context: {context}",
    ]

    if additional_info:
        message_parts.append(f"Additional Info: {additional_info}")

    if exception:
        message_parts.append(f"\nException: {str(exception)}")
        message_parts.append(f"\nTraceback:\n{frappe.get_traceback()}")

    message = "\n".join(message_parts)

    frappe.log_error(title=title, message=message)

    # Also log to standard logger for immediate visibility
    frappe.logger("verenigingen.errors").error(
        f"[{error_code}] {context}: {str(exception) if exception else description}"
    )
