"""
Dutch Banking Calendar Utilities

Provides functionality for determining Dutch banking days, holidays,
and SEPA collection date validation according to Dutch banking regulations.
"""

from datetime import date, datetime, timedelta
from typing import List, Optional

import frappe
from frappe.utils import add_days, getdate


def get_dutch_bank_holidays(year: int) -> List[date]:
    """
    Get list of Dutch bank holidays for a given year

    Args:
        year: Year to get holidays for

    Returns:
        List of bank holiday dates
    """
    holidays = []

    # Fixed holidays
    holidays.extend(
        [
            date(year, 1, 1),  # New Year's Day
            date(year, 4, 27),  # King's Day (if not on Sunday)
            date(year, 5, 5),  # Liberation Day (every 5 years, all years since 2020)
            date(year, 12, 25),  # Christmas Day
            date(year, 12, 26),  # Boxing Day
        ]
    )

    # King's Day adjustment (if on Sunday, moved to Saturday)
    kings_day = date(year, 4, 27)
    if kings_day.weekday() == 6:  # Sunday
        holidays.remove(kings_day)
        holidays.append(date(year, 4, 26))  # Move to Saturday

    # Easter-dependent holidays
    easter_date = calculate_easter(year)
    holidays.extend(
        [
            easter_date - timedelta(days=2),  # Good Friday
            easter_date + timedelta(days=1),  # Easter Monday
            easter_date + timedelta(days=39),  # Ascension Day
            easter_date + timedelta(days=50),  # Whit Monday
        ]
    )

    return sorted(holidays)


def calculate_easter(year: int) -> date:
    """
    Calculate Easter date for a given year using the algorithm

    Args:
        year: Year to calculate Easter for

    Returns:
        Easter date
    """
    # Anonymous Gregorian algorithm
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    easter_calc = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * easter_calc) // 451
    month = (h + easter_calc - 7 * m + 114) // 31
    day = ((h + easter_calc - 7 * m + 114) % 31) + 1

    return date(year, month, day)


def is_dutch_banking_day(check_date: str) -> bool:
    """
    Check if a given date is a Dutch banking day

    Args:
        check_date: Date to check (string format)

    Returns:
        True if it's a banking day, False otherwise
    """
    try:
        date_obj = getdate(check_date)

        # Check if it's a weekend
        if date_obj.weekday() >= 5:  # Saturday (5) or Sunday (6)
            return False

        # Check if it's a bank holiday
        holidays = get_dutch_bank_holidays(date_obj.year)
        if date_obj in holidays:
            return False

        return True

    except Exception:
        return False


def get_next_banking_day(start_date: str, days_ahead: int = 0) -> str:
    """
    Get the next banking day from a given date

    Args:
        start_date: Starting date
        days_ahead: Minimum number of days ahead

    Returns:
        Next banking day as string
    """
    current_date = getdate(start_date)

    # Add minimum days ahead
    current_date = current_date + timedelta(days=days_ahead)

    # Find next banking day
    while not is_dutch_banking_day(current_date.strftime("%Y-%m-%d")):
        current_date = current_date + timedelta(days=1)

    return current_date.strftime("%Y-%m-%d")


def validate_sepa_collection_date(collection_date: str, mandate_type: str = "RCUR") -> dict:
    """
    Validate SEPA collection date according to Dutch banking rules

    Args:
        collection_date: Proposed collection date
        mandate_type: Mandate type (OOFF, FRST, RCUR)

    Returns:
        Validation result with suggestions
    """
    try:
        collection_dt = getdate(collection_date)
        today_dt = getdate(frappe.utils.today())

        # Calculate minimum lead time
        if mandate_type == "OOFF":  # One-off
            min_lead_days = 5
        elif mandate_type == "FRST":  # First
            min_lead_days = 5
        else:  # RCUR - Recurring
            min_lead_days = 2

        # Check minimum lead time
        days_ahead = (collection_dt - today_dt).days
        if days_ahead < min_lead_days:
            suggested_date = get_next_banking_day(frappe.utils.today(), min_lead_days)
            return {
                "valid": False,
                "error": f"Collection date must be at least {min_lead_days} banking days ahead for {mandate_type} mandates",
                "suggested_date": suggested_date,
            }

        # Check if it's a banking day
        if not is_dutch_banking_day(collection_date):
            suggested_date = get_next_banking_day(collection_date)
            return {
                "valid": False,
                "error": "Collection date must be a banking day (not weekend or holiday)",
                "suggested_date": suggested_date,
            }

        return {"valid": True, "collection_date": collection_date}

    except Exception as e:
        return {"valid": False, "error": f"Invalid date format: {str(e)}"}


def get_sepa_processing_calendar(year: int) -> dict:
    """
    Get SEPA processing calendar for a year with banking days

    Args:
        year: Year to get calendar for

    Returns:
        Calendar data with banking days and holidays
    """
    holidays = get_dutch_bank_holidays(year)

    # Generate all dates in year
    start_date = date(year, 1, 1)
    end_date = date(year, 12, 31)

    banking_days = []
    non_banking_days = []

    current_date = start_date
    while current_date <= end_date:
        if is_dutch_banking_day(current_date.strftime("%Y-%m-%d")):
            banking_days.append(current_date.strftime("%Y-%m-%d"))
        else:
            non_banking_days.append(
                {
                    "date": current_date.strftime("%Y-%m-%d"),
                    "reason": "Weekend" if current_date.weekday() >= 5 else "Holiday",
                }
            )
        current_date += timedelta(days=1)

    return {
        "year": year,
        "total_banking_days": len(banking_days),
        "total_non_banking_days": len(non_banking_days),
        "holidays": [h.strftime("%Y-%m-%d") for h in holidays],
        "banking_days_count_by_month": get_banking_days_by_month(year),
        "non_banking_days": non_banking_days,
    }


