# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
CoverageCalculator Service - Consolidated coverage period calculations.

Extracts all date/coverage calculation logic from MembershipDuesSchedule god object.
Consolidates existing billing_period_calculator.py utilities with DocType methods.
"""

from datetime import date, timedelta
from typing import Any, Dict, Optional

import frappe
from frappe.utils import add_days, add_months, getdate, today


class CoveragePeriodResult:
    """
    Result object for coverage period calculations.

    Provides validation and metadata about how the coverage period was calculated.
    """

    def __init__(self, start_date: date, end_date: date, calculation_method: str, **metadata: Any):
        """
        Initialize coverage period result.

        Args:
            start_date: Coverage period start date
            end_date: Coverage period end date
            calculation_method: How period was calculated ("sequential", "date_based", "first_invoice")
            **metadata: Additional calculation metadata (previous_coverage_end, force_date, etc.)
        """
        self.start_date = start_date
        self.end_date = end_date
        self.calculation_method = calculation_method
        self.metadata = metadata

    def is_valid(self) -> bool:
        """
        Validate that coverage period is logically sound.

        Returns:
            bool: True if period is valid, False otherwise
        """
        if not self.start_date or not self.end_date:
            return False
        if self.start_date > self.end_date:
            return False
        return True

    def __repr__(self):
        return (
            f"CoveragePeriodResult(start={self.start_date}, end={self.end_date}, "
            f"method={self.calculation_method})"
        )


class CoverageCalculator:
    """
    Service for calculating coverage periods and invoice dates for membership billing.

    Consolidates all date/period calculation logic into a single, testable service.
    Stateless - all context passed as parameters or extracted from schedule doc at init.

    Example:
        calculator = CoverageCalculator(schedule_doc)
        result = calculator.calculate_next_coverage_period(member_doc)
        if result.is_valid():
            start, end = result.start_date, result.end_date
    """

    def __init__(self, schedule_doc: Any):
        """
        Initialize calculator with schedule context.

        Args:
            schedule_doc: MembershipDuesSchedule document (for accessing billing frequency fields)
        """
        self.schedule_name = schedule_doc.name
        self.billing_frequency = schedule_doc.billing_frequency
        self.custom_frequency_number = getattr(schedule_doc, "custom_frequency_number", None)
        self.custom_frequency_unit = getattr(schedule_doc, "custom_frequency_unit", None)
        self.member_name = schedule_doc.member
        self.next_invoice_date = getattr(schedule_doc, "next_invoice_date", None)

    # ========== Primary Public API ==========

    def calculate_next_coverage_period(
        self, member_doc: Any, force_date: Optional[date] = None, use_sequential: Optional[bool] = None
    ) -> CoveragePeriodResult:
        """
        Calculate the next coverage period for invoice generation.

        Uses sequential logic (builds on previous coverage) by default,
        falls back to date-based calculation for first invoice or when sequential is disabled.

        Args:
            member_doc: Member document (for customer lookup)
            force_date: Override date for testing/manual generation
            use_sequential: Override sequential setting (None = use global setting)

        Returns:
            CoveragePeriodResult with start_date, end_date, calculation metadata
        """
        # Determine if sequential coverage is enabled
        if use_sequential is None:
            settings = frappe.get_single("Verenigingen Settings")
            use_sequential = getattr(settings, "enable_sequential_coverage", True)

        metadata = {
            "use_sequential": use_sequential,
            "force_date": force_date,
        }

        # Sequential logic: Build on previous coverage
        if use_sequential:
            latest_coverage_end = self.get_latest_coverage_end_date(member_doc)
            metadata["previous_coverage_end"] = latest_coverage_end

            if latest_coverage_end:
                # Start the day after previous coverage ended
                coverage_start = add_days(latest_coverage_end, 1)
                calculation_method = "sequential"
            else:
                # First invoice: Use force date or today
                coverage_start = getdate(force_date or today())
                calculation_method = "first_invoice"
        else:
            # Fallback to date-based calculation
            calculation_method = "date_based"
            coverage_start, coverage_end = self.calculate_billing_period(
                self.billing_frequency,
                force_date or today(),
                self.custom_frequency_number,
                self.custom_frequency_unit,
            )
            return CoveragePeriodResult(coverage_start, coverage_end, calculation_method, **metadata)

        # Calculate end date based on billing frequency
        coverage_end = self._calculate_coverage_end(coverage_start)

        # Validation: Ensure coverage dates are valid
        if not coverage_start or not coverage_end:
            metadata["error"] = f"Coverage calculation failed: start={coverage_start}, end={coverage_end}"
            return CoveragePeriodResult(None, None, calculation_method, **metadata)

        # For daily billing, start and end can be the same day; otherwise start must be before end
        if getdate(coverage_start) > getdate(coverage_end):
            metadata[
                "error"
            ] = f"Invalid coverage period: start date {coverage_start} must not be after end date {coverage_end}"
            return CoveragePeriodResult(None, None, calculation_method, **metadata)

        if getdate(coverage_start) == getdate(coverage_end) and self.billing_frequency != "Daily":
            metadata["error"] = (
                f"Invalid coverage period: start date {coverage_start} must be before end date {coverage_end} "
                f"for {self.billing_frequency} billing"
            )
            return CoveragePeriodResult(None, None, calculation_method, **metadata)

        return CoveragePeriodResult(coverage_start, coverage_end, calculation_method, **metadata)

    def should_generate_invoice_for_cutoff(
        self, cutoff_date: date, latest_coverage_end: Optional[date] = None
    ) -> bool:
        """
        Determine if invoice generation is needed to cover through cutoff_date.

        Prioritizes actual coverage data from submitted invoices over the next_invoice_date
        tracking field, which can become stale after invoice cancellations or manual adjustments.

        Args:
            cutoff_date: Target date that should be covered by invoices
            latest_coverage_end: Latest coverage end (if already known, avoids re-query)

        Returns:
            bool: True if invoice generation is needed
        """
        cutoff_date = getdate(cutoff_date)

        # Query for latest coverage if not provided
        if latest_coverage_end is None:
            latest_coverage_end = self.get_latest_coverage_end_date(None)

        # If we have actual coverage data, use it exclusively
        # This prevents stale next_invoice_date from affecting decisions
        if latest_coverage_end is not None:
            return latest_coverage_end < cutoff_date

        # No coverage exists yet - use next_invoice_date as signal for first invoice
        # Generate if no next_invoice_date set, or if it's overdue
        return not self.next_invoice_date or getdate(self.next_invoice_date) < getdate(today())

    # ========== Data Access Methods ==========

    def get_latest_coverage_end_date(self, member_doc: Optional[Any]) -> Optional[date]:
        """
        Query database for the latest coverage end date from submitted invoices.

        CRITICAL: Always queries the database to find the TRUE latest invoice,
        since the tracked field may be stale if invoices were created outside
        the normal flow.

        Args:
            member_doc: Member document (for customer lookup). Can be None if using self.member_name.

        Returns:
            date: Latest coverage end date, or None if no invoices exist
        """
        # Get member if not provided
        if member_doc is None:
            if not self.member_name:
                return None
            member_doc = frappe.get_doc("Member", self.member_name)

        if not member_doc.customer:
            return None

        # Query for the absolute latest submitted invoice with coverage dates
        latest_invoice = frappe.db.sql(
            """
            SELECT custom_coverage_end_date
            FROM `tabSales Invoice`
            WHERE customer = %s
            AND docstatus = 1
            AND custom_coverage_end_date IS NOT NULL
            ORDER BY custom_coverage_end_date DESC
            LIMIT 1
        """,
            member_doc.customer,
            as_dict=True,
        )

        if latest_invoice:
            return latest_invoice[0].custom_coverage_end_date
        return None

    # ========== Static Utility Methods ==========

    @staticmethod
    def calculate_billing_period(
        billing_frequency: str,
        invoice_date,
        custom_frequency_number: Optional[int] = None,
        custom_frequency_unit: Optional[str] = None,
    ) -> tuple[date, date]:
        """
        Calculate billing period for a given invoice date.

        Delegates to billing_period_calculator utility for actual calculation.

        Args:
            billing_frequency: One of Daily, Weekly, Monthly, Quarterly, Semi-Annual, Annual, Custom
            invoice_date: Date for which to calculate the billing period
            custom_frequency_number: Number of units for custom frequency
            custom_frequency_unit: Unit for custom frequency (Days, Weeks, Months, Years)

        Returns:
            tuple: (period_start, period_end) as date objects
        """
        from verenigingen.utils.billing_period_calculator import calculate_billing_period

        return calculate_billing_period(
            billing_frequency, invoice_date, custom_frequency_number, custom_frequency_unit
        )

    @staticmethod
    def calculate_cutoff_date_for_period() -> date:
        """
        Calculate the cutoff date for invoice generation based on Verenigingen Settings.

        Reads from Verenigingen Settings billing_cutoff_frequency to determine
        how far ahead to generate invoices (monthly, quarterly, yearly).

        Returns:
            date: The cutoff date through which invoices should provide coverage
        """
        from datetime import date as date_obj

        from frappe.utils import add_days, getdate, today

        settings = frappe.get_single("Verenigingen Settings")
        cutoff_frequency = getattr(settings, "billing_cutoff_frequency", "Monthly")

        today_date = getdate(today())

        # DEBUG LOGGING
        frappe.logger().info(
            f"[CoverageCalculator] today_date={today_date}, cutoff_frequency={cutoff_frequency}"
        )

        if cutoff_frequency == "Monthly":
            # End of current month
            if today_date.month == 12:
                next_month = today_date.replace(year=today_date.year + 1, month=1, day=1)
            else:
                next_month = today_date.replace(month=today_date.month + 1, day=1)
            return add_days(next_month, -1)

        elif cutoff_frequency == "Quarterly":
            # End of current quarter based on book year
            book_year_start_month = getattr(settings, "book_year_start_month", 1)

            # Calculate which quarter we're in based on book year
            months_since_book_start = (today_date.month - book_year_start_month) % 12
            current_quarter = (months_since_book_start // 3) + 1

            # Calculate end month of current quarter
            quarter_end_month = ((current_quarter * 3 - 1) + book_year_start_month - 1) % 12 + 1

            # Determine the year for the quarter end
            # If quarter_end_month >= today's month, we're still in this year's quarter
            # If quarter_end_month < today's month, the quarter must have wrapped to next year
            if quarter_end_month >= today_date.month:
                quarter_end_year = today_date.year
            else:
                # Quarter wraps to next year (e.g., book year starts in April, we're in Jan-Mar)
                quarter_end_year = today_date.year + 1

            # Calculate last day of quarter end month
            import calendar

            last_day_of_month = calendar.monthrange(quarter_end_year, quarter_end_month)[1]
            return date_obj(quarter_end_year, quarter_end_month, last_day_of_month)

        elif cutoff_frequency == "Yearly":
            # End of current book year
            book_year_end_month = getattr(settings, "book_year_end_month", 12)
            book_year_end_day = getattr(settings, "book_year_end_day", 31)

            frappe.logger().info(
                f"[CoverageCalculator] Yearly: book_year_end_month={book_year_end_month}, "
                f"book_year_end_day={book_year_end_day}, today={today_date}"
            )

            if today_date.month < book_year_end_month or (
                today_date.month == book_year_end_month and today_date.day <= book_year_end_day
            ):
                # Still in current book year
                end_year = today_date.year
            else:
                # In next book year
                end_year = today_date.year + 1

            frappe.logger().info(f"[CoverageCalculator] end_year={end_year}")

            # Calculate last day of book year end month
            if book_year_end_month == 12:
                # December - use actual last day or day 31
                import calendar

                last_day = min(book_year_end_day, calendar.monthrange(end_year, 12)[1])
                result = date_obj(end_year, 12, last_day)
                frappe.logger().info(f"[CoverageCalculator] Returning Dec result: {result}")
                return result
            else:
                # Other month - calculate last day properly
                import calendar

                last_day = min(book_year_end_day, calendar.monthrange(end_year, book_year_end_month)[1])
                result = date_obj(end_year, book_year_end_month, last_day)
                frappe.logger().info(f"[CoverageCalculator] Returning other month result: {result}")
                return result

        else:
            # Default to end of current month
            if today_date.month == 12:
                next_month = today_date.replace(year=today_date.year + 1, month=1, day=1)
            else:
                next_month = today_date.replace(month=today_date.month + 1, day=1)
            return add_days(next_month, -1)

    @staticmethod
    def derive_coverage_from_invoice_data(
        posting_date,
        last_invoice_date: Optional[date] = None,
        next_invoice_date: Optional[date] = None,
        billing_frequency: Optional[str] = None,
    ) -> tuple[date, date]:
        """
        Derive coverage period from invoice data when explicit coverage dates are missing.

        Used for legacy invoices that don't have custom_coverage_start_date/end_date fields.
        Delegates to billing_period_calculator utility for actual derivation.

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
        from verenigingen.utils.billing_period_calculator import derive_coverage_from_invoice_data

        return derive_coverage_from_invoice_data(
            posting_date, last_invoice_date, next_invoice_date, billing_frequency
        )

    # ========== Internal Helper Methods ==========

    def _calculate_coverage_end(self, coverage_start: date) -> date:
        """
        Calculate coverage end date based on billing frequency.

        Internal helper for calculate_next_coverage_period().

        Args:
            coverage_start: Coverage period start date

        Returns:
            date: Coverage period end date
        """
        if self.billing_frequency == "Daily":
            return coverage_start
        elif self.billing_frequency == "Weekly":
            return add_days(coverage_start, 6)  # 7 days total
        elif self.billing_frequency == "Monthly":
            return add_days(add_months(coverage_start, 1), -1)
        elif self.billing_frequency == "Quarterly":
            return add_days(add_months(coverage_start, 3), -1)
        elif self.billing_frequency == "Semi-Annual":
            return add_days(add_months(coverage_start, 6), -1)
        elif self.billing_frequency == "Annual":
            return add_days(add_months(coverage_start, 12), -1)
        elif self.billing_frequency == "Custom":
            # Use custom frequency settings
            if not self.custom_frequency_number or self.custom_frequency_number < 1:
                return add_days(add_months(coverage_start, 1), -1)  # Default to monthly

            if self.custom_frequency_unit == "Days":
                return add_days(coverage_start, self.custom_frequency_number - 1)
            elif self.custom_frequency_unit == "Weeks":
                return add_days(coverage_start, self.custom_frequency_number * 7 - 1)
            elif self.custom_frequency_unit == "Months":
                return add_days(add_months(coverage_start, self.custom_frequency_number), -1)
            elif self.custom_frequency_unit == "Years":
                return add_days(add_months(coverage_start, self.custom_frequency_number * 12), -1)
            else:
                return add_days(add_months(coverage_start, 1), -1)  # Default to monthly
        else:
            # Unknown frequency - fallback to monthly
            return add_days(add_months(coverage_start, 1), -1)
