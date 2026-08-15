"""
Common Mollie Helper Utilities

Consolidated utilities extracted from payment_gateways.py to eliminate duplication.
Provides standardized patterns for error responses, frequency mapping, and other
common operations used across Mollie integration code.
"""

import re
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple, Union

import frappe
from frappe import _


def mollie_signature_date() -> str:
    """Return today's date (UTC) as a Y-m-d string for a Mollie SEPA mandate.

    Mollie rejects a mandate ``signatureDate`` in the FUTURE relative to its own
    clock, so site-local ``frappe.utils.today()`` breaks on a site configured east
    of Mollie's timezone (it returns tomorrow near local midnight → HTTP 422). The
    UTC date is never ahead of Mollie's clock, and SEPA accepts a past signature
    date without restriction, so this is safe on every site.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# Decimal precision for monetary amounts (2 decimal places)
DECIMAL_PLACES = Decimal("0.01")
MIN_MOLLIE_AMOUNT = Decimal("0.01")

# Pre-compiled regex patterns for Mollie ID validation
MOLLIE_ID_PATTERNS = {
    "payment": re.compile(r"^tr_[a-zA-Z0-9]{10,}$"),
    "refund": re.compile(r"^re_[a-zA-Z0-9]{10,}$"),
    "chargeback": re.compile(r"^chb_[a-zA-Z0-9]{10,}$"),
    "customer": re.compile(r"^cst_[a-zA-Z0-9]{10,}$"),
    "subscription": re.compile(r"^sub_[a-zA-Z0-9]{10,}$"),
    "mandate": re.compile(r"^mdt_[a-zA-Z0-9]{10,}$"),
}


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
        # Donation.recurring_frequency Select vocabulary (Daily/Weekly/Bi-weekly/
        # Monthly/Quarterly/Yearly). Mollie supports day/week/month intervals;
        # without these, Yearly/Weekly/etc. silently defaulted to monthly and a
        # yearly donor would be billed every month.
        "Daily": "1 day",
        "Weekly": "1 week",
        "Bi-Weekly": "2 weeks",  # "bi-weekly".title() == "Bi-Weekly"
        "Yearly": "12 months",
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


# Mollie counts subscription intervals in days, weeks and months. There is no year
# unit: "1 year" comes back 422 "The interval unit is invalid", as does "2 years".
# Measured against the Mollie test API -- a customer with a real directdebit mandate,
# one subscription create per candidate, all cancelled afterwards -- because a probe
# WITHOUT a mandate proves nothing: "no suitable mandates found" is checked before the
# interval is, so every candidate including nonsense returns an identical 422.
# An annual subscription is "12 months". (tests/contracts/mollie-contracts.json carries
# a near-identical pattern, but nothing loads that file, and it admits "0 months" --
# it is documentation, not the authority for this grammar.)
MOLLIE_INTERVAL_PATTERN = re.compile(r"^([1-9][0-9]*) (day|days|week|weeks|month|months)$")

# Mollie also documents an upper bound: "The maximum interval is one year
# (12 months, 52 weeks, or 365 days)."
# This matters beyond tidiness because this predicate doubles as the
# permanent-refusal classifier: an interval it calls valid is sent to Mollie,
# 422s, and is then treated as a TRANSIENT failure -- buying ten webhook
# re-deliveries for a refusal that can never change.
MOLLIE_INTERVAL_MAXIMUM = {"day": 365, "week": 52, "month": 12}


def is_valid_mollie_interval(interval: Any) -> bool:
    """True if Mollie's subscription API will accept this interval string."""
    if not isinstance(interval, str):
        return False

    match = MOLLIE_INTERVAL_PATTERN.match(interval.strip())
    if not match:
        return False

    count, unit = int(match.group(1)), match.group(2).rstrip("s")
    return count <= MOLLIE_INTERVAL_MAXIMUM[unit]


def validate_mollie_interval(interval: Any, context: str = "") -> str:
    """Return the interval, or throw if Mollie would refuse it.

    Deliberately throws rather than falling back to a default. The failure this
    guards is silent by construction: an interval Mollie refuses surfaces only as
    a 422 inside a broad except that writes an Error Log, so substituting a
    "sensible" default here would bill someone on the wrong schedule instead --
    the louder failure is the safer one.
    """
    if is_valid_mollie_interval(interval):
        return interval.strip()

    where = f" ({context})" if context else ""
    frappe.throw(
        _(
            "Mollie will not accept the subscription interval {0}{1}. Intervals are "
            "counted in days, weeks or months -- an annual subscription must be "
            "expressed as '12 months', not '1 year'."
        ).format(frappe.bold(interval if interval else repr(interval)), where),
        title=_("Invalid subscription interval"),
    )


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


