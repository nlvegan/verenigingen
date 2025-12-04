# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Service for detecting duplicate and overlapping invoices based on coverage periods.
Extracted from MembershipDuesSchedule to reduce complexity and improve testability.

This service implements the critical duplicate prevention logic that ensures members
are not billed multiple times for the same coverage period.

Architecture:
    - Inherits from StatelessService for consistent logging, metrics, error handling
    - DuplicateInvoiceDetectionResult kept for backward compatibility with OperationResult-compatible properties
"""

import re
from datetime import date
from typing import Any, Dict, List, Optional

import frappe
from frappe.utils import getdate

from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.utils.billing_period_calculator import derive_coverage_from_invoice_data

# Business rule constants
GAP_RESET_THRESHOLD_DAYS = 30  # Billing gap threshold - prevents processing old invoices
MAX_OVERLAPPING_INVOICES = 10  # Maximum overlapping invoices to return from SQL query
FALLBACK_CUTOFF_DATE = "1900-01-01"  # Sentinel date for first-time invoice generation


class DuplicateInvoiceDetectionResult:
    """
    Result object for duplicate invoice detection.

    Deprecated: Migrate to OperationResult[None] in future versions.

    This class maintains backward compatibility while providing OperationResult-compatible
    properties for gradual migration.

    Attributes:
        can_generate: Whether invoice generation is allowed (legacy - use .success)
        reason: Explanation message (legacy - use .error_message for failures)
        metadata: Additional context
        success: OperationResult-compatible alias for can_generate
        error_message: OperationResult-compatible alias for reason (when can_generate=False)
    """

    def __init__(self, can_generate: bool, reason: str, **metadata: Any) -> None:
        self.can_generate: bool = can_generate
        self.reason: str = reason
        self.metadata: Dict[str, Any] = metadata

        # OperationResult-compatible properties
        self.success: bool = can_generate
        self.data = None  # No data payload for this result type
        self.error_message: Optional[str] = reason if not can_generate else None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format"""
        result: Dict[str, Any] = {"can_generate": self.can_generate, "reason": self.reason}
        result.update(self.metadata)
        return result

    def __repr__(self) -> str:
        return f"DuplicateInvoiceDetectionResult(can_generate={self.can_generate}, reason='{self.reason}')"


