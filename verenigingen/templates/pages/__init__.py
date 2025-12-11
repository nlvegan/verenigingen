# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""Shared utilities for portal page templates."""

from datetime import date, datetime


def serialize_dates(obj):
    """
    Recursively convert date/datetime objects to strings for JSON serialization.

    Handles nested dicts and lists. Returns ISO format strings (YYYY-MM-DD or
    YYYY-MM-DD HH:MM:SS).

    Args:
        obj: Any object - date, datetime, dict, list, or other

    Returns:
        Object with dates converted to strings
    """
    if isinstance(obj, datetime):
        return obj.strftime("%Y-%m-%d %H:%M:%S")
    elif isinstance(obj, date):
        return obj.strftime("%Y-%m-%d")
    elif isinstance(obj, dict):
        return {k: serialize_dates(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [serialize_dates(item) for item in obj]
    return obj
