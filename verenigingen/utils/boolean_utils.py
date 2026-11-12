"""
Boolean utility functions for handling JavaScript boolean strings
"""

import frappe


def cbool(value):
    """
    Convert various boolean representations to integer (0 or 1)

    Handles:
    - JavaScript boolean strings: 'true' -> 1, 'false' -> 0
    - Python booleans: True -> 1, False -> 0
    - Numbers: 1 -> 1, 0 -> 0
    - Strings: '1' -> 1, '0' -> 0
    - None/empty: -> 0

    Args:
        value: Value to convert

    Returns:
        int: 1 for truthy values, 0 for falsy values
    """
    if value is None:
        return 0

    if isinstance(value, bool):
        return 1 if value else 0

    if isinstance(value, (int, float)):
        return 1 if value else 0

    if isinstance(value, str):
        value = value.lower().strip()
        if value in ("true", "yes", "on", "1"):
            return 1
        elif value in ("false", "no", "off", "0", ""):
            return 0
        else:
            # Try to convert to number
            try:
                return 1 if float(value) else 0
            except (ValueError, TypeError):
                return 0

    # For other types, use frappe's cint
    return frappe.utils.cint(value)


_FALSE_STRINGS = ("false", "no", "off", "0", "0.0")


def is_dry_run(value):
    """True unless the caller explicitly says no (#2377, #2385).

    A ``dry_run`` flag guards a destructive run, so it must fail closed: ``cbool`` alone maps an
    unrecognised string, "" or None to 0 and would turn it into a real run. Over HTTP the flag
    is a string, so "false" must also be able to request the real run.
    """
    return str(value).strip().lower() not in _FALSE_STRINGS


_TRUE_STRINGS = ("1", "true", "yes", "on")


def is_confirmed(value):
    """True only for an explicit yes: True, or "1"/"true"/"yes"/"on" (#2385).

    For confirmation flags guarding a destructive run. ``cbool`` fails OPEN here: it parses any
    other string as a float, so "nan", "inf", "0.5" and "1e-5" all become 1.
    """
    return str(value).strip().lower() in _TRUE_STRINGS


def safe_int(value):
    """
    Safely convert value to integer, handling boolean strings

    This is a drop-in replacement for int() that handles JavaScript boolean strings

    Args:
        value: Value to convert

    Returns:
        int: Converted integer value
    """
    if isinstance(value, str):
        value = value.lower().strip()
        if value in ("true", "yes", "on"):
            return 1
        elif value in ("false", "no", "off"):
            return 0

    return frappe.utils.cint(value)
