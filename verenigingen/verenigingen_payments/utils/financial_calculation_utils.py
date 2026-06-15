"""
Financial Calculation Utilities for Mollie Integration

Provides reusable functions for financial calculations including:
- Decimal to float conversion for JSON serialization
- Amount prorating for partial periods
- Date range overlap calculations
"""

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple, Union


def convert_decimal_dict_to_float(
    data: Dict[str, Any], keys: Optional[List[str]] = None, recursive: bool = False
) -> None:
    """
    Convert Decimal values to float in a dictionary, in-place.

    Useful for preparing data for JSON serialization since Decimal
    is not JSON-serializable by default.

    Args:
        data: Dictionary to modify in-place
        keys: Specific keys to convert. If None, converts all Decimal values.
        recursive: If True, recursively process nested dicts

    Examples:
        >>> metrics = {"total": Decimal("123.45"), "count": 5}
        >>> convert_decimal_dict_to_float(metrics)
        >>> metrics["total"]
        123.45

        >>> nested = {"current_month": {"total": Decimal("100")}}
        >>> convert_decimal_dict_to_float(nested, recursive=True)
    """
    if keys is None:
        # Convert all Decimal values
        for key, value in data.items():
            if isinstance(value, Decimal):
                data[key] = float(value)
            elif recursive and isinstance(value, dict):
                convert_decimal_dict_to_float(value, keys=None, recursive=True)
    else:
        # Convert only specified keys
        for key in keys:
            if key in data and isinstance(data[key], Decimal):
                data[key] = float(data[key])


def convert_nested_decimals_to_float(data: Dict[str, Dict[str, Any]], keys: List[str]) -> None:
    """
    Convert Decimal values to float for specified keys in nested dict structure.

    Commonly used for metrics dictionaries with a nested structure like:
    {"current_month": {"total_costs": Decimal("100"), "count": 5}}

    Args:
        data: Nested dictionary with structure {outer_key: {inner_key: value}}
        keys: List of inner keys whose values should be converted to float

    Examples:
        >>> breakdown = {
        ...     "current_month": {
        ...         "transaction_fees": Decimal("10.50"),
        ...         "chargeback_fees": Decimal("5.00"),
        ...         "total_costs": Decimal("15.50")
        ...     }
        ... }
        >>> convert_nested_decimals_to_float(
        ...     breakdown,
        ...     ["transaction_fees", "chargeback_fees", "total_costs"]
        ... )
    """
    for outer_key, inner_dict in data.items():
        if isinstance(inner_dict, dict):
            for key in keys:
                if key in inner_dict and isinstance(inner_dict[key], Decimal):
                    inner_dict[key] = float(inner_dict[key])


def prorate_amount_by_days(
    amount: Union[Decimal, float],
    total_days: int,
    actual_days: int,
) -> Decimal:
    """
    Prorate an amount based on the ratio of actual days to total days.

    Used for calculating partial period amounts in settlement reconciliation.

    Args:
        amount: The full amount to prorate
        total_days: Total number of days in the full period
        actual_days: Number of days actually covered

    Returns:
        Prorated amount as Decimal

    Raises:
        ValueError: If total_days is zero or negative

    Examples:
        >>> # Half a month coverage
        >>> prorate_amount_by_days(Decimal("100"), 30, 15)
        Decimal('50')

        >>> # Full coverage returns original amount
        >>> prorate_amount_by_days(Decimal("100"), 30, 30)
        Decimal('100')
    """
    if total_days <= 0:
        raise ValueError("total_days must be positive")

    if actual_days >= total_days:
        # Full coverage - return original amount
        return Decimal(str(amount)) if not isinstance(amount, Decimal) else amount

    if actual_days <= 0:
        return Decimal("0")

    amount_decimal = Decimal(str(amount)) if not isinstance(amount, Decimal) else amount
    ratio = Decimal(str(actual_days)) / Decimal(str(total_days))

    return amount_decimal * ratio


