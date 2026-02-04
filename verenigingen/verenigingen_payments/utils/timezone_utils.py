"""
Timezone utilities for Mollie integration
Handles conversion between timezone-aware and timezone-naive datetimes,
date range calculations, and Mollie API response filtering.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

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


def safe_datetime_to_isoformat(dt_value: Any) -> Optional[str]:
    """
    Safely convert a datetime value to ISO format string.
    Handles datetime objects, strings, and None values from Mollie API.

    Args:
        dt_value: datetime object, string, or None

    Returns:
        ISO format string or None if input is None/invalid

    Examples:
        >>> safe_datetime_to_isoformat(datetime.now())
        '2025-01-15T10:30:00'
        >>> safe_datetime_to_isoformat("2025-01-15T10:30:00+00:00")
        '2025-01-15T10:30:00+00:00'
        >>> safe_datetime_to_isoformat(None)
        None
    """
    if dt_value is None:
        return None

    # If it's already a string, return as-is (assuming it's already in ISO format)
    if isinstance(dt_value, str):
        return dt_value

    # If it's a datetime object, convert to ISO format
    if isinstance(dt_value, datetime):
        try:
            # Convert to timezone-naive datetime for consistent formatting
            dt_naive = ensure_timezone_naive(dt_value)
            return dt_naive.isoformat() if dt_naive else None
        except Exception as e:
            frappe.logger().warning(f"Failed to convert datetime to ISO format: {e}")
            return None

    # For other types, try to convert to string
    return str(dt_value) if dt_value is not None else None


def get_period_date_range(
    period: str, reference_date: Optional[datetime] = None
) -> Tuple[datetime, datetime]:
    """
    Get start and end datetimes for a named period.

    Args:
        period: Period name - 'day', 'week', 'month', 'quarter', 'year'
        reference_date: Reference datetime (default: now in UTC)

    Returns:
        Tuple of (start_date, end_date) as timezone-aware datetimes

    Examples:
        >>> start, end = get_period_date_range("month")
        >>> start, end = get_period_date_range("quarter", some_date)
    """
    if reference_date is None:
        reference_date = datetime.now(timezone.utc)
    elif reference_date.tzinfo is None:
        reference_date = reference_date.replace(tzinfo=timezone.utc)

    if period == "day":
        start_date = reference_date.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
        # Start of current week (Monday)
        start_date = (reference_date - timedelta(days=reference_date.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    elif period == "month":
        start_date = reference_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif period == "quarter":
        quarter_start_month = ((reference_date.month - 1) // 3) * 3 + 1
        start_date = reference_date.replace(
            month=quarter_start_month, day=1, hour=0, minute=0, second=0, microsecond=0
        )
    elif period == "year":
        start_date = reference_date.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        raise ValueError(f"Unknown period: {period}. Use 'day', 'week', 'month', 'quarter', or 'year'")

    return start_date, reference_date


def filter_items_by_date_range(
    items: List[Dict],
    start_date: datetime,
    end_date: datetime,
    date_field: str = "createdAt",
) -> List[Dict]:
    """
    Filter Mollie API response items by date range.

    Args:
        items: List of Mollie API response dicts
        start_date: Start of date range (inclusive)
        end_date: End of date range (inclusive)
        date_field: Name of the date field to filter on (default: 'createdAt')

    Returns:
        Filtered list of items within the date range

    Examples:
        >>> payments = filter_items_by_date_range(
        ...     all_payments,
        ...     thirty_days_ago,
        ...     now,
        ...     date_field="createdAt"
        ... )
    """
    filtered = []

    for item in items:
        date_value = item.get(date_field)
        if not date_value:
            continue

        parsed_date = parse_mollie_datetime(date_value)
        if parsed_date is None:
            continue

        # Ensure comparison datetimes are timezone-aware
        if start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=timezone.utc)
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)

        if start_date <= parsed_date <= end_date:
            filtered.append(item)

    return filtered


def parse_period_key_to_date_range(period_key: str) -> Tuple[datetime, datetime]:
    """
    Parse a period key (YYYY-MM format) to start and end datetimes.

    Used for parsing Mollie settlement period keys.

    Args:
        period_key: Period key in YYYY-MM format (e.g., "2025-01")

    Returns:
        Tuple of (period_start, period_end) as timezone-aware datetimes

    Raises:
        ValueError: If period_key format is invalid

    Examples:
        >>> start, end = parse_period_key_to_date_range("2025-01")
        >>> print(start)  # 2025-01-01 00:00:00+00:00
        >>> print(end)    # 2025-01-31 23:59:59+00:00
    """
    try:
        year, month = period_key.split("-")
        year, month = int(year), int(month)

        period_start = datetime(year, month, 1, tzinfo=timezone.utc)

        # Calculate period end (last day of month)
        if month == 12:
            next_month_start = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            next_month_start = datetime(year, month + 1, 1, tzinfo=timezone.utc)

        period_end = next_month_start - timedelta(seconds=1)

        return period_start, period_end

    except (ValueError, AttributeError) as e:
        raise ValueError(f"Invalid period key format '{period_key}'. Expected YYYY-MM.") from e
