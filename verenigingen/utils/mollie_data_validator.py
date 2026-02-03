"""
Compatibility Shim for Mollie Data Validator

This module provides backward compatibility for code that was importing
from the old path (verenigingen.utils.mollie_data_validator) by redirecting
to the new enhanced validation system at the correct location.

Also provides utility functions for Mollie customer ID handling.
"""

import re

import frappe

# Redirect to the new validation system
from verenigingen.verenigingen_payments.mollie.utils.data_validator import (
    MollieDataValidator,
    get_mollie_validator,
    validate_mollie_customer_data,
)

# Re-export everything for backward compatibility
# Also provide the old class name for compatibility
MollieValidator = MollieDataValidator


def parse_mollie_customer_ids(customer_id_string, max_ids=10):
    """
    Safely parse and validate comma-separated Mollie customer IDs.

    Args:
        customer_id_string: String containing comma-separated customer IDs
        max_ids: Maximum number of IDs allowed (default 10, security limit)

    Returns:
        List of validated customer ID strings

    Raises:
        None - logs errors but returns empty list or truncated list on invalid input
    """
    if not customer_id_string:
        return []

    if not isinstance(customer_id_string, str):
        frappe.log_error(
            f"Invalid mollie_customer_id type: {type(customer_id_string).__name__}",
            "Mollie Customer ID Validation",
        )
        return []

    # Split on commas and strip whitespace
    customer_ids = [cid.strip() for cid in customer_id_string.split(",") if cid.strip()]

    # Enforce maximum limit to prevent DoS
    if len(customer_ids) > max_ids:
        frappe.log_error(
            f"Too many customer IDs ({len(customer_ids)}) exceeds limit of {max_ids}. Truncating.",
            "Mollie Customer ID Validation",
        )
        customer_ids = customer_ids[:max_ids]

    # Validate format - Mollie customer IDs match pattern: cst_[A-Za-z0-9]{10}
    customer_id_pattern = re.compile(r"^cst_[A-Za-z0-9]{10}$")
    validated_ids = []

    for cid in customer_ids:
        if customer_id_pattern.match(cid):
            validated_ids.append(cid)
        else:
            frappe.log_error(
                f"Invalid Mollie customer ID format: {cid}. Expected pattern: cst_[A-Za-z0-9]{{10}}",
                "Mollie Customer ID Validation",
            )

    return validated_ids


__all__ = [
    "get_mollie_validator",
    "validate_mollie_customer_data",
    "MollieDataValidator",
    "MollieValidator",
    "parse_mollie_customer_ids",
]
