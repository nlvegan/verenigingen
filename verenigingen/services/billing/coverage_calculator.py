# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
CoverageCalculator Service - Consolidated coverage period calculations.

Extracts all date/coverage calculation logic from MembershipDuesSchedule god object.
Consolidates existing billing_period_calculator.py utilities with DocType methods.

Architecture:
    - Inherits from StatelessService for consistent logging, metrics, error handling
    - Returns OperationResult[CoveragePeriod] for fallible operations
    - Pure CoveragePeriod dataclass for domain data
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, Optional

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.utils.operation_result import OperationResult


@dataclass
class CoveragePeriod:
    """
    Pure data structure for coverage period information.

    Attributes:
        start_date: Coverage period start date
        end_date: Coverage period end date
        calculation_method: How period was calculated ("sequential", "date_based", "first_invoice")
        metadata: Additional calculation context (previous_coverage_end, force_date, etc.)
    """

    start_date: date
    end_date: date
    calculation_method: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            f"CoveragePeriod(start={self.start_date}, end={self.end_date}, "
            f"method={self.calculation_method})"
        )


class CoverageCalculator(StatelessService):
    """
    Service for calculating coverage periods and invoice dates for membership billing.

    Inherits from StatelessService for consistent logging, metrics, and error handling.
    Consolidates all date/period calculation logic into a single, testable service.

    Example:
        calculator = CoverageCalculator(schedule_doc)
        result = calculator.calculate_next_coverage_period(member_doc)
        if result.success:
            period = result.data
            start, end = period.start_date, period.end_date
    """

    def __init__(self, schedule_doc: Optional[Any] = None):
        """
        Initialize calculator with optional schedule context.

        Args:
            schedule_doc: MembershipDuesSchedule document (for accessing billing frequency fields).
                         Optional for utility method access (calculate_billing_period, etc.)
        """
        super().__init__(service_name="CoverageCalculator")
        if schedule_doc is not None:
            self.schedule_name = schedule_doc.name
            self.billing_frequency = schedule_doc.billing_frequency
            self.custom_frequency_number = getattr(schedule_doc, "custom_frequency_number", None)
            self.custom_frequency_unit = getattr(schedule_doc, "custom_frequency_unit", None)
            self.member_name = schedule_doc.member
            self.next_invoice_date = getattr(schedule_doc, "next_invoice_date", None)
        else:
            # Utility-only mode - schedule-specific methods will fail
            self.schedule_name = None
            self.billing_frequency = None
            self.custom_frequency_number = None
            self.custom_frequency_unit = None
            self.member_name = None
            self.next_invoice_date = None

    # ========== Primary Public API ==========

    def calculate_next_coverage_period(
        self, member_doc: Any, force_date: Optional[date] = None, use_sequential: Optional[bool] = None
    ) -> OperationResult[CoveragePeriod]:
        """
        Calculate the next coverage period for invoice generation.

        Uses sequential logic (builds on previous coverage) by default,
        falls back to date-based calculation for first invoice or when sequential is disabled.

        Args:
            member_doc: Member document (for customer lookup)
            force_date: Override date for testing/manual generation
            use_sequential: Override sequential setting (None = use global setting)

        Returns:
            OperationResult[CoveragePeriod] with period data on success, error details on failure
        """

        def _calculate():
            # Determine if sequential coverage is enabled
            seq = use_sequential
            if seq is None:
                settings = frappe.get_single("Verenigingen Settings")
                seq = getattr(settings, "enable_sequential_coverage", True)

            metadata = {
                "use_sequential": seq,
                "force_date": force_date,
            }

            # Sequential logic: Build on previous coverage
            if seq:
                latest_coverage_end = self.get_latest_coverage_end_date(member_doc)
                metadata["previous_coverage_end"] = latest_coverage_end

                if latest_coverage_end:
                    # Start the day after previous coverage ended
                    coverage_start = add_days(latest_coverage_end, 1)
                    calculation_method = "sequential"
                    # Calculate end date based on billing frequency from this start
                    coverage_end = self._calculate_coverage_end(coverage_start)
                else:
                    # First invoice: run a full billing period from the member's join date.
                    # Membership itself runs from start_date (Membership.set_renewal_date sets
                    # renewal_date = start_date + billing_period), and the sequential branch
                    # above rolls each later period off the previous coverage end, so the first
                    # period must roll too. Anchoring it to the surrounding calendar period
                    # instead produced a short first period that nothing prorates — the invoice
                    # generator always charges the full dues_rate — and, for a member joining on
                    # the period's last day, a zero-length period that threw and left them
                    # permanently un-invoiceable.
                    reference_date = getdate(force_date or today())
                    period_start = self.calculate_billing_period(
                        self.billing_frequency,
                        reference_date,
                        self.custom_frequency_number,
                        self.custom_frequency_unit,
                    )[0]

                    # Members who joined mid-period start from their membership start date so
                    # they do not pay for time before joining. With no membership on record the
                    # join date is unknown, so fall back to the calendar period start — for
                    # which _calculate_coverage_end reproduces the calendar period exactly.
                    membership_start = self._get_membership_start_date()
                    if membership_start and getdate(membership_start) > getdate(period_start):
                        coverage_start = getdate(membership_start)
                        metadata["membership_start_used"] = True
                    else:
                        coverage_start = period_start
                        metadata["membership_start_used"] = False

                    coverage_end = self._calculate_coverage_end(coverage_start)

                    calculation_method = "first_invoice"
                    metadata["reference_date"] = reference_date
                    metadata["period_start"] = period_start
                    metadata["membership_start"] = membership_start
            else:
                # Fallback to date-based calculation
                calculation_method = "date_based"
                coverage_start, coverage_end = self.calculate_billing_period(
                    self.billing_frequency,
                    force_date or today(),
                    self.custom_frequency_number,
                    self.custom_frequency_unit,
                )

            # Validation: Ensure coverage dates are valid
            if not coverage_start or not coverage_end:
                return OperationResult.fail(
                    f"Coverage calculation failed: start={coverage_start}, end={coverage_end}",
                    calculation_method=calculation_method,
                    **metadata,
                )

            # For daily billing, start and end can be the same day; otherwise start must be before end
            if getdate(coverage_start) > getdate(coverage_end):
                return OperationResult.fail(
                    f"Invalid coverage period: start date {coverage_start} must not be after end date {coverage_end}",
                    calculation_method=calculation_method,
                    **metadata,
                )

            if getdate(coverage_start) == getdate(coverage_end) and self.billing_frequency != "Daily":
                return OperationResult.fail(
                    f"Invalid coverage period: start date {coverage_start} must be before end date {coverage_end} "
                    f"for {self.billing_frequency} billing",
                    calculation_method=calculation_method,
                    **metadata,
                )

            period = CoveragePeriod(
                start_date=coverage_start,
                end_date=coverage_end,
                calculation_method=calculation_method,
                metadata=metadata,
            )
            return OperationResult.ok(period, **metadata)

        try:
            return self.execute_operation(_calculate)
        except Exception as e:
            self.handle_error(e, "calculate_next_coverage_period", raise_error=False)
            return OperationResult.fail(str(e))

    def should_generate_invoice_for_cutoff(
        self, cutoff_date: date, latest_coverage_end: Optional[date] = None
    ) -> bool:
        """
        Determine if invoice generation is needed to cover through cutoff_date.

        The logic is based solely on actual invoice coverage:
        - Query the latest coverage_end_date from submitted Sales Invoices
        - If coverage exists and extends to/past the effective cutoff: no invoice needed
        - If coverage exists but ends before it: invoice needed
        - If NO coverage exists (0 invoices): invoice needed (0% of period is covered)

        The cutoff is capped at one billing period ahead of today. billing_cutoff_frequency
        is a single global setting, so it can be coarser than an individual member's
        billing frequency - a Quarterly cutoff asks for a Monthly member to be covered
        through quarter end, i.e. three periods. Since the generator emits one invoice per
        schedule per run, that produced one extra invoice per run until coverage caught up,
        rather than either three at once or one per month. Capping keeps a coarser cutoff
        from over-billing short-frequency members, and is inert whenever the cutoff is at
        or finer than the member's own frequency (the normal configuration).

        Args:
            cutoff_date: Target date that should be covered by invoices (e.g., end of Q4)
            latest_coverage_end: Latest coverage end (if already known, avoids re-query)

        Returns:
            bool: True if invoice generation is needed to cover through the effective cutoff
        """
        cutoff_date = getdate(cutoff_date)

        # Query for latest coverage if not provided
        if latest_coverage_end is None:
            latest_coverage_end = self.get_latest_coverage_end_date(None)

        # If we have coverage, check if it extends to cutoff
        if latest_coverage_end is not None:
            effective_cutoff = min(cutoff_date, self._one_period_ahead_of_today())
            # Invoice needed if coverage ends before the effective cutoff date
            return getdate(latest_coverage_end) < effective_cutoff

        # No coverage exists (0 invoices) - member ALWAYS needs an invoice
        return True

    def _one_period_ahead_of_today(self) -> date:
        """
        The furthest coverage end this schedule may hold before further generation stops.

        Uses the same period arithmetic as the coverage sequence itself, so the cap can
        never disagree with the periods being generated.
        """
        if not self.billing_frequency:
            # Utility mode with no schedule - impose no cap.
            return date.max

        return self._calculate_coverage_end(getdate(today()))

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

    # ========== Utility Methods ==========

    def calculate_billing_period(
        self,
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
        from verenigingen.services.billing.billing_period_calculator import calculate_billing_period

        return calculate_billing_period(
            billing_frequency, invoice_date, custom_frequency_number, custom_frequency_unit
        )

    def calculate_cutoff_date_for_period(self) -> date:
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

        self.logger.debug(
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
            if quarter_end_month >= today_date.month:
                quarter_end_year = today_date.year
            else:
                quarter_end_year = today_date.year + 1

            # Calculate last day of quarter end month
            import calendar

            last_day_of_month = calendar.monthrange(quarter_end_year, quarter_end_month)[1]
            return date_obj(quarter_end_year, quarter_end_month, last_day_of_month)

        elif cutoff_frequency == "Yearly":
            # End of current book year
            book_year_end_month = getattr(settings, "book_year_end_month", 12)
            book_year_end_day = getattr(settings, "book_year_end_day", 31)

            self.logger.debug(
                f"[CoverageCalculator] Yearly: book_year_end_month={book_year_end_month}, "
                f"book_year_end_day={book_year_end_day}, today={today_date}"
            )

            if today_date.month < book_year_end_month or (
                today_date.month == book_year_end_month and today_date.day <= book_year_end_day
            ):
                end_year = today_date.year
            else:
                end_year = today_date.year + 1

            self.logger.debug(f"[CoverageCalculator] end_year={end_year}")

            # Calculate last day of book year end month
            import calendar

            if book_year_end_month == 12:
                last_day = min(book_year_end_day, calendar.monthrange(end_year, 12)[1])
                result = date_obj(end_year, 12, last_day)
                self.logger.debug(f"[CoverageCalculator] Returning Dec result: {result}")
                return result
            else:
                last_day = min(book_year_end_day, calendar.monthrange(end_year, book_year_end_month)[1])
                result = date_obj(end_year, book_year_end_month, last_day)
                self.logger.debug(f"[CoverageCalculator] Returning other month result: {result}")
                return result

        else:
            # Default to end of current month
            if today_date.month == 12:
                next_month = today_date.replace(year=today_date.year + 1, month=1, day=1)
            else:
                next_month = today_date.replace(month=today_date.month + 1, day=1)
            return add_days(next_month, -1)

    def derive_coverage_from_invoice_data(
        self,
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
        from verenigingen.services.billing.billing_period_calculator import derive_coverage_from_invoice_data

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
        from verenigingen.services.billing.billing_period_calculator import calculate_coverage_end

        return calculate_coverage_end(
            self.billing_frequency,
            coverage_start,
            self.custom_frequency_number,
            self.custom_frequency_unit,
        )

    def _get_membership_start_date(self) -> Optional[date]:
        """
        Get the start date of the member's active membership.

        Used for first invoice calculation to ensure members who joined mid-period
        don't pay for time before their membership started.

        Returns:
            date: Membership start date, or None if not found
        """
        if not self.member_name:
            return None

        # Query the active membership for this member. Ordered because a member with
        # more than one active membership would otherwise anchor their whole coverage
        # sequence on an arbitrary row; the earliest start is the one the sequence
        # actually began from.
        membership_start = frappe.db.get_value(
            "Membership",
            {"member": self.member_name, "status": "Active", "docstatus": 1},
            "start_date",
            order_by="start_date asc",
        )

        return getdate(membership_start) if membership_start else None


def get_coverage_calculator(schedule_doc: Optional[Any] = None) -> CoverageCalculator:
    """Get instance of CoverageCalculator.

    Args:
        schedule_doc: MembershipDuesSchedule document for schedule-specific operations.
                     Optional - pass None for utility methods only (calculate_billing_period, etc.)
    """
    return CoverageCalculator(schedule_doc)


def calculate_coverage_for_payment_date(
    member_name: str,
    payment_date: date,
) -> tuple[date, date]:
    """
    Calculate coverage dates for a payment based on member's billing configuration.

    This is the generalized, billing-frequency-aware replacement for the
    hardcoded quarterly logic in DuesPaymentProcessor.

    The billing FREQUENCY is resolved by priority hierarchy:
    1. Member's current_dues_schedule link field (if set and schedule is Active)
    2. Fallback query for any non-cancelled schedule for this member
    3. Ultimate fallback: billing_cutoff_frequency from Verenigingen Settings

    The PERIOD is then taken from the member's own coverage sequence, not the calendar
    - see _coverage_period_from_member_sequence. Coverage runs from the member's join
    date, so the calendar period is only the right answer for a member who happens to
    be calendar-aligned, or one with no sequence to anchor to.

    Args:
        member_name: Member document name
        payment_date: Date the payment was made

    Returns:
        tuple: (coverage_start, coverage_end) as date objects

    Example:
        # Monthly member who joined on the 3rd, paying 2024-05-15: the period is the
        # member's own, NOT the calendar month.
        >>> calculate_coverage_for_payment_date("MEM-001", date(2024, 5, 15))
        (date(2024, 5, 3), date(2024, 6, 2))

        # A member with no invoices and no membership on record falls back to the
        # calendar period for their frequency.
        >>> calculate_coverage_for_payment_date("MEM-002", date(2024, 5, 15))
        (date(2024, 4, 1), date(2024, 6, 30))
    """
    from frappe.utils import getdate

    payment_date = getdate(payment_date)

    billing_frequency = None
    custom_number = None
    custom_unit = None

    # Priority 1: Use Member's current_dues_schedule link field
    current_schedule_name = frappe.db.get_value("Member", member_name, "current_dues_schedule")

    if current_schedule_name:
        schedule = frappe.db.get_value(
            "Membership Dues Schedule",
            current_schedule_name,
            ["status", "billing_frequency", "custom_frequency_number", "custom_frequency_unit"],
            as_dict=True,
        )

        if schedule and schedule.status == "Active":
            billing_frequency = schedule.billing_frequency
            custom_number = schedule.custom_frequency_number
            custom_unit = schedule.custom_frequency_unit
            frappe.logger().debug(
                f"Using current_dues_schedule {current_schedule_name} "
                f"(billing_frequency={billing_frequency}) for member {member_name}"
            )

    # Priority 2: Fallback query for any non-cancelled schedule
    if not billing_frequency:
        schedule = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member_name, "status": ["!=", "Cancelled"]},
            ["billing_frequency", "custom_frequency_number", "custom_frequency_unit"],
            as_dict=True,
            order_by="creation desc",  # Most recent first
        )

        if schedule:
            billing_frequency = schedule.billing_frequency
            custom_number = schedule.custom_frequency_number
            custom_unit = schedule.custom_frequency_unit
            frappe.logger().debug(
                f"Using fallback schedule query (billing_frequency={billing_frequency}) "
                f"for member {member_name}"
            )

    # Priority 3: Ultimate fallback to settings
    if not billing_frequency:
        settings = frappe.get_single("Verenigingen Settings")
        # Default matches bulk_invoice_generation_service.calculate_cutoff_date and
        # www/dues_invoice_manager; this call site alone used to default to Quarterly,
        # so an unset setting made the payment matcher and the generator disagree.
        cutoff_freq = getattr(settings, "billing_cutoff_frequency", "Monthly")

        # Map cutoff frequency to billing frequency
        freq_map = {"Monthly": "Monthly", "Quarterly": "Quarterly", "Yearly": "Annual"}
        billing_frequency = freq_map.get(cutoff_freq, "Quarterly")
        frappe.logger().debug(
            f"Using settings fallback (billing_cutoff_frequency={cutoff_freq} -> "
            f"billing_frequency={billing_frequency}) for member {member_name}"
        )

    # Prefer the member's OWN coverage sequence over the calendar. Every consumer
    # compares this result to an invoice's custom_coverage_* for exact equality, and
    # periods run from the member's join date, so for anyone who joined mid-period the
    # calendar period matches no invoice at all. The create-invoice paths use these
    # same dates, so a calendar answer would also write invoices overlapping the
    # member's own sequence.
    anchored = _coverage_period_from_member_sequence(
        member_name, payment_date, billing_frequency, custom_number, custom_unit
    )
    if anchored:
        return anchored

    # No sequence to anchor to (no invoices and no membership start, or a payment
    # predating all coverage) - fall back to the calendar period.
    from verenigingen.services.billing.billing_period_calculator import calculate_billing_period

    coverage_start, coverage_end = calculate_billing_period(
        billing_frequency, payment_date, custom_number, custom_unit
    )

    return coverage_start, coverage_end


# A payment far outside the member's coverage sequence should not spin: bail out and
# let the caller fall back to the calendar period. Daily billing needs ~365 steps a
# year, so this only trips on genuinely nonsensical dates.
MAX_PERIOD_ROLL_STEPS = 10000


def _coverage_period_from_member_sequence(
    member_name: str,
    payment_date: date,
    billing_frequency: str,
    custom_number: Optional[int],
    custom_unit: Optional[str],
) -> Optional[tuple]:
    """
    Resolve the member's own billing period containing payment_date.

    Order of preference:
    1. An invoice whose coverage already contains payment_date - the period is then
       exactly what the consumers will compare against, with no arithmetic.
    2. Rolling forward from the day after the member's last period to END BEFORE the
       payment, which is precisely how CoverageCalculator's sequential branch builds
       the next period, so an invoice created for this period stays gap-free. Anchoring
       on the *latest* coverage end instead would send a payment landing in a coverage
       GAP to the calendar fallback, and the create-invoice callers would then write a
       calendar-aligned invoice into an off-calendar member's sequence.
    3. Rolling forward from the membership start date, matching the first_invoice
       branch, for a member who has no invoiced coverage at all.

    Invoice lookups are restricted to SUBMITTED invoices, deliberately, even though the
    overlap detectors every caller uses match on `docstatus < 2`. An earlier version of
    this function widened to match them, on the reasoning that a draft would otherwise
    be reported as an exact overlap of a period derived from elsewhere. That reasoning
    was backwards, and widening made the duplicate it feared strictly more likely:

    - `check_coverage_overlap` already includes drafts, so a draft is in the overlap set
      either way. The only variable is whether the period returned here EQUALS it.
    - Returning a submitted-only period usually differs from the draft's, so the callers
      see a partial overlap and stop - `mollie_payment_orchestrator._create_invoice_if_safe`
      and `dues_payment_processor` both return None for "manual review required".
    - Returning the draft's own period makes `exact_match` certain, and a draft's
      `outstanding_amount` is 0, which those same callers read as "already paid" and use
      as their cue to create ANOTHER invoice for the period.

    The real defect is that the callers treat `outstanding_amount == 0` as "paid"
    without checking `docstatus`; for a draft it means "not submitted yet". Until that
    is fixed there, staying submitted-only keeps the safe branch reachable.

    Args:
        member_name: Member document name
        payment_date: Date the payment was made
        billing_frequency: Resolved billing frequency for this member
        custom_number: Period length for Custom frequency
        custom_unit: Period unit for Custom frequency

    Returns:
        tuple: (coverage_start, coverage_end), or None if there is nothing to anchor to
    """
    from verenigingen.services.billing.billing_period_calculator import calculate_coverage_end

    customer = frappe.db.get_value("Member", member_name, "customer")

    if customer:
        # Where two invoices cover the same date (e.g. an Annual period plus a
        # corrective short one), take the latest-starting - the narrower, more
        # specific period is the one a payment on that date belongs to.
        covering = frappe.db.get_value(
            "Sales Invoice",
            {
                "customer": customer,
                "docstatus": 1,
                "custom_coverage_start_date": ["<=", payment_date],
                "custom_coverage_end_date": [">=", payment_date],
            },
            ["custom_coverage_start_date", "custom_coverage_end_date"],
            as_dict=True,
            order_by="custom_coverage_start_date desc",
        )
        if covering:
            return getdate(covering.custom_coverage_start_date), getdate(covering.custom_coverage_end_date)

        prior_end = frappe.db.get_value(
            "Sales Invoice",
            {"customer": customer, "docstatus": 1, "custom_coverage_end_date": ["<", payment_date]},
            "custom_coverage_end_date",
            order_by="custom_coverage_end_date desc",
        )
        if prior_end:
            return _roll_to_period_containing(
                add_days(getdate(prior_end), 1),
                payment_date,
                billing_frequency,
                custom_number,
                custom_unit,
                calculate_coverage_end,
            )

        if frappe.db.exists(
            "Sales Invoice",
            {"customer": customer, "docstatus": 1, "custom_coverage_end_date": ["is", "set"]},
        ):
            # Coverage exists but all of it starts after this payment, so the payment
            # has no position in the sequence. Fall back rather than invent one - the
            # membership start below would anchor a period the member was never billed.
            return None

    membership_start = frappe.db.get_value(
        "Membership",
        {"member": member_name, "status": "Active", "docstatus": 1},
        "start_date",
        order_by="start_date asc",
    )
    if membership_start and getdate(membership_start) <= payment_date:
        return _roll_to_period_containing(
            getdate(membership_start),
            payment_date,
            billing_frequency,
            custom_number,
            custom_unit,
            calculate_coverage_end,
        )

    return None


def _roll_to_period_containing(
    period_start: date,
    payment_date: date,
    billing_frequency: str,
    custom_number: Optional[int],
    custom_unit: Optional[str],
    coverage_end_fn,
) -> Optional[tuple]:
    """
    Step whole billing periods forward from period_start until one contains payment_date.

    Returns:
        tuple: (coverage_start, coverage_end), or None if payment_date is unreachably far
    """
    for _ in range(MAX_PERIOD_ROLL_STEPS):
        period_end = coverage_end_fn(billing_frequency, period_start, custom_number, custom_unit)
        if period_end >= payment_date:
            return period_start, period_end
        period_start = add_days(period_end, 1)

    return None


def find_invoice_for_payment(
    member_name: str,
    payment_date: date,
    payment_amount: float,
    remittance_info: Optional[str] = None,
) -> Optional[str]:
    """
    Find the best matching Sales Invoice for a payment.

    Matching strategy (in priority order):
    1. Parse invoice number from remittance_info if present
    2. Find invoice by exact coverage period match
    3. Find invoice by member + amount + unpaid status within date window

    Args:
        member_name: Member document name
        payment_date: Date the payment was made
        payment_amount: Payment amount
        remittance_info: Optional remittance information (may contain invoice reference)

    Returns:
        Sales Invoice name if found, None otherwise
    """
    import re

    from frappe.utils import flt, getdate

    payment_date = getdate(payment_date)

    # Get member's customer
    customer = frappe.db.get_value("Member", member_name, "customer")
    if not customer:
        frappe.logger().warning(f"Member {member_name} has no customer record")
        return None

    # Strategy 1: Parse invoice number from remittance info
    if remittance_info:
        # Common patterns: "ACC-SINV-2024-00001", "SINV-00001", "Invoice 12345"
        invoice_patterns = [
            r"(ACC-SINV-\d{4}-\d+)",  # ERPNext naming with accounting prefix
            r"(SINV-\d+)",  # ERPNext default naming
            r"(?:Invoice|Factuur|Inv)[:\s#]*(\d+)",  # "Invoice 12345" or "Factuur: 12345"
        ]

        for pattern in invoice_patterns:
            match = re.search(pattern, remittance_info, re.IGNORECASE)
            if match:
                potential_invoice = match.group(1)
                # Verify the invoice exists and belongs to this customer
                if frappe.db.exists(
                    "Sales Invoice",
                    {"name": potential_invoice, "customer": customer, "docstatus": 1},
                ):
                    frappe.logger().info(
                        f"Found invoice {potential_invoice} from remittance info for member {member_name}"
                    )
                    return potential_invoice

    # Strategy 2: Find invoice by coverage period
    coverage_start, coverage_end = calculate_coverage_for_payment_date(member_name, payment_date)

    # Check for overlap with existing invoices using the coverage overlap detector
    from verenigingen.services.billing.coverage_overlap_detector import check_coverage_overlap

    overlap_result = check_coverage_overlap(
        customer=customer,
        proposed_start=coverage_start,
        proposed_end=coverage_end,
        exclude_cancelled=True,
    )

    if overlap_result.exact_match:
        # Found exact coverage match - check if it has outstanding amount
        outstanding = frappe.db.get_value("Sales Invoice", overlap_result.exact_match, "outstanding_amount")
        if outstanding and flt(outstanding) > 0:
            frappe.logger().info(
                f"Found invoice {overlap_result.exact_match} by coverage period match "
                f"({coverage_start} to {coverage_end}) for member {member_name}"
            )
            return overlap_result.exact_match

    # Strategy 3: Find unpaid invoice by amount match
    # Look for unpaid invoices within a reasonable date window (e.g., 3 months before payment)
    amount_tolerance = 0.01  # Allow for small rounding differences

    unpaid_invoices = frappe.db.sql(
        """
        SELECT name, grand_total, outstanding_amount, posting_date
        FROM `tabSales Invoice`
        WHERE customer = %s
        AND docstatus = 1
        AND outstanding_amount > 0
        AND posting_date BETWEEN DATE_SUB(%s, INTERVAL 3 MONTH) AND %s
        ORDER BY
            ABS(outstanding_amount - %s) ASC,  -- Prefer exact amount match
            posting_date DESC  -- Then most recent
        LIMIT 1
    """,
        (customer, payment_date, payment_date, payment_amount),
        as_dict=True,
    )

    if unpaid_invoices:
        invoice = unpaid_invoices[0]
        # Check if amount matches within tolerance
        if abs(flt(invoice.outstanding_amount) - flt(payment_amount)) <= amount_tolerance:
            frappe.logger().info(
                f"Found invoice {invoice.name} by amount match "
                f"(outstanding: {invoice.outstanding_amount}, payment: {payment_amount}) for member {member_name}"
            )
            return invoice.name

    # No matching invoice found
    frappe.logger().info(
        f"No matching invoice found for member {member_name}, "
        f"amount {payment_amount}, coverage {coverage_start} to {coverage_end}"
    )
    return None
