# Copyright (c) 2025, Verenigingen
# For license information, please see license.txt

"""
PaymentCoverageService - Coverage date extraction for payment history.

This service handles extraction of coverage period dates (start/end) from
multiple sources with proper fallback logic.

Coverage Date Sources (in priority order):
    1. Membership Dues Schedule (authoritative source via last_generated_invoice link)
    2. Sales Invoice custom fields (cached coverage dates)

Extracted from payment_mixin.py:
    - _get_coverage_from_schedule() (lines 537-559)
    - _get_coverage_from_invoice() (lines 561-572)

Total: ~35 LOC of coverage extraction logic now in service layer.

Architecture:
    - StatelessService for consistent logging and error handling
    - No external service dependencies
    - Pure date extraction without side effects
"""

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any, Optional, Tuple

import frappe

from verenigingen.services.infrastructure.base_service import StatelessService

if TYPE_CHECKING:
    from frappe.model.document import Document


@dataclass
class CoveragePeriod:
    """Represents a coverage period with start and end dates."""

    start_date: Optional[date] = None
    end_date: Optional[date] = None
    source: str = "unknown"

    @property
    def is_valid(self) -> bool:
        """Check if coverage period has valid dates."""
        if not self.start_date or not self.end_date:
            return False
        return self.start_date <= self.end_date


class PaymentCoverageService(StatelessService):
    """
    Service for extracting coverage period dates from various sources.

    Provides consistent coverage date extraction with proper fallback logic
    and validation. Used by PaymentHistoryService for building payment
    history entries with coverage information.
    """

    def __init__(self) -> None:
        """Initialize the payment coverage service."""
        super().__init__(service_name="PaymentCoverageService")

    def get_coverage_for_invoice(
        self, member_name: str, invoice_name: str, invoice_data: Optional[Any] = None
    ) -> CoveragePeriod:
        """
        Get coverage period for an invoice from best available source.

        Attempts to get coverage from schedule first (authoritative), then
        falls back to invoice custom fields (cached).

        Args:
            member_name: Name of the member document
            invoice_name: Name of the Sales Invoice
            invoice_data: Optional pre-fetched invoice data with coverage fields

        Returns:
            CoveragePeriod: Coverage dates with source information
        """
        # Try schedule first (authoritative source)
        schedule_coverage = self.get_coverage_from_schedule(member_name, invoice_name)
        if schedule_coverage.is_valid:
            return schedule_coverage

        # Fallback to invoice cache
        invoice_coverage = self.get_coverage_from_invoice(invoice_data)
        if invoice_coverage.is_valid:
            return invoice_coverage

        # Return empty coverage if nothing found
        return CoveragePeriod(source="none")

    def get_coverage_from_schedule(self, member_name: str, invoice_name: str) -> CoveragePeriod:
        """
        Get coverage from dues schedule - direct link, no heuristics.

        This is the authoritative source for coverage dates as it links
        the invoice directly to the schedule that generated it.

        Args:
            member_name: Name of the member document
            invoice_name: Name of the Sales Invoice

        Returns:
            CoveragePeriod: Coverage dates from schedule, or empty if not found
        """
        try:
            # Direct link lookup via last_generated_invoice
            schedule = frappe.db.get_value(
                "Membership Dues Schedule",
                {"member": member_name, "last_generated_invoice": invoice_name},
                ["last_invoice_coverage_start", "last_invoice_coverage_end"],
                as_dict=True,
            )

            if schedule and schedule.last_invoice_coverage_start:
                return CoveragePeriod(
                    start_date=schedule.last_invoice_coverage_start,
                    end_date=schedule.last_invoice_coverage_end,
                    source="schedule",
                )

            # No coverage data found in schedule
            return CoveragePeriod(source="schedule_empty")

        except Exception as e:
            self.logger.error(f"Error getting coverage from schedule for invoice {invoice_name}: {str(e)}")
            return CoveragePeriod(source="schedule_error")

    def get_coverage_from_invoice(self, invoice_data: Optional[Any]) -> CoveragePeriod:
        """
        Get coverage from invoice custom fields (cached values).

        This is a fallback source when schedule lookup doesn't return results.
        The invoice stores a cached copy of the coverage dates.

        Args:
            invoice_data: Invoice data (dict or object with custom_coverage_* fields)

        Returns:
            CoveragePeriod: Coverage dates from invoice, or empty if not found
        """
        if not invoice_data:
            return CoveragePeriod(source="invoice_empty")

        try:
            start_date = getattr(invoice_data, "custom_coverage_start_date", None)
            end_date = getattr(invoice_data, "custom_coverage_end_date", None)

            # Also check dict access for frappe.get_all results
            if start_date is None and isinstance(invoice_data, dict):
                start_date = invoice_data.get("custom_coverage_start_date")
            if end_date is None and isinstance(invoice_data, dict):
                end_date = invoice_data.get("custom_coverage_end_date")

            if start_date or end_date:
                return CoveragePeriod(
                    start_date=start_date,
                    end_date=end_date,
                    source="invoice_cache",
                )

            return CoveragePeriod(source="invoice_empty")

        except Exception as e:
            self.logger.error(f"Error getting coverage from invoice cache: {str(e)}")
            return CoveragePeriod(source="invoice_error")

    def validate_coverage_period(self, coverage: CoveragePeriod, invoice_name: str) -> bool:
        """
        Validate that a coverage period is logically correct.

        Logs errors for invalid periods but doesn't throw exceptions.

        Args:
            coverage: Coverage period to validate
            invoice_name: Invoice name for error logging

        Returns:
            bool: True if coverage is valid or empty, False if invalid
        """
        if not coverage.start_date or not coverage.end_date:
            # Empty coverage is acceptable
            return True

        if coverage.start_date > coverage.end_date:
            self.logger.error(
                f"Invalid coverage period for invoice {invoice_name}: "
                f"start ({coverage.start_date}) > end ({coverage.end_date})"
            )
            return False

        return True


# Singleton instance
_payment_coverage_service: Optional[PaymentCoverageService] = None


def get_payment_coverage_service() -> PaymentCoverageService:
    """Get singleton instance of PaymentCoverageService."""
    global _payment_coverage_service
    if _payment_coverage_service is None:
        _payment_coverage_service = PaymentCoverageService()
    return _payment_coverage_service
