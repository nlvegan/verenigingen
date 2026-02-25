# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
BillingDateService - Date management for Membership Dues Schedule.

This service handles all date-related operations for dues schedules including:
- Calculating next invoice dates based on billing frequency
- Updating schedule dates after invoice generation
- Setting billing day from member anniversary
- Advancing schedule dates for retry logic

Extracted from membership_dues_schedule.py to reduce controller size
and improve testability.

Architecture:
- StatelessService base class for consistent logging and error handling
- Uses utility functions from billing_period_calculator for calculations
"""

from datetime import date
from typing import TYPE_CHECKING, Optional

import frappe
from frappe.utils import getdate, today

from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.utils.billing_period_calculator import calculate_next_invoice_date

if TYPE_CHECKING:
    from frappe.model.document import Document


class BillingDateService(StatelessService):
    """
    Service for managing billing dates on Membership Dues Schedule documents.

    Handles date calculations, updates, and synchronization between
    schedule and member records.

    Example:
        service = get_billing_date_service()
        next_date = service.calculate_next_invoice_date(schedule_doc)
        service.update_schedule_dates(schedule_doc, actual_invoice_date="2025-01-15")
    """

    def __init__(self):
        super().__init__(service_name="BillingDateService")

    def calculate_next_invoice_date(self, schedule_doc: "Document", from_date: Optional[str] = None) -> date:
        """
        Calculate next billing date based on frequency.

        Uses the billing_period_calculator utility for actual calculation,
        handling both standard frequencies (Monthly, Quarterly, etc.) and
        custom frequencies.

        Args:
            schedule_doc: The schedule document
            from_date: Starting date for calculation (defaults to next_invoice_date or today)

        Returns:
            The calculated next invoice date
        """
        if not from_date:
            from_date = schedule_doc.next_invoice_date or today()

        return calculate_next_invoice_date(
            billing_frequency=schedule_doc.billing_frequency,
            from_date=from_date,
            custom_frequency_number=getattr(schedule_doc, "custom_frequency_number", None),
            custom_frequency_unit=getattr(schedule_doc, "custom_frequency_unit", None),
        )

    def update_schedule_dates(
        self, schedule_doc: "Document", actual_invoice_date: Optional[str] = None
    ) -> None:
        """
        Update schedule dates after invoice generation.

        Handles both actual invoice generation (with posting date) and
        test mode (fallback behavior). Also updates the member's
        next_invoice_date field.

        CRITICAL FIX: For daily/sequential billing, base next_invoice_date on coverage end
        rather than posting date to prevent date drift when generating ahead of time.

        Args:
            schedule_doc: The schedule document to update
            actual_invoice_date: The posting date from the created invoice (optional)
        """
        if actual_invoice_date:
            # Use the actual posting date from the created invoice
            schedule_doc.last_invoice_date = actual_invoice_date

            # For daily billing or when we have coverage tracking, calculate next date from coverage end
            if schedule_doc.billing_frequency == "Daily" and schedule_doc.last_invoice_coverage_end:
                # For daily: next invoice should be day after coverage ends
                schedule_doc.next_invoice_date = self.calculate_next_invoice_date(
                    schedule_doc, schedule_doc.last_invoice_coverage_end
                )
            else:
                # For other frequencies: use posting date as before
                schedule_doc.next_invoice_date = self.calculate_next_invoice_date(
                    schedule_doc, actual_invoice_date
                )
        else:
            # Fallback to old behavior (for test mode)
            schedule_doc.last_invoice_date = schedule_doc.next_invoice_date
            schedule_doc.next_invoice_date = self.calculate_next_invoice_date(
                schedule_doc, schedule_doc.next_invoice_date
            )

        schedule_doc.save()

        # Update member's next_invoice_date field
        self._update_member_next_invoice_date(schedule_doc)

    def _update_member_next_invoice_date(self, schedule_doc: "Document") -> None:
        """
        Update the member's next_invoice_date field to match the schedule.

        Skips update for terminated/deceased/banned members, or if member doesn't exist.

        Args:
            schedule_doc: The schedule document with updated dates
        """
        if not schedule_doc.member:
            return

        # Check member exists and get status before updating
        member_status = frappe.db.get_value("Member", schedule_doc.member, "status")

        if member_status is None:
            # Member doesn't exist (possibly deleted)
            self.logger.warning(f"Member {schedule_doc.member} not found, skipping next_invoice_date update")
            return

        if member_status in ["Deceased", "Banned", "Quit"]:
            self.logger.debug(
                f"Skipping member date update for {schedule_doc.member} - status: {member_status}"
            )
            return

        # Use db.set_value to avoid triggering Member's validate/on_update hooks
        frappe.db.set_value(
            "Member",
            schedule_doc.member,
            "next_invoice_date",
            schedule_doc.next_invoice_date,
            update_modified=False,
        )

    def set_billing_day(self, schedule_doc: "Document") -> None:
        """
        Set billing day based on member's anniversary date.

        For member schedules, uses the day from member_since date.
        Defaults to 1 (first of month) if no member_since date is available.

        Args:
            schedule_doc: The schedule document to update
        """
        if not schedule_doc.billing_day or schedule_doc.billing_day == 0:
            if schedule_doc.member:
                # Get the member_since value directly from database
                member_since = frappe.db.get_value("Member", schedule_doc.member, "member_since")
                if member_since:
                    member_since_date = getdate(member_since)
                    schedule_doc.billing_day = member_since_date.day
                else:
                    # Default to 1st of month when no member_since date
                    schedule_doc.billing_day = 1
            else:
                # Default for templates or schedules without member
                schedule_doc.billing_day = 1

    def advance_schedule_dates(self, schedule_doc: "Document") -> None:
        """
        Advance schedule dates to the next billing period.

        Used for error recovery when invoice generation fails repeatedly
        to prevent infinite retry loops.

        Args:
            schedule_doc: The schedule document to advance
        """
        try:
            if not schedule_doc.next_invoice_date:
                self.logger.warning(f"Cannot advance dates for {schedule_doc.name}: no next_invoice_date set")
                return

            new_next_date = self.calculate_next_invoice_date(schedule_doc, schedule_doc.next_invoice_date)

            # Update dates using db_set to avoid validation loops
            frappe.db.set_value(
                schedule_doc.doctype,
                schedule_doc.name,
                "last_invoice_date",
                schedule_doc.next_invoice_date,
            )
            frappe.db.set_value(
                schedule_doc.doctype,
                schedule_doc.name,
                "next_invoice_date",
                new_next_date,
            )

            # Update local object for immediate consistency
            schedule_doc.last_invoice_date = schedule_doc.next_invoice_date
            schedule_doc.next_invoice_date = new_next_date

            self.logger.info(
                f"Advanced schedule {schedule_doc.name}: "
                f"last_invoice_date={schedule_doc.last_invoice_date}, "
                f"next_invoice_date={schedule_doc.next_invoice_date}"
            )

        except Exception as e:
            self.logger.error(f"Failed to advance dates for schedule {schedule_doc.name}: {str(e)}")
            frappe.log_error(
                f"Failed to advance dates for schedule {schedule_doc.name}: {str(e)}",
                "Date Advancement Error",
            )

    def initialize_next_invoice_date(self, schedule_doc: "Document") -> None:
        """
        Initialize next invoice date for new schedules.

        Sets next_invoice_date to today if not already set.

        Args:
            schedule_doc: The schedule document to initialize
        """
        if schedule_doc.is_new() and not schedule_doc.is_template and not schedule_doc.next_invoice_date:
            schedule_doc.next_invoice_date = today()


def get_billing_date_service() -> BillingDateService:
    """Get singleton instance of BillingDateService."""
    return BillingDateService()