def get_banking_days_by_month(year: int) -> dict:
    """
    Get count of banking days by month for a year

    Args:
        year: Year to analyze

    Returns:
        Dictionary with month names and banking day counts
    """
    months = {}

    for month in range(1, 13):
        # Get first and last day of month
        if month == 12:
            last_day = date(year, month, 31)
        else:
            last_day = date(year, month + 1, 1) - timedelta(days=1)

        first_day = date(year, month, 1)

        # Count banking days in month
        banking_days = 0
        current_date = first_day

        while current_date <= last_day:
            if is_dutch_banking_day(current_date.strftime("%Y-%m-%d")):
                banking_days += 1
            current_date += timedelta(days=1)

        month_name = current_date.replace(day=1).strftime("%B")
        months[month_name] = banking_days

    return months


def calculate_optimal_collection_dates(start_date: str, frequency: str, count: int) -> List[str]:
    """
    Calculate optimal collection dates for recurring payments

    Args:
        start_date: First collection date
        frequency: Collection frequency (monthly, quarterly, yearly)
        count: Number of collection dates to generate

    Returns:
        List of optimal collection dates
    """
    collection_dates = []
    current_date = getdate(start_date)

    # Ensure start date is a banking day
    if not is_dutch_banking_day(start_date):
        current_date = getdate(get_next_banking_day(start_date))

    collection_dates.append(current_date.strftime("%Y-%m-%d"))

    for i in range(1, count):
        if frequency == "monthly":
            # Add one month, handling month-end properly
            if current_date.month == 12:
                next_date = current_date.replace(year=current_date.year + 1, month=1)
            else:
                try:
                    next_date = current_date.replace(month=current_date.month + 1)
                except ValueError:
                    # Handle month-end dates (e.g., Jan 31 -> Feb 28)
                    next_month = current_date.month + 1 if current_date.month < 12 else 1
                    next_year = current_date.year if current_date.month < 12 else current_date.year + 1

                    # Find last day of next month
                    if next_month == 12:
                        last_day = date(next_year, next_month, 31)
                    else:
                        last_day = date(next_year, next_month + 1, 1) - timedelta(days=1)

                    next_date = last_day

        elif frequency == "quarterly":
            # Add 3 months
            next_month = current_date.month + 3
            next_year = current_date.year

            while next_month > 12:
                next_month -= 12
                next_year += 1

            try:
                next_date = current_date.replace(year=next_year, month=next_month)
            except ValueError:
                # Handle month-end dates
                if next_month == 12:
                    last_day = date(next_year, next_month, 31)
                else:
                    last_day = date(next_year, next_month + 1, 1) - timedelta(days=1)
                next_date = last_day

        elif frequency == "yearly":
            try:
                next_date = current_date.replace(year=current_date.year + 1)
            except ValueError:
                # Handle leap year Feb 29
                next_date = current_date.replace(year=current_date.year + 1, day=28)
        else:
            # Default to monthly
            next_date = (
                current_date.replace(month=current_date.month + 1)
                if current_date.month < 12
                else current_date.replace(year=current_date.year + 1, month=1)
            )

        # Ensure next date is a banking day
        next_banking_day = get_next_banking_day(next_date.strftime("%Y-%m-%d"))
        collection_dates.append(next_banking_day)
        current_date = getdate(next_banking_day)

    return collection_dates


def get_banking_day_info(check_date: str) -> dict:
    """
    Get detailed information about a specific date's banking status

    Args:
        check_date: Date to check

    Returns:
        Detailed banking day information
    """
    try:
        date_obj = getdate(check_date)
        is_banking_day = is_dutch_banking_day(check_date)

        info = {
            "date": check_date,
            "is_banking_day": is_banking_day,
            "weekday": date_obj.strftime("%A"),
            "weekday_number": date_obj.weekday(),
        }

        if not is_banking_day:
            if date_obj.weekday() >= 5:
                info["reason"] = "Weekend"
            else:
                holidays = get_dutch_bank_holidays(date_obj.year)
                if date_obj in holidays:
                    info["reason"] = "Bank Holiday"
                    # Identify specific holiday
                    holiday_names = {
                        f"{date_obj.year}-01-01": "New Year's Day",
                        f"{date_obj.year}-04-27": "King's Day",
                        f"{date_obj.year}-04-26": "King's Day (moved from Sunday)",
                        f"{date_obj.year}-05-05": "Liberation Day",
                        f"{date_obj.year}-12-25": "Christmas Day",
                        f"{date_obj.year}-12-26": "Boxing Day",
                    }

                    # Check Easter-related holidays
                    easter = calculate_easter(date_obj.year)
                    easter_holidays = {
                        (easter - timedelta(days=2)).strftime("%Y-%m-%d"): "Good Friday",
                        (easter + timedelta(days=1)).strftime("%Y-%m-%d"): "Easter Monday",
                        (easter + timedelta(days=39)).strftime("%Y-%m-%d"): "Ascension Day",
                        (easter + timedelta(days=50)).strftime("%Y-%m-%d"): "Whit Monday",
                    }

                    holiday_names.update(easter_holidays)
                    info["holiday_name"] = holiday_names.get(check_date, "Bank Holiday")
                else:
                    info["reason"] = "Unknown"

            # Suggest next banking day
            info["next_banking_day"] = get_next_banking_day(check_date)

        return info

    except Exception as e:
        return {"date": check_date, "error": str(e), "is_banking_day": False}
