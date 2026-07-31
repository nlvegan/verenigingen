# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Pure functions for billing period and invoice date calculations.
Extracted from MembershipDuesSchedule to reduce complexity and improve testability.
"""

from datetime import date, timedelta

import frappe
from frappe.utils import add_days, add_months, add_years, getdate, today


def calculate_next_invoice_date(
    billing_frequency: str,
    from_date=None,
    custom_frequency_number: int = None,
    custom_frequency_unit: str = None,
) -> date:
    """
    Calculate next billing date based on frequency.

    Args:
        billing_frequency: One of Daily, Weekly, Monthly, Quarterly, Semi-Annual, Annual, Custom
        from_date: Starting date (defaults to today if not provided)
        custom_frequency_number: Number of units for custom frequency
        custom_frequency_unit: Unit for custom frequency (Days, Weeks, Months, Years)

    Returns:
        Next invoice date as a date object
    """
    if not from_date:
        from_date = today()

    from_date = getdate(from_date)

    if billing_frequency == "Daily":
        return add_days(from_date, 1)
    elif billing_frequency == "Weekly":
        return add_days(from_date, 7)
    elif billing_frequency == "Monthly":
        return add_months(from_date, 1)
    elif billing_frequency == "Quarterly":
        return add_months(from_date, 3)
    elif billing_frequency == "Semi-Annual":
        return add_months(from_date, 6)
    elif billing_frequency == "Annual":
        return add_years(from_date, 1)
    elif billing_frequency == "Custom":
        # Use custom frequency settings with validation
        if not custom_frequency_number or custom_frequency_number < 1:
            custom_frequency_number = 1  # Safe default

        if not custom_frequency_unit:
            custom_frequency_unit = "Months"  # Safe default

        if custom_frequency_unit == "Days":
            return add_days(from_date, custom_frequency_number)
        elif custom_frequency_unit == "Weeks":
            return add_days(from_date, custom_frequency_number * 7)
        elif custom_frequency_unit == "Months":
            return add_months(from_date, custom_frequency_number)
        elif custom_frequency_unit == "Years":
            return add_years(from_date, custom_frequency_number)
        else:
            # Fallback to monthly if unit is invalid
            return add_months(from_date, 1)
    else:
        # Unknown frequency - default to monthly
        return add_months(from_date, 1)


def calculate_billing_period(
    billing_frequency: str,
    invoice_date,
    custom_frequency_number: int = None,
    custom_frequency_unit: str = None,
) -> tuple[date, date]:
    """
    Calculate the billing period start and end dates for a given invoice date.

    Args:
        billing_frequency: One of Daily, Weekly, Monthly, Quarterly, Semi-Annual, Annual, Custom
        invoice_date: Date for which to calculate the billing period
        custom_frequency_number: Number of units for custom frequency
        custom_frequency_unit: Unit for custom frequency (Days, Weeks, Months, Years)

    Returns:
        Tuple of (period_start, period_end) as date objects
    """
    invoice_date = getdate(invoice_date)

    if billing_frequency == "Daily":
        # For daily billing, the period is just the single day
        return invoice_date, invoice_date

    elif billing_frequency == "Weekly":
        # Weekly period: Monday to Sunday
        days_since_monday = invoice_date.weekday()
        period_start = add_days(invoice_date, -days_since_monday)
        period_end = add_days(period_start, 6)
        return period_start, period_end

    elif billing_frequency == "Monthly":
        # Monthly period: 1st to last day of month
        period_start = invoice_date.replace(day=1)
        # Get last day of month
        if invoice_date.month == 12:
            next_month = invoice_date.replace(year=invoice_date.year + 1, month=1, day=1)
        else:
            next_month = invoice_date.replace(month=invoice_date.month + 1, day=1)
        period_end = add_days(next_month, -1)
        return period_start, period_end

    elif billing_frequency == "Quarterly":
        # Quarterly periods: Q1 (Jan-Mar), Q2 (Apr-Jun), Q3 (Jul-Sep), Q4 (Oct-Dec)
        quarter = (invoice_date.month - 1) // 3 + 1
        period_start = invoice_date.replace(month=(quarter - 1) * 3 + 1, day=1)
        period_end_month = quarter * 3
        if period_end_month == 12:
            period_end = invoice_date.replace(month=12, day=31)
        else:
            next_quarter = invoice_date.replace(month=period_end_month + 1, day=1)
            period_end = add_days(next_quarter, -1)
        return period_start, period_end

    elif billing_frequency == "Semi-Annual":
        # Semi-annual: H1 (Jan-Jun), H2 (Jul-Dec)
        if invoice_date.month <= 6:
            period_start = invoice_date.replace(month=1, day=1)
            period_end = invoice_date.replace(month=6, day=30)
        else:
            period_start = invoice_date.replace(month=7, day=1)
            period_end = invoice_date.replace(month=12, day=31)
        return period_start, period_end

    elif billing_frequency == "Annual":
        # Annual period: Jan 1 to Dec 31
        period_start = invoice_date.replace(month=1, day=1)
        period_end = invoice_date.replace(month=12, day=31)
        return period_start, period_end

    elif billing_frequency == "Custom":
        # For custom frequency, calculate period based on custom settings
        if not custom_frequency_number or custom_frequency_number < 1:
            custom_frequency_number = 1

        if not custom_frequency_unit:
            custom_frequency_unit = "Months"

        # Calculate period end based on frequency
        if custom_frequency_unit == "Days":
            period_start = invoice_date
            period_end = add_days(invoice_date, custom_frequency_number - 1)
        elif custom_frequency_unit == "Weeks":
            # Week starts on Monday
            days_since_monday = invoice_date.weekday()
            period_start = add_days(invoice_date, -days_since_monday)
            period_end = add_days(period_start, custom_frequency_number * 7 - 1)
        elif custom_frequency_unit == "Months":
            period_start = invoice_date.replace(day=1)
            end_month = add_months(period_start, custom_frequency_number)
            period_end = add_days(end_month, -1)
        elif custom_frequency_unit == "Years":
            period_start = invoice_date.replace(month=1, day=1)
            period_end = invoice_date.replace(
                year=invoice_date.year + custom_frequency_number - 1, month=12, day=31
            )
        else:
            # Fallback to monthly
            period_start = invoice_date.replace(day=1)
            end_month = add_months(period_start, 1)
            period_end = add_days(end_month, -1)

        return period_start, period_end

    else:
        # Unknown frequency - default to monthly
        period_start = invoice_date.replace(day=1)
        if invoice_date.month == 12:
            next_month = invoice_date.replace(year=invoice_date.year + 1, month=1, day=1)
        else:
            next_month = invoice_date.replace(month=invoice_date.month + 1, day=1)
        period_end = add_days(next_month, -1)
        return period_start, period_end


def calculate_coverage_end(
    billing_frequency: str,
    coverage_start,
    custom_frequency_number: int = None,
    custom_frequency_unit: str = None,
) -> date:
    """
    Calculate the end of a billing period that RUNS FROM coverage_start.

    Distinct from calculate_billing_period(), which returns the calendar period
    surrounding a date. This one runs a full period forward from a given start, which
    is how the coverage sequence is actually built: each period begins the day after
    the previous one ended.

    Args:
        billing_frequency: Daily, Weekly, Monthly, Quarterly, Semi-Annual, Annual or Custom
        coverage_start: First day of the period
        custom_frequency_number: Period length for Custom frequency
        custom_frequency_unit: Days, Weeks, Months or Years for Custom frequency

    Returns:
        date: Last day of the period (inclusive)
    """
    coverage_start = getdate(coverage_start)

    if billing_frequency == "Daily":
        return coverage_start
    elif billing_frequency == "Weekly":
        return add_days(coverage_start, 6)  # 7 days total
    elif billing_frequency == "Monthly":
        return add_days(add_months(coverage_start, 1), -1)
    elif billing_frequency == "Quarterly":
        return add_days(add_months(coverage_start, 3), -1)
    elif billing_frequency == "Semi-Annual":
        return add_days(add_months(coverage_start, 6), -1)
    elif billing_frequency == "Annual":
        return add_days(add_months(coverage_start, 12), -1)
    elif billing_frequency == "Custom":
        if not custom_frequency_number or custom_frequency_number < 1:
            return add_days(add_months(coverage_start, 1), -1)  # Default to monthly

        if custom_frequency_unit == "Days":
            return add_days(coverage_start, custom_frequency_number - 1)
        elif custom_frequency_unit == "Weeks":
            return add_days(coverage_start, custom_frequency_number * 7 - 1)
        elif custom_frequency_unit == "Months":
            return add_days(add_months(coverage_start, custom_frequency_number), -1)
        elif custom_frequency_unit == "Years":
            return add_days(add_months(coverage_start, custom_frequency_number * 12), -1)
        else:
            return add_days(add_months(coverage_start, 1), -1)  # Default to monthly
    else:
        # Unknown frequency - fallback to monthly
        return add_days(add_months(coverage_start, 1), -1)


def derive_coverage_from_invoice_data(
    posting_date, last_invoice_date=None, next_invoice_date=None, billing_frequency=None
):
    """
    Derive coverage period from invoice and schedule dates when explicit coverage dates are missing.

    Includes comprehensive validation to prevent silent failures and ensure reliable results.

    Args:
        posting_date: Invoice posting date (required)
        last_invoice_date: Previous invoice date from schedule (optional)
        next_invoice_date: Next invoice date from schedule (optional)
        billing_frequency: Billing frequency for period calculation (optional)

    Returns:
        tuple: (start_date, end_date) for the coverage period

    Raises:
        ValueError: If unable to derive valid coverage dates
    """
    # Input validation
    if not posting_date:
        raise ValueError("posting_date is required for coverage derivation")

    try:
        posting_date = getdate(posting_date)
    except Exception as e:
        raise ValueError(f"Invalid posting_date format: {posting_date} - {str(e)}")

    # Validate billing frequency
    valid_frequencies = ["Daily", "Weekly", "Monthly", "Quarterly", "Semi-Annual", "Annual", "Custom"]
    if billing_frequency and billing_frequency not in valid_frequencies:
        frappe.log_error(
            f"Unknown billing frequency '{billing_frequency}' for coverage derivation, using fallback logic",
            "Coverage Derivation Warning",
        )
        billing_frequency = None

    # Determine coverage start date with validation
    coverage_start = None
    if last_invoice_date:
        try:
            last_date = getdate(last_invoice_date)
            coverage_start = add_days(last_date, 1)

            # Sanity check: coverage start shouldn't be too far in the future from posting date
            if coverage_start > add_days(posting_date, 365):
                frappe.log_error(
                    f"Suspicious coverage start derivation: last_invoice_date={last_invoice_date}, "
                    f"posting_date={posting_date}, derived start={coverage_start}. Using posting date instead.",
                    "Coverage Derivation Warning",
                )
                coverage_start = posting_date

            # Gap detection: if coverage would start too far in the past, reset forward to posting date
            gap_days = (posting_date - coverage_start).days
            max_gap_days = 30  # Configurable threshold

            if gap_days > max_gap_days:
                frappe.log_error(
                    f"Large coverage gap detected: {gap_days} days between last invoice coverage "
                    f"({last_invoice_date}) and posting date ({posting_date}). "
                    f"Resetting forward - coverage will start from posting date.",
                    "Coverage Gap Reset",
                )
                coverage_start = posting_date
        except Exception as e:
            frappe.log_error(
                f"Failed to parse last_invoice_date '{last_invoice_date}': {str(e)}. Using posting date.",
                "Coverage Derivation Warning",
            )
            coverage_start = posting_date
    else:
        # Fallback: coverage starts at posting date
        coverage_start = posting_date

    # Calculate coverage end based on billing frequency with validation
    coverage_end = None

    try:
        if billing_frequency == "Daily":
            coverage_end = coverage_start
        elif billing_frequency == "Weekly":
            coverage_end = add_days(coverage_start, 6)
        elif billing_frequency == "Monthly":
            coverage_end = add_days(add_months(coverage_start, 1), -1)
        elif billing_frequency == "Quarterly":
            coverage_end = add_days(add_months(coverage_start, 3), -1)
        elif billing_frequency == "Semi-Annual":
            coverage_end = add_days(add_months(coverage_start, 6), -1)
        elif billing_frequency == "Annual":
            coverage_end = add_days(add_months(coverage_start, 12), -1)
        else:
            # Unknown frequency - use next_invoice_date if available, otherwise assume monthly
            if next_invoice_date:
                try:
                    next_date = getdate(next_invoice_date)
                    coverage_end = add_days(next_date, -1)

                    # Validation: next invoice date should be after coverage start
                    if coverage_end <= coverage_start:
                        frappe.log_error(
                            f"Invalid coverage period derived from next_invoice_date: "
                            f"start={coverage_start}, end={coverage_end}. Using monthly fallback.",
                            "Coverage Derivation Warning",
                        )
                        coverage_end = add_days(add_months(coverage_start, 1), -1)
                except Exception as e:
                    frappe.log_error(
                        f"Failed to parse next_invoice_date '{next_invoice_date}': {str(e)}. Using monthly fallback.",
                        "Coverage Derivation Warning",
                    )
                    coverage_end = add_days(add_months(coverage_start, 1), -1)
            else:
                # Final fallback: assume monthly
                coverage_end = add_days(add_months(coverage_start, 1), -1)
    except Exception as e:
        frappe.log_error(
            f"Error calculating coverage end for frequency '{billing_frequency}': {str(e)}. Using monthly fallback.",
            "Coverage Derivation Error",
        )
        coverage_end = add_days(add_months(coverage_start, 1), -1)

    # Final validation
    if not coverage_start or not coverage_end:
        raise ValueError(f"Failed to derive valid coverage dates: start={coverage_start}, end={coverage_end}")

    if coverage_end <= coverage_start:
        raise ValueError(
            f"Invalid coverage period: end date ({coverage_end}) must be after start date ({coverage_start})"
        )

    # Sanity check: coverage period shouldn't exceed 2 years
    if (coverage_end - coverage_start) > timedelta(days=730):
        frappe.log_error(
            f"Suspiciously long coverage period derived: {coverage_start} to {coverage_end} "
            f"({(coverage_end - coverage_start).days} days). This may indicate a data issue.",
            "Coverage Derivation Warning",
        )

    return coverage_start, coverage_end