def validate_mollie_amount(amount: Any, min_amount: Union[Decimal, float, str] = None) -> Decimal:
    """
    Validate and normalize amount for Mollie API using Decimal for precision.

    Mollie requires amounts to be positive with minimum transaction amounts
    (typically €0.01 for EUR). This utility ensures consistent validation across
    all payment and subscription operations using Decimal to avoid floating-point
    precision issues.

    Args:
        amount: Amount value (can be string, int, float, or Decimal)
        min_amount: Minimum allowed amount (default: 0.01 EUR)

    Returns:
        Validated Decimal amount with 2 decimal places

    Raises:
        ValueError: If amount is invalid, non-positive, or below minimum

    Example:
        >>> validate_mollie_amount("25.50")
        Decimal('25.50')
        >>> validate_mollie_amount(0.005)
        ValueError: Amount must be at least 0.01, got: 0.01
        >>> validate_mollie_amount(-10)
        ValueError: Amount must be positive, got: -10.00
    """
    if min_amount is None:
        min_amount = MIN_MOLLIE_AMOUNT
    elif not isinstance(min_amount, Decimal):
        min_amount = Decimal(str(min_amount))

    try:
        # Convert to string first to avoid float precision issues
        if isinstance(amount, Decimal):
            raw_decimal = amount
        elif isinstance(amount, float):
            # Use string conversion to preserve precision
            raw_decimal = Decimal(str(amount))
        else:
            raw_decimal = Decimal(str(amount))

        # Quantize to 2 decimal places with proper rounding
        amount_decimal = raw_decimal.quantize(DECIMAL_PLACES, rounding=ROUND_HALF_UP)

    except (TypeError, ValueError, InvalidOperation) as e:
        raise ValueError(f"Invalid amount format: {amount}") from e

    if amount_decimal <= 0:
        raise ValueError(f"Amount must be positive, got: {amount_decimal}")

    # Compare the *raw* (pre-rounding) value against the minimum. Otherwise a value
    # such as 0.005 would round up to 0.01 and be silently accepted even though it is
    # below Mollie's minimum transaction amount. This matches the documented contract.
    if raw_decimal < min_amount:
        raise ValueError(f"Amount must be at least {min_amount}, got: {amount_decimal}")

    return amount_decimal


def validate_mollie_id(mollie_id: str, id_type: str = "payment") -> Tuple[bool, str]:
    """
    Validate a single Mollie ID format.

    Args:
        mollie_id: The Mollie ID to validate
        id_type: Type of ID ('payment', 'refund', 'chargeback', 'customer', 'subscription', 'mandate')

    Returns:
        Tuple of (is_valid, error_message). Error message is empty if valid.

    Example:
        >>> validate_mollie_id("tr_WDqYK6vllg", "payment")
        (True, "")
        >>> validate_mollie_id("invalid", "payment")
        (False, "Invalid payment ID format: invalid")
        >>> validate_mollie_id("cst_123", "customer")
        (False, "Invalid customer ID format: cst_123")
    """
    if not mollie_id or not isinstance(mollie_id, str):
        return False, f"{id_type.capitalize()} ID must be a non-empty string"

    pattern = MOLLIE_ID_PATTERNS.get(id_type)
    if not pattern:
        return False, f"Unknown ID type: {id_type}"

    if not pattern.match(mollie_id):
        return False, f"Invalid {id_type} ID format: {mollie_id}"

    return True, ""


def validate_mollie_payment_ids(payment_ids: List[str]) -> None:
    """
    Validate a list of Mollie payment IDs, raising ValueError on invalid.

    This is a convenience function for batch validation that throws on first error.
    Use for API endpoint validation where you want to reject invalid input early.

    Args:
        payment_ids: List of payment IDs to validate

    Raises:
        ValueError: If any payment ID is invalid

    Example:
        >>> validate_mollie_payment_ids(["tr_WDqYK6vllg", "tr_AbCdEfGhIj"])  # Valid
        >>> validate_mollie_payment_ids(["invalid"])
        ValueError: Invalid Mollie payment ID: invalid - Invalid payment ID format: invalid
    """
    for pid in payment_ids:
        if not isinstance(pid, str):
            raise ValueError(_("Payment ID must be a string: {0}").format(pid))

        is_valid, error_msg = validate_mollie_id(pid, "payment")
        if not is_valid:
            raise ValueError(_("Invalid Mollie payment ID: {0} - {1}").format(pid, error_msg))


