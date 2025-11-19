"""
Timezone utilities for Mollie integration
Handles conversion between timezone-aware and timezone-naive datetimes
"""

from datetime import datetime, timezone

import frappe
from frappe.utils import get_system_timezone


def ensure_timezone_aware(dt: datetime) -> datetime:
    """
    Ensure datetime is timezone-aware

    Args:
        dt: datetime object (may be naive or aware)

    Returns:
        timezone-aware datetime object
    """
    if dt is None:
        return None

    if dt.tzinfo is None:
        # Assume UTC for naive datetimes from Mollie
        return dt.replace(tzinfo=timezone.utc)

    return dt


def ensure_timezone_naive(dt: datetime) -> datetime:
    """
    Ensure datetime is timezone-naive (for Frappe compatibility)

    Args:
        dt: datetime object (may be naive or aware)

    Returns:
        timezone-naive datetime object
    """
    if dt is None:
        return None

    if dt.tzinfo is not None:
        # Convert to UTC and remove timezone info
        return dt.astimezone(timezone.utc).replace(tzinfo=None)

    return dt


def parse_mollie_datetime(date_string: str) -> datetime:
    """
    Parse Mollie API datetime string consistently

    Args:
        date_string: ISO datetime string from Mollie API

    Returns:
        timezone-aware datetime object
    """
    if not date_string:
        return None

    try:
        # Handle both Z suffix and +00:00 suffix
        if date_string.endswith("Z"):
            date_string = date_string.replace("Z", "+00:00")

        return datetime.fromisoformat(date_string)
    except (ValueError, TypeError) as e:
        frappe.logger().warning(f"Failed to parse Mollie datetime '{date_string}': {e}")
        return None


def mollie_datetime_for_display(dt: datetime) -> str:
    """
    Format Mollie datetime for display in Frappe

    Args:
        dt: timezone-aware datetime from Mollie

    Returns:
        formatted string for display
    """
    if not dt:
        return ""

    if dt.tzinfo is not None:
        # Convert to system timezone for display
        system_tz = get_system_timezone()
        try:
            import pytz

            system_tz_obj = pytz.timezone(system_tz)
            local_dt = dt.astimezone(system_tz_obj)
            return local_dt.strftime("%Y-%m-%d %H:%M:%S %Z")
        except:
            # Fallback to UTC
            utc_dt = dt.astimezone(timezone.utc)
            return utc_dt.strftime("%Y-%m-%d %H:%M:%S UTC")

    return dt.strftime("%Y-%m-%d %H:%M:%S")
