"""
Mollie SDK Amount Helpers

Utility functions for safely extracting amount values from Mollie SDK objects.

The Mollie Python SDK v3+ returns amount as a dict:
    {"value": "10.00", "currency": "EUR"}

This module provides helper functions that handle both dict format (SDK v3+)
and potential legacy object format for backward compatibility.
"""

from typing import Any, Optional, Union


def extract_amount_value(amount_obj: Any) -> str:
    """
    Extract amount value from Mollie SDK amount object.

    Handles both dict format (SDK v3+) and legacy object format.

    Args:
        amount_obj: Mollie amount (dict or object)

    Returns:
        Amount value as string (e.g., "10.00")

    Examples:
        >>> extract_amount_value({"value": "10.00", "currency": "EUR"})
        "10.00"
        >>> extract_amount_value(None)
        "0.00"
    """
    if amount_obj is None:
        return "0.00"

    # SDK v3+ dict format (correct)
    if isinstance(amount_obj, dict):
        return str(amount_obj.get("value", "0.00"))

    # Legacy fallback for object-style access
    if hasattr(amount_obj, "value"):
        return str(amount_obj.value)
    if hasattr(amount_obj, "amount"):
        return str(amount_obj.amount)

    return "0.00"


def extract_amount_currency(amount_obj: Any) -> str:
    """
    Extract currency from Mollie SDK amount object.

    Args:
        amount_obj: Mollie amount (dict or object)

    Returns:
        Currency code (e.g., "EUR"), defaults to "EUR"

    Examples:
        >>> extract_amount_currency({"value": "10.00", "currency": "USD"})
        "USD"
        >>> extract_amount_currency(None)
        "EUR"
    """
    if amount_obj is None:
        return "EUR"

    # SDK v3+ dict format (correct)
    if isinstance(amount_obj, dict):
        return str(amount_obj.get("currency", "EUR"))

    # Legacy fallback for object-style access
    if hasattr(amount_obj, "currency"):
        return str(amount_obj.currency)

    return "EUR"


def extract_amount_float(amount_obj: Any) -> float:
    """
    Extract amount as float from Mollie SDK amount object.

    Args:
        amount_obj: Mollie amount (dict or object)

    Returns:
        Amount as float

    Examples:
        >>> extract_amount_float({"value": "10.00", "currency": "EUR"})
        10.0
        >>> extract_amount_float(None)
        0.0
    """
    try:
        return float(extract_amount_value(amount_obj))
    except (ValueError, TypeError):
        return 0.0


def format_amount_display(amount_obj: Any) -> str:
    """
    Format amount for display (value + currency).

    Args:
        amount_obj: Mollie amount (dict or object)

    Returns:
        Formatted string like "10.00 EUR"

    Examples:
        >>> format_amount_display({"value": "10.00", "currency": "EUR"})
        "10.00 EUR"
    """
    value = extract_amount_value(amount_obj)
    currency = extract_amount_currency(amount_obj)
    return f"{value} {currency}"


def create_amount_dict(value: Union[str, float, int], currency: str = "EUR") -> dict:
    """
    Create a Mollie-compatible amount dict.

    Args:
        value: Amount value (will be formatted to 2 decimal places)
        currency: Currency code (default: EUR)

    Returns:
        Dict in Mollie format: {"value": "10.00", "currency": "EUR"}

    Examples:
        >>> create_amount_dict(10.5)
        {"value": "10.50", "currency": "EUR"}
        >>> create_amount_dict("25.00", "USD")
        {"value": "25.00", "currency": "USD"}
    """
    # Convert to float first, then format to 2 decimal places
    float_value = float(value)
    return {
        "value": f"{float_value:.2f}",
        "currency": currency,
    }