def user_has_any_role(allowed_roles: List[str], user: Optional[str] = None) -> bool:
    """
    Check if a user has any of the specified roles.

    Centralized role-based permission checking pattern used across Mollie integration.
    Using direct role check instead of frappe.has_permission() because has_permission()
    doesn't work correctly for service accounts (e.g., webhook users).

    Args:
        allowed_roles: List of role names that grant access
        user: User to check (defaults to current session user)

    Returns:
        True if user has any of the allowed roles, False otherwise

    Example:
        >>> user_has_any_role([Roles.SYSTEM_MANAGER, "Administrator"])
        True  # If current user has either role
        >>> user_has_any_role([Roles.VERENIGINGEN_ADMIN], "webhook@example.com")
        False  # If webhook user doesn't have that role
    """
    if user is None:
        user = frappe.session.user

    user_roles = frappe.get_roles(user)
    return any(role in allowed_roles for role in user_roles)


def format_mollie_amount(amount: Any, currency: str = "EUR") -> Dict[str, str]:
    """
    Format amount for Mollie API with consistent 2-decimal precision.

    Extracted from repeated `.2f` formatting patterns throughout payment_gateways.py
    (lines 165, 194, 542, 1194, 1974). Provides consistent amount structure.

    Uses Decimal internally to avoid floating-point precision issues.

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

    # Decimal already quantized to 2 places, convert to string
    return {"value": str(validated_amount), "currency": currency}


def format_mollie_amount_string(amount: Any) -> str:
    """
    Format amount as string for Mollie metadata (2-decimal precision).

    Used for metadata fields where only the string value is needed,
    not the full amount dictionary.

    Uses Decimal internally to avoid floating-point precision issues.

    Args:
        amount: Amount value (will be validated)

    Returns:
        Formatted amount string with 2 decimal places

    Example:
        >>> format_mollie_amount_string(25.5)
        "25.50"
    """
    validated_amount = validate_mollie_amount(amount)
    # Decimal already quantized to 2 places
    return str(validated_amount)


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


# Metadata sanitization constants
METADATA_MAX_TOTAL_SIZE = 1024  # Mollie metadata limit (1KB)
METADATA_MAX_KEY_LENGTH = 50
METADATA_MAX_VALUE_LENGTH = 255

# Allowed metadata keys that can be passed to Mollie
ALLOWED_METADATA_KEYS = frozenset(
    {
        # Reference tracking
        "reference_doctype",
        "reference_docname",
        "donation_id",
        "member_id",
        "invoice_id",
        "subscription_id",
        # Transaction context
        "donation_type",
        "payment_type",
        "payment_for",
        "description",
        # Non-sensitive identifiers
        "locale",
        "source",
        "campaign",
    }
)

# Keys that should never be passed to Mollie (PII/sensitive)
BLOCKED_METADATA_KEYS = frozenset(
    {
        # Personal Identifiable Information
        "email",
        "donor_email",
        "member_email",
        "phone",
        "contact_number",
        "address",
        "name",
        "first_name",
        "last_name",
        "full_name",
        # Financial data
        "iban",
        "bank_account",
        "credit_card",
        "card_number",
        # Authentication data
        "password",
        "token",
        "secret",
        "api_key",
    }
)


def sanitize_metadata(
    metadata: Optional[Dict[str, Any]],
    allow_unlisted_keys: bool = False,
    max_total_size: int = METADATA_MAX_TOTAL_SIZE,
) -> Dict[str, str]:
    """
    Sanitize metadata before sending to Mollie API.

    Applies key whitelisting, PII filtering, size limits, and value sanitization
    to ensure safe metadata is passed to external payment provider.

    Args:
        metadata: Raw metadata dictionary to sanitize
        allow_unlisted_keys: If True, allows keys not in ALLOWED_METADATA_KEYS
                            (but still blocks BLOCKED_METADATA_KEYS)
        max_total_size: Maximum total size in bytes for the metadata

    Returns:
        Sanitized metadata dictionary with string values only

    Example:
        >>> sanitize_metadata({"donation_id": "DON-001", "email": "test@example.com"})
        {"donation_id": "DON-001"}  # email is blocked
    """
    if not metadata:
        return {}

    sanitized = {}
    total_size = 0
    dropped_keys: Dict[str, str] = {}  # key -> reason for dropping

    for key, value in metadata.items():
        # Skip None values
        if value is None:
            continue

        # Block sensitive/PII keys
        key_lower = key.lower()
        if key_lower in BLOCKED_METADATA_KEYS or any(
            blocked in key_lower for blocked in ["password", "secret", "token", "key"]
        ):
            dropped_keys[key] = "blocked_pii"
            continue

        # Check if key is allowed
        if not allow_unlisted_keys and key not in ALLOWED_METADATA_KEYS:
            dropped_keys[key] = "not_whitelisted"
            continue

        # Truncate key if too long
        safe_key = str(key)[:METADATA_MAX_KEY_LENGTH]
        if len(str(key)) > METADATA_MAX_KEY_LENGTH:
            dropped_keys[key] = f"key_truncated_to_{METADATA_MAX_KEY_LENGTH}_chars"

        # Convert value to string and truncate if too long
        original_value = str(value)
        safe_value = original_value[:METADATA_MAX_VALUE_LENGTH]
        if len(original_value) > METADATA_MAX_VALUE_LENGTH:
            dropped_keys[
                key
            ] = f"value_truncated_from_{len(original_value)}_to_{METADATA_MAX_VALUE_LENGTH}_chars"

        # Check total size limit
        entry_size = len(safe_key) + len(safe_value) + 4  # Account for JSON formatting
        if total_size + entry_size > max_total_size:
            dropped_keys[key] = "size_limit_exceeded"
            # Log remaining keys that won't fit
            remaining_keys = [k for k in metadata.keys() if k not in sanitized and k not in dropped_keys]
            for remaining_key in remaining_keys:
                dropped_keys[remaining_key] = "size_limit_exceeded"
            break

        sanitized[safe_key] = safe_value
        total_size += entry_size

    # Log summary of dropped fields (visible in production)
    if dropped_keys:
        pii_blocked = [k for k, reason in dropped_keys.items() if reason == "blocked_pii"]
        not_whitelisted = [k for k, reason in dropped_keys.items() if reason == "not_whitelisted"]
        size_exceeded = [k for k, reason in dropped_keys.items() if reason == "size_limit_exceeded"]

        if pii_blocked:
            frappe.logger().warning(
                f"Mollie metadata: blocked {len(pii_blocked)} PII key(s): {', '.join(pii_blocked)}"
            )
        if not_whitelisted:
            frappe.logger().info(
                f"Mollie metadata: skipped {len(not_whitelisted)} non-whitelisted key(s): {', '.join(not_whitelisted)}"
            )
        if size_exceeded:
            frappe.logger().warning(
                f"Mollie metadata: dropped {len(size_exceeded)} key(s) due to size limit: {', '.join(size_exceeded)}"
            )

    return sanitized


def merge_metadata_safely(
    base_metadata: Dict[str, Any],
    additional_metadata: Optional[Dict[str, Any]],
) -> Dict[str, str]:
    """
    Safely merge additional metadata into base metadata with sanitization.

    The base metadata is added first (whitelisted keys only), then additional
    metadata is merged with the same sanitization rules. This prevents
    additional metadata from overwriting critical base metadata.

    Args:
        base_metadata: Core metadata that must be preserved
        additional_metadata: Optional user-provided metadata to merge

    Returns:
        Merged and sanitized metadata dictionary

    Example:
        >>> base = {"reference_doctype": "Donation", "reference_docname": "DON-001"}
        >>> additional = {"campaign": "spring-2024", "email": "test@example.com"}
        >>> merge_metadata_safely(base, additional)
        {"reference_doctype": "Donation", "reference_docname": "DON-001", "campaign": "spring-2024"}
    """
    # Sanitize base metadata (strict - only whitelisted keys)
    result = sanitize_metadata(base_metadata, allow_unlisted_keys=False)

    if additional_metadata:
        # Sanitize additional metadata (also strict by default)
        additional_sanitized = sanitize_metadata(additional_metadata, allow_unlisted_keys=False)

        # Merge but don't overwrite base keys
        for key, value in additional_sanitized.items():
            if key not in result:
                result[key] = value

    return result


def read_payment_field(payment: Any, snake_case: str, camel_case: Optional[str] = None) -> Any:
    """Read one field from a Mollie payment, whichever shape it arrived in.

    Three shapes reach this code and they are not interchangeable:

    * ``mollie.api.objects.payment.Payment`` -- a ``dict`` SUBCLASS whose keys are
      camelCase and whose properties are snake_case;
    * the normalised snake_case dict ``_fetch_payment_from_mollie`` builds;
    * plain camelCase JSON straight from the API (captured fixtures).

    ``hasattr({...}, "subscription_id")`` is False, so an attribute-only reader
    returns nothing for two of the three -- the defect this replaces. Returns
    None when the field is absent in every shape.
    """
    camel_case = camel_case or snake_case

    if isinstance(payment, dict):
        for key in (snake_case, camel_case):
            if key in payment:
                return payment[key]
        return None

    value = getattr(payment, snake_case, None)
    if value is None:
        value = getattr(payment, camel_case, None)
    return value


def read_payment_metadata(payment: Any) -> Dict[str, Any]:
    """A Mollie payment's metadata, always as a dict.

    Mollie copies a subscription's metadata onto every charge it generates --
    including copying nothing. A subscription with no metadata yields
    ``metadata: null`` on its charges (measured: sub_5euSBaLzqF), and metadata is
    free-form, so a caller cannot assume a mapping. Anything that is not a dict
    becomes ``{}``.
    """
    metadata = read_payment_field(payment, "metadata")
    return metadata if isinstance(metadata, dict) else {}
