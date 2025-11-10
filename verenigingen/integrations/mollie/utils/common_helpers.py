"""
Common Mollie Helper Utilities

Consolidated utilities extracted from payment_gateways.py to eliminate duplication.
Provides standardized patterns for error responses, frequency mapping, and other
common operations used across Mollie integration code.
"""

from typing import Any, Dict, Optional

import frappe
from frappe import _


def create_error_response(message: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Create standardized error response format.

    Extracted from 30+ duplicated error response patterns in payment_gateways.py.
    Provides consistent error response structure across all Mollie operations.

    Args:
        message: Human-readable error message (will be translated)
        details: Optional additional error details (reason, code, etc.)
                Note: Reserved keys "status" and "message" will be filtered out

    Returns:
        Dictionary with status="error" and message

    Example:
        >>> create_error_response("Payment failed", {"reason": "insufficient_funds"})
        {"status": "error", "message": "Payment failed", "reason": "insufficient_funds"}
        >>> create_error_response("Failed", {"status": "success"})  # Filtered
        {"status": "error", "message": "Failed"}
    """
    RESERVED_KEYS = {"status", "message"}

    response = {"status": "error", "message": _(message) if isinstance(message, str) else str(message)}

    if details:
        # Filter out reserved keys to prevent accidental/malicious override
        safe_details = {k: v for k, v in details.items() if k not in RESERVED_KEYS}
        if len(safe_details) < len(details):
            # Log warning if reserved keys were filtered
            filtered_keys = RESERVED_KEYS & details.keys()
            frappe.logger().warning(f"Filtered reserved keys from error response details: {filtered_keys}")
        response.update(safe_details)

    return response


def create_success_response(message: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Create standardized success response format.

    Provides consistent success response structure across all Mollie operations.

    Args:
        message: Human-readable success message (will be translated)
        data: Optional additional data to include in response
              Note: Reserved keys "status" and "message" will be filtered out

    Returns:
        Dictionary with status="success" and message

    Example:
        >>> create_success_response("Payment created", {"payment_id": "tr_123"})
        {"status": "success", "message": "Payment created", "payment_id": "tr_123"}
        >>> create_success_response("Done", {"status": "error"})  # Filtered
        {"status": "success", "message": "Done"}
    """
    RESERVED_KEYS = {"status", "message"}

    response = {"status": "success", "message": _(message) if isinstance(message, str) else str(message)}

    if data:
        # Filter out reserved keys to prevent accidental/malicious override
        safe_data = {k: v for k, v in data.items() if k not in RESERVED_KEYS}
        if len(safe_data) < len(data):
            # Log warning if reserved keys were filtered
            filtered_keys = RESERVED_KEYS & data.keys()
            frappe.logger().warning(f"Filtered reserved keys from success response data: {filtered_keys}")
        response.update(safe_data)

    return response


def convert_frequency_to_mollie_interval(frequency: str) -> str:
    """
    Convert billing frequency to Mollie subscription interval format.

    Extracted from duplicated frequency_map dictionaries in payment_gateways.py
    (lines 899-904 and 1244-1253). Consolidates frequency conversion logic.

    Args:
        frequency: Billing frequency from Dues Schedule or Donation Agreement
                  Can be: "Monthly", "Quarterly", "Semi-Annual", "Annual"
                  Or direct intervals: "1 month", "3 months", "6 months", "12 months"
                  Case-insensitive matching supported

    Returns:
        Mollie interval format string (e.g., "1 month", "3 months")
        Defaults to "1 month" for unknown frequencies

    Example:
        >>> convert_frequency_to_mollie_interval("Quarterly")
        "3 months"
        >>> convert_frequency_to_mollie_interval("quarterly")  # Case-insensitive
        "3 months"
        >>> convert_frequency_to_mollie_interval("Annual")
        "12 months"
    """
    # Normalize input for case-insensitive matching
    normalized_frequency = frequency.strip().title() if frequency else ""

    frequency_map = {
        # Human-readable formats
        "Monthly": "1 month",
        "Quarterly": "3 months",
        "Semi-Annual": "6 months",
        "Annual": "12 months",
        # Direct interval pass-through
        "1 Month": "1 month",
        "3 Months": "3 months",
        "6 Months": "6 months",
        "12 Months": "12 months",
    }

    result = frequency_map.get(normalized_frequency, "1 month")

    # Log warning for unknown frequencies
    if normalized_frequency not in frequency_map:
        frappe.logger().warning(
            f"Unknown billing frequency '{frequency}' (normalized: '{normalized_frequency}') - defaulting to monthly (1 month)"
        )

    return result


def is_long_interval(interval: str) -> bool:
    """
    Check if a Mollie interval is quarterly or longer.

    Used to determine whether smart start date calculation is needed
    (quarterly/yearly subscriptions use configured payment months).

    Args:
        interval: Mollie interval format (e.g., "1 month", "3 months")

    Returns:
        True if interval is 3+ months, False otherwise

    Example:
        >>> is_long_interval("1 month")
        False
        >>> is_long_interval("3 months")
        True
    """
    long_intervals = ["3 months", "6 months", "12 months"]
    return interval in long_intervals


def log_mollie_error(operation: str, error: Exception, context: Optional[Dict[str, Any]] = None):
    """
    Standardized error logging for Mollie operations.

    Extracted from duplicated error logging patterns throughout payment_gateways.py.
    Provides consistent error tracking and debugging information.

    Args:
        operation: Name of the operation that failed (e.g., "Payment Creation")
        error: Exception that occurred
        context: Optional additional context (member_id, payment_id, etc.)

    Example:
        >>> log_mollie_error(
        ...     "Subscription Creation",
        ...     ValueError("Invalid amount"),
        ...     {"member_id": "MEM-001", "amount": -50}
        ... )
    """
    error_message = f"Mollie {operation} failed: {str(error)}"

    if context:
        context_str = ", ".join(f"{k}={v}" for k, v in context.items())
        error_message += f" (Context: {context_str})"

    frappe.logger().error(error_message)
    frappe.log_error(error_message, f"Mollie {operation} Error")


def validate_mollie_amount(amount: Any, min_amount: float = 0.01) -> float:
    """
    Validate and normalize amount for Mollie API.

    Mollie requires amounts to be positive floats with minimum transaction amounts
    (typically €0.01 for EUR). This utility ensures consistent validation across
    all payment and subscription operations.

    Args:
        amount: Amount value (can be string, int, or float)
        min_amount: Minimum allowed amount (default: 0.01 EUR)

    Returns:
        Validated float amount

    Raises:
        ValueError: If amount is invalid, non-positive, or below minimum

    Example:
        >>> validate_mollie_amount("25.50")
        25.5
        >>> validate_mollie_amount(0.005)
        ValueError: Amount must be at least 0.01, got: 0.005
        >>> validate_mollie_amount(-10)
        ValueError: Amount must be positive, got: -10.0
    """
    try:
        amount_float = float(amount)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Invalid amount format: {amount}") from e

    if amount_float <= 0:
        raise ValueError(f"Amount must be positive, got: {amount_float}")

    if amount_float < min_amount:
        raise ValueError(f"Amount must be at least {min_amount}, got: {amount_float}")

    return amount_float


def format_mollie_amount(amount: Any, currency: str = "EUR") -> Dict[str, str]:
    """
    Format amount for Mollie API with consistent 2-decimal precision.

    Extracted from repeated `.2f` formatting patterns throughout payment_gateways.py
    (lines 165, 194, 542, 1194, 1974). Provides consistent amount structure.

    Args:
        amount: Amount value (will be validated)
        currency: Currency code (default: "EUR")

    Returns:
        Dictionary with "value" (formatted string) and "currency"

    Raises:
        ValueError: If amount is invalid

    Example:
        >>> format_mollie_amount(25.5)
        {"value": "25.50", "currency": "EUR"}
        >>> format_mollie_amount("42")
        {"value": "42.00", "currency": "EUR"}
    """
    validated_amount = validate_mollie_amount(amount)

    return {"value": f"{validated_amount:.2f}", "currency": currency}


def format_mollie_amount_string(amount: Any) -> str:
    """
    Format amount as string for Mollie metadata (2-decimal precision).

    Used for metadata fields where only the string value is needed,
    not the full amount dictionary.

    Args:
        amount: Amount value (will be validated)

    Returns:
        Formatted amount string with 2 decimal places

    Example:
        >>> format_mollie_amount_string(25.5)
        "25.50"
    """
    validated_amount = validate_mollie_amount(amount)
    return f"{validated_amount:.2f}"


def get_mollie_currency() -> str:
    """
    Get currency for Mollie payments from settings.

    Currently hardcoded to EUR for Dutch association management.
    Extracted to centralize currency configuration.

    Returns:
        Currency code (currently always "EUR")
    """
    return "EUR"


def format_mollie_response_amount(amount_obj: Any) -> str:
    """
    Format Mollie API response amount object to human-readable string.

    Mollie API returns amounts as {"currency": "EUR", "value": "25.00"}.
    This utility formats them for display in logs and debug output.

    Args:
        amount_obj: Mollie amount object (dict) or other value

    Returns:
        Formatted amount string (e.g., "EUR 25.00") or "Unknown" if invalid

    Example:
        >>> format_mollie_response_amount({"currency": "EUR", "value": "25.50"})
        "EUR 25.50"
        >>> format_mollie_response_amount(None)
        "Unknown"
    """
    try:
        if not amount_obj:
            return "Unknown"
        if isinstance(amount_obj, dict):
            currency = amount_obj.get("currency", "EUR")
            value = amount_obj.get("value", "0")
            return f"{currency} {value}"
        return str(amount_obj)
    except Exception:
        return "Error parsing amount"


def get_member_by_subscription_id(
    subscription_id: str, fields: Optional[list] = None
) -> Optional[Dict[str, Any]]:
    """
    Find member by Mollie subscription ID.

    Extracted from duplicated member lookup patterns in payment_gateways.py
    (lines 1938-1943 and 1962-1967). Consolidates subscription-based member queries.

    Args:
        subscription_id: Mollie subscription ID (format: sub_xxx)
        fields: Optional list of fields to retrieve (default: ["name"])

    Returns:
        Member document as dict if found, None otherwise

    Example:
        >>> member = get_member_by_subscription_id("sub_xyz123", ["name", "mollie_customer_id"])
        >>> if member:
        ...     print(f"Found member: {member['name']}")
    """
    if not subscription_id:
        return None

    if fields is None:
        fields = ["name"]

    members = frappe.get_all(
        "Member", filters={"mollie_subscription_id": subscription_id}, fields=fields, limit=1
    )

    return members[0] if members else None


def get_member_by_customer_id(customer_id: str, fields: Optional[list] = None) -> Optional[Dict[str, Any]]:
    """
    Find member by Mollie customer ID.

    Extracted from duplicated member lookup patterns in payment_gateways.py
    (line 1488). Consolidates customer-based member queries.

    Args:
        customer_id: Mollie customer ID (format: cst_xxx)
        fields: Optional list of fields to retrieve (default: ["name"])

    Returns:
        Member document as dict if found, None otherwise

    Example:
        >>> member = get_member_by_customer_id("cst_abc123")
        >>> if member:
        ...     print(f"Found member: {member['name']}")
    """
    if not customer_id:
        return None

    # First try to find by mollie_customer_id field
    if fields is None:
        fields = ["name"]

    # Member has mollie_customer_id field
    members = frappe.get_all("Member", filters={"mollie_customer_id": customer_id}, fields=fields, limit=1)

    if members:
        return members[0]

    # Fallback: Check if customer_id matches a Customer doctype, then find linked Member
    # This handles the pattern at line 988 where filters={"customer": customer_name}
    from verenigingen.utils.member_utils import get_member_for_customer

    member_name = get_member_for_customer(customer_id)
    if member_name:
        if "name" not in fields:
            fields = ["name"] + fields
        member_doc = frappe.get_value("Member", member_name, fields, as_dict=True)
        return member_doc

    return None


def get_members_by_customer(customer_name: str, fields: Optional[list] = None) -> list:
    """
    Find all members linked to a Customer doctype.

    Extracted from duplicated pattern at line 986-990 in payment_gateways.py.
    Note: Returns list (not single member) as multiple members could theoretically
    link to same customer (though this should be rare).

    Args:
        customer_name: Customer doctype name
        fields: Optional list of fields to retrieve

    Returns:
        List of member documents (empty list if none found)

    Example:
        >>> members = get_members_by_customer("CUST-001", ["name", "mollie_subscription_id"])
        >>> for member in members:
        ...     print(f"Member: {member['name']}")
    """
    if not customer_name:
        return []

    if fields is None:
        fields = ["name", "mollie_subscription_id", "subscription_status"]

    members = frappe.get_all("Member", filters={"customer": customer_name}, fields=fields)

    return members