class DuplicateInvoiceDetector(StatelessService):
    """
    Service for detecting duplicate and overlapping invoice coverage periods.

    This service handles:
    - Precondition validation (member/customer existence)
    - Primary overlap detection using SQL queries
    - Fallback overlap detection for invoices with missing coverage dates
    - Gap reset logic for large time gaps
    """

    def __init__(self, schedule_doc: Any) -> None:
        """
        Initialize detector with a MembershipDuesSchedule document.

        Args:
            schedule_doc: MembershipDuesSchedule document instance
        """
        super().__init__(service_name="DuplicateInvoiceDetector")
        self.schedule: Any = schedule_doc
        self.member: Optional[str] = schedule_doc.member
        self.billing_frequency: str = schedule_doc.billing_frequency

    def check_for_duplicates(
        self, proposed_coverage_start: date, proposed_coverage_end: date
    ) -> DuplicateInvoiceDetectionResult:
        """
        Check if proposed coverage period would create duplicate/overlapping invoices.

        Args:
            proposed_coverage_start: Start date of proposed coverage period
            proposed_coverage_end: End date of proposed coverage period

        Returns:
            DuplicateInvoiceDetectionResult with can_generate flag and reason
        """
        # Phase 1: Validate preconditions
        validation_result = self._validate_preconditions()
        if validation_result:  # Returns result only if validation fails
            return validation_result

        customer = self._get_customer()

        # Phase 2: Primary overlap detection (invoices with coverage dates)
        overlapping = self._find_overlapping_invoices(
            customer, proposed_coverage_start, proposed_coverage_end
        )

        if overlapping:
            return self._analyze_overlap(overlapping, proposed_coverage_start, proposed_coverage_end)

        # Phase 3: Check for large gaps (gap reset logic)
        gap_result = self._check_gap_reset(customer, proposed_coverage_start)
        if gap_result:
            return gap_result

        # Phase 4: Fallback detection (invoices with missing coverage dates)
        fallback_result = self._check_fallback_overlaps(
            customer, proposed_coverage_start, proposed_coverage_end
        )
        if fallback_result:
            return fallback_result

        return DuplicateInvoiceDetectionResult(can_generate=True, reason="No duplicates found")

    def _validate_preconditions(self) -> Optional[DuplicateInvoiceDetectionResult]:
        """Validate that member and customer exist

        Returns:
            DuplicateInvoiceDetectionResult if validation fails, None if validation passes
        """
        if not self.member:
            return DuplicateInvoiceDetectionResult(
                can_generate=True, reason="No member - skipping duplicate check"
            )

        member_doc = frappe.get_doc("Member", self.member)
        if not member_doc.customer:
            return DuplicateInvoiceDetectionResult(
                can_generate=True, reason="No customer - skipping duplicate check"
            )

        return None  # Validation passed

    def _get_customer(self) -> str:
        """Get customer name from member

        Returns:
            Customer name string
        """
        member_doc = frappe.get_doc("Member", self.member)
        return member_doc.customer

    def _find_overlapping_invoices(
        self, customer: str, proposed_start: date, proposed_end: date
    ) -> List[Dict[str, Any]]:
        """
        Find invoices with overlapping coverage periods using efficient SQL.

        Only checks SUBMITTED invoices (docstatus=1) with explicit coverage dates.

        Args:
            customer: Customer name to check
            proposed_start: Proposed coverage period start date
            proposed_end: Proposed coverage period end date

        Returns:
            List of invoice dictionaries with coverage dates
        """
        overlapping_invoices = frappe.db.sql(
            """
            SELECT si.name, si.posting_date,
                   si.custom_coverage_start_date, si.custom_coverage_end_date
            FROM `tabSales Invoice` si
            WHERE si.customer = %(customer)s
            AND si.docstatus = 1
            AND si.custom_coverage_start_date IS NOT NULL
            AND si.custom_coverage_end_date IS NOT NULL
            AND %(proposed_start)s <= si.custom_coverage_end_date
            AND %(proposed_end)s >= si.custom_coverage_start_date
            LIMIT %(limit)s
        """,
            {
                "customer": customer,
                "proposed_start": proposed_start,
                "proposed_end": proposed_end,
                "limit": MAX_OVERLAPPING_INVOICES,
            },
            as_dict=True,
        )
        return overlapping_invoices

    def _analyze_overlap(
        self, overlapping_invoices: List[Dict[str, Any]], proposed_start: date, proposed_end: date
    ) -> DuplicateInvoiceDetectionResult:
        """
        Analyze overlapping invoices to distinguish exact duplicates from partial overlaps.

        Args:
            overlapping_invoices: List of invoice dictionaries with coverage dates
            proposed_start: Proposed coverage period start date
            proposed_end: Proposed coverage period end date

        Returns:
            DuplicateInvoiceDetectionResult with duplicate/overlap information
        """
        # Check if any are exact duplicates vs partial overlaps
        exact_duplicates = [
            inv
            for inv in overlapping_invoices
            if getdate(inv["custom_coverage_start_date"]) == getdate(proposed_start)
            and getdate(inv["custom_coverage_end_date"]) == getdate(proposed_end)
        ]

        if exact_duplicates:
            # Exact duplicate - same coverage period
            invoice_details = ", ".join(
                [f"{inv['name']} (posted {inv['posting_date']})" for inv in exact_duplicates]
            )
            return DuplicateInvoiceDetectionResult(
                can_generate=False,
                reason=f"Duplicate coverage prevented: Invoice(s) {invoice_details} already cover exact period {proposed_start} to {proposed_end}",
            )
        else:
            # Partial overlap - different but overlapping periods
            invoice_list = ", ".join([inv["name"] for inv in overlapping_invoices])
            return DuplicateInvoiceDetectionResult(
                can_generate=False,
                reason=f"Coverage overlap prevented: Invoice(s) {invoice_list} already cover overlapping period with {proposed_start} to {proposed_end}",
            )

    def _check_gap_reset(
        self, customer: str, proposed_start: date
    ) -> Optional[DuplicateInvoiceDetectionResult]:
        """
        Check for large gaps in coverage that trigger gap reset logic.

        If more than 30 days have passed since last coverage, skip fallback processing.

        Args:
            customer: Customer name to check
            proposed_start: Proposed coverage period start date

        Returns:
            DuplicateInvoiceDetectionResult if gap reset applies, None otherwise
        """
        latest_coverage_invoice = frappe.db.sql(
            """
            SELECT custom_coverage_end_date
            FROM `tabSales Invoice` si
            WHERE si.customer = %(customer)s
            AND si.docstatus = 1
            AND si.custom_coverage_end_date IS NOT NULL
            ORDER BY si.custom_coverage_end_date DESC
            LIMIT 1
        """,
            {"customer": customer},
            as_dict=True,
        )

        if latest_coverage_invoice:
            latest_coverage_end = getdate(latest_coverage_invoice[0]["custom_coverage_end_date"])
            gap_days = (getdate(proposed_start) - latest_coverage_end).days

            if gap_days > GAP_RESET_THRESHOLD_DAYS:
                # Large gap detected - skip fallback processing entirely
                self.logger.info(
                    f"Large coverage gap ({gap_days} days > {GAP_RESET_THRESHOLD_DAYS}) detected for {customer}. "
                    f"Skipping fallback coverage processing per gap reset logic."
                )
                return DuplicateInvoiceDetectionResult(
                    can_generate=True,
                    reason="No duplicates found (gap reset applied)",
                    gap_reset=True,
                )

        return None  # No gap reset needed

    def _check_fallback_overlaps(
        self, customer: str, proposed_start: date, proposed_end: date
    ) -> Optional[DuplicateInvoiceDetectionResult]:
        """
        Check for overlaps with invoices that have missing coverage dates.

        Uses coverage derivation fallback logic to estimate coverage periods.

        Args:
            customer: Customer name to check
            proposed_start: Proposed coverage period start date
            proposed_end: Proposed coverage period end date

        Returns:
            DuplicateInvoiceDetectionResult if fallback overlaps found, None otherwise
        """
        # Determine cutoff date for fallback processing
        cutoff_date = self._get_fallback_cutoff_date(customer)

        # Find invoices needing fallback processing
        invoices_needing_fallback = frappe.db.sql(
            """
            SELECT
                si.name,
                si.posting_date,
                mds.last_invoice_date,
                mds.next_invoice_date,
                mds.billing_frequency
            FROM `tabSales Invoice` si
            LEFT JOIN `tabMembership Dues Schedule` mds ON mds.name = si.membership_dues_schedule_display
            WHERE si.customer = %(customer)s
            AND si.docstatus = 1
            AND (si.custom_coverage_start_date IS NULL OR si.custom_coverage_end_date IS NULL)
            AND si.posting_date > %(cutoff_date)s
        """,
            {
                "customer": customer,
                "cutoff_date": cutoff_date,
            },
            as_dict=True,
        )

        # Process fallback cases
        overlapping_fallback_invoices = self._process_fallback_invoices(
            invoices_needing_fallback, proposed_start, proposed_end
        )

        if overlapping_fallback_invoices:
            return DuplicateInvoiceDetectionResult(
                can_generate=False,
                reason=f"Coverage overlap prevented (fallback detection): Invoice(s) {', '.join(overlapping_fallback_invoices)} already cover period {proposed_start} to {proposed_end}",
            )

        return None  # No fallback overlaps found

    def _get_fallback_cutoff_date(self, customer: str) -> str:
        """
        Get cutoff date for fallback processing.

        Only processes invoices newer than the most recent coverage date.

        Args:
            customer: Customer name to check

        Returns:
            Cutoff date string (ISO format)
        """
        latest_coverage_invoice = frappe.db.sql(
            """
            SELECT custom_coverage_end_date
            FROM `tabSales Invoice` si
            WHERE si.customer = %(customer)s
            AND si.docstatus = 1
            AND si.custom_coverage_end_date IS NOT NULL
            ORDER BY si.custom_coverage_end_date DESC
            LIMIT 1
        """,
            {"customer": customer},
            as_dict=True,
        )

        if latest_coverage_invoice:
            return str(getdate(latest_coverage_invoice[0]["custom_coverage_end_date"]))
        else:
            # No coverage found - check all invoices (first-time generation)
            return FALLBACK_CUTOFF_DATE

    def _process_fallback_invoices(
        self, invoices: List[Dict[str, Any]], proposed_start: date, proposed_end: date
    ) -> List[str]:
        """
        Process invoices with missing coverage dates using derivation fallback.

        Args:
            invoices: List of invoice dictionaries with potentially missing coverage dates
            proposed_start: Proposed coverage period start date
            proposed_end: Proposed coverage period end date

        Returns:
            List of overlapping invoice names
        """
        overlapping_fallback_invoices = []

        for inv in invoices:
            try:
                # Derive coverage from invoice and schedule dates
                inv_start, inv_end = derive_coverage_from_invoice_data(
                    inv["posting_date"],
                    inv["last_invoice_date"],
                    inv["next_invoice_date"],
                    inv["billing_frequency"] or self.billing_frequency,
                )

                # Validate derived coverage dates
                if not inv_start or not inv_end:
                    self.logger.error(
                        f"Failed to derive coverage dates for invoice {inv['name']}: "
                        f"posting_date={inv['posting_date']}, derived start={inv_start}, end={inv_end}"
                    )
                    continue

                # Check for overlap with proposed period
                if getdate(proposed_start) <= inv_end and getdate(proposed_end) >= inv_start:
                    overlapping_fallback_invoices.append(inv["name"])

            except Exception as e:
                # Clean up HTML tags from error message to prevent formatting issues
                error_msg = re.sub("<[^<]+?>", "", str(e))
                self.logger.error(
                    f"Error processing fallback coverage for invoice {inv['name']}: {error_msg}"
                )
                continue

        return overlapping_fallback_invoices


def get_duplicate_invoice_detector(schedule_doc) -> DuplicateInvoiceDetector:
    """Get instance of DuplicateInvoiceDetector."""
    return DuplicateInvoiceDetector(schedule_doc)
