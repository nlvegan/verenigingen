"""
Shared CSV utilities for Mollie admin tools.

Extracted from the duplicated `sanitize_csv_field` implementations in
`mollie_bulk_payment_creation.py` and `mollie_subscription_recreation.py`
so both CSV-handling pages share a single, verbatim-preserved
implementation.
"""


def sanitize_csv_field(value: str) -> str:
    """
    Sanitize CSV field to prevent CSV injection attacks.

    Args:
        value: Field value to sanitize

    Returns:
        str: Sanitized value safe for CSV output
    """
    if not value:
        return value

    value_str = str(value)

    # Prevent CSV injection by escaping formula indicators
    dangerous_chars = ("=", "+", "-", "@", "\t", "\r")
    if value_str.startswith(dangerous_chars):
        return "'" + value_str

    return value_str