def calculate_date_overlap(
    range1_start: datetime,
    range1_end: datetime,
    range2_start: datetime,
    range2_end: datetime,
) -> Tuple[Optional[datetime], Optional[datetime], int]:
    """
    Calculate the overlap between two date ranges.

    Args:
        range1_start: Start of first range
        range1_end: End of first range
        range2_start: Start of second range
        range2_end: End of second range

    Returns:
        Tuple of (overlap_start, overlap_end, overlap_days)
        Returns (None, None, 0) if no overlap exists

    Examples:
        >>> # Partial overlap
        >>> r1_start = datetime(2025, 1, 1)
        >>> r1_end = datetime(2025, 1, 31)
        >>> r2_start = datetime(2025, 1, 15)
        >>> r2_end = datetime(2025, 2, 15)
        >>> start, end, days = calculate_date_overlap(r1_start, r1_end, r2_start, r2_end)
        >>> days
        17  # Jan 15 to Jan 31

        >>> # No overlap
        >>> r1_start = datetime(2025, 1, 1)
        >>> r1_end = datetime(2025, 1, 15)
        >>> r2_start = datetime(2025, 2, 1)
        >>> r2_end = datetime(2025, 2, 28)
        >>> start, end, days = calculate_date_overlap(r1_start, r1_end, r2_start, r2_end)
        >>> days
        0
    """
    # Check if ranges overlap
    if range1_end < range2_start or range2_end < range1_start:
        return None, None, 0

    overlap_start = max(range1_start, range2_start)
    overlap_end = min(range1_end, range2_end)

    # Calculate overlap days (inclusive)
    overlap_days = (overlap_end - overlap_start).days + 1

    return overlap_start, overlap_end, overlap_days


def find_gap_periods(
    covered_periods: List[Dict[str, datetime]],
    range_start: datetime,
    range_end: datetime,
) -> List[Dict[str, datetime]]:
    """
    Find date gaps not covered by the given periods within a range.

    Used to identify unsettled periods in settlement reconciliation.

    Args:
        covered_periods: List of dicts with 'start' and 'end' datetime keys
        range_start: Start of the range to check
        range_end: End of the range to check

    Returns:
        List of gap periods as dicts with 'start' and 'end' keys

    Examples:
        >>> covered = [
        ...     {"start": datetime(2025, 1, 1), "end": datetime(2025, 1, 15)},
        ...     {"start": datetime(2025, 1, 20), "end": datetime(2025, 1, 31)}
        ... ]
        >>> gaps = find_gap_periods(covered, datetime(2025, 1, 1), datetime(2025, 1, 31))
        >>> len(gaps)
        1  # Gap from Jan 16 to Jan 19
    """
    if not covered_periods:
        return [{"start": range_start, "end": range_end}]

    # Sort covered periods by start date
    sorted_periods = sorted(covered_periods, key=lambda p: p["start"])
    gaps = []

    current_date = range_start

    for period in sorted_periods:
        # Gap before this covered period?
        if current_date < period["start"]:
            gap_end = min(period["start"] - timedelta(days=1), range_end)
            if gap_end >= current_date:
                gaps.append({"start": current_date, "end": gap_end})

        # Move current date past this covered period
        current_date = max(current_date, period["end"] + timedelta(days=1))

        if current_date > range_end:
            break

    # Gap after all covered periods?
    if current_date <= range_end:
        gaps.append({"start": current_date, "end": range_end})

    return gaps


def safe_decimal_from_dict(
    data: Dict[str, Any],
    *keys: str,
    default: Decimal = Decimal("0"),
) -> Decimal:
    """
    Safely extract a Decimal value from nested dict keys.

    Commonly used for extracting amounts from Mollie API responses
    with structures like {"amountNet": {"value": "123.45"}}.

    Args:
        data: Dictionary to extract from
        *keys: Keys to traverse (in order)
        default: Default value if extraction fails

    Returns:
        Extracted value as Decimal

    Examples:
        >>> data = {"amountNet": {"value": "123.45"}}
        >>> safe_decimal_from_dict(data, "amountNet", "value")
        Decimal('123.45')

        >>> # Missing key returns default
        >>> safe_decimal_from_dict(data, "missing", "value")
        Decimal('0')
    """
    try:
        current = data
        for key in keys:
            if isinstance(current, dict):
                current = current.get(key)
            else:
                return default

            if current is None:
                return default

        return Decimal(str(current))
    except (ValueError, TypeError, AttributeError, InvalidOperation):
        # Decimal(str(<malformed>)) raises decimal.InvalidOperation (an
        # ArithmeticError, not a ValueError) for non-numeric strings — catch it
        # so this "safe" extractor returns the default instead of crashing.
        return default
