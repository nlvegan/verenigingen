# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Coverage Overlap Detection - Standalone functions for detecting overlapping invoice coverage.

This module provides reusable functions for detecting overlapping coverage periods
that can be used by:
- DuplicateInvoiceDetector (for schedule-based invoice generation)
- Payment recovery utilities (for historical payment processing)
- Any other code that creates dues invoices

The key function `find_overlapping_invoices` uses proper date range overlap detection:
    proposed_start <= existing_end AND proposed_end >= existing_start
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional

import frappe
from frappe.utils import getdate

# Business rule constants
MAX_OVERLAPPING_INVOICES = 10  # Maximum overlapping invoices to return from SQL query


@dataclass
class OverlapCheckResult:
    """
    Result of coverage overlap check.

    Attributes:
        has_overlap: Whether any overlapping invoices were found
        overlapping_invoices: List of overlapping invoice details
        exact_match: Invoice name if an exact coverage match exists
        reason: Human-readable explanation of the result
    """

    has_overlap: bool
    overlapping_invoices: List[dict]
    exact_match: Optional[str]
    reason: str

    @property
    def can_create_invoice(self) -> bool:
        """Whether it's safe to create a new invoice (no overlaps found)."""
        return not self.has_overlap

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "has_overlap": self.has_overlap,
            "overlapping_invoices": self.overlapping_invoices,
            "exact_match": self.exact_match,
            "reason": self.reason,
            "can_create_invoice": self.can_create_invoice,
        }


def find_overlapping_invoices(
    customer: str,
    proposed_start: date,
    proposed_end: date,
    exclude_cancelled: bool = True,
    only_with_outstanding: bool = False,
) -> List[dict]:
    """
    Find invoices with coverage periods that overlap with the proposed period.

    Uses standard date range overlap detection:
        proposed_start <= existing_end AND proposed_end >= existing_start

    This catches:
    - Exact matches (same start and end dates)
    - Partial overlaps (one period starts during another)
    - Complete containment (one period fully contains another)

    Args:
        customer: Customer name to check invoices for
        proposed_start: Start date of proposed coverage period
        proposed_end: End date of proposed coverage period
        exclude_cancelled: If True, excludes cancelled invoices (docstatus=2)
        only_with_outstanding: If True, only returns invoices with outstanding_amount > 0

    Returns:
        List of invoice dicts with keys: name, posting_date,
        custom_coverage_start_date, custom_coverage_end_date, outstanding_amount
    """
    proposed_start = getdate(proposed_start)
    proposed_end = getdate(proposed_end)

    # Build docstatus filter
    if exclude_cancelled:
        docstatus_condition = "AND si.docstatus < 2"
    else:
        docstatus_condition = ""

    # Build outstanding filter
    if only_with_outstanding:
        outstanding_condition = "AND si.outstanding_amount > 0"
    else:
        outstanding_condition = ""

    overlapping_invoices = frappe.db.sql(
        f"""
        SELECT
            si.name,
            si.posting_date,
            si.custom_coverage_start_date,
            si.custom_coverage_end_date,
            si.outstanding_amount,
            si.grand_total,
            si.docstatus
        FROM `tabSales Invoice` si
        WHERE si.customer = %(customer)s
        AND si.custom_coverage_start_date IS NOT NULL
        AND si.custom_coverage_end_date IS NOT NULL
        AND %(proposed_start)s <= si.custom_coverage_end_date
        AND %(proposed_end)s >= si.custom_coverage_start_date
        {docstatus_condition}
        {outstanding_condition}
        ORDER BY si.custom_coverage_start_date ASC
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


def check_coverage_overlap(
    customer: str,
    proposed_start: date,
    proposed_end: date,
    exclude_cancelled: bool = True,
) -> OverlapCheckResult:
    """
    Check if proposed coverage period overlaps with any existing invoices.

    This is the main entry point for overlap detection. Returns a structured
    result with details about any overlapping invoices found.

    Args:
        customer: Customer name to check invoices for
        proposed_start: Start date of proposed coverage period
        proposed_end: End date of proposed coverage period
        exclude_cancelled: If True, excludes cancelled invoices

    Returns:
        OverlapCheckResult with overlap details and recommendation
    """
    proposed_start = getdate(proposed_start)
    proposed_end = getdate(proposed_end)

    overlapping = find_overlapping_invoices(
        customer=customer,
        proposed_start=proposed_start,
        proposed_end=proposed_end,
        exclude_cancelled=exclude_cancelled,
    )

    if not overlapping:
        return OverlapCheckResult(
            has_overlap=False,
            overlapping_invoices=[],
            exact_match=None,
            reason="No overlapping invoices found",
        )

    # Check for exact match. Callers use exact_match to decide what a payment can be
    # allocated to, and only a submitted invoice can be - so when a draft and a
    # submitted invoice share the period, prefer the submitted one. The query orders by
    # coverage start date, which is tied in that case, so without this the winner would
    # be whatever the storage engine happened to return first, and picking the draft
    # costs a real allocation. The list itself is left in query order for the callers
    # that report every overlapping invoice.
    exact_matches = [
        inv
        for inv in overlapping
        if getdate(inv["custom_coverage_start_date"]) == proposed_start
        and getdate(inv["custom_coverage_end_date"]) == proposed_end
    ]
    submitted_match = next((inv for inv in exact_matches if inv.get("docstatus") == 1), None)
    exact_match = (submitted_match or exact_matches[0])["name"] if exact_matches else None

    # Build reason message
    invoice_names = [inv["name"] for inv in overlapping]
    if exact_match:
        reason = (
            f"Exact duplicate: Invoice {exact_match} already covers " f"{proposed_start} to {proposed_end}"
        )
    else:
        reason = (
            f"Coverage overlap: Invoice(s) {', '.join(invoice_names)} have "
            f"overlapping coverage with proposed period {proposed_start} to {proposed_end}"
        )

    return OverlapCheckResult(
        has_overlap=True,
        overlapping_invoices=overlapping,
        exact_match=exact_match,
        reason=reason,
    )


def find_exact_coverage_invoice(
    customer: str,
    coverage_start: date,
    coverage_end: date,
    only_submitted: bool = True,
    only_with_outstanding: bool = False,
) -> Optional[str]:
    """
    Find an invoice with exact matching coverage dates.

    This is a convenience function for cases where you need to find or link
    to an existing invoice with the exact same coverage period.

    Args:
        customer: Customer name
        coverage_start: Exact coverage start date to match
        coverage_end: Exact coverage end date to match
        only_submitted: If True, only returns submitted invoices (docstatus=1)
        only_with_outstanding: If True, only returns invoices with outstanding > 0

    Returns:
        Invoice name if found, None otherwise
    """
    filters = {
        "customer": customer,
        "custom_coverage_start_date": getdate(coverage_start),
        "custom_coverage_end_date": getdate(coverage_end),
    }

    if only_submitted:
        filters["docstatus"] = 1
    else:
        filters["docstatus"] = ["<", 2]  # Not cancelled

    if only_with_outstanding:
        filters["outstanding_amount"] = [">", 0]

    return frappe.db.get_value("Sales Invoice", filters=filters, fieldname="name")


def get_member_coverage_gaps(
    customer: str,
    from_date: date,
    to_date: date,
) -> List[dict]:
    """
    Identify gaps in coverage for a member within a date range.

    Useful for understanding what periods need invoicing vs what's already covered.

    Args:
        customer: Customer name
        from_date: Start of analysis period
        to_date: End of analysis period

    Returns:
        List of gap dicts with 'start' and 'end' dates
    """
    from_date = getdate(from_date)
    to_date = getdate(to_date)

    # Get all invoices in the date range
    invoices = frappe.db.sql(
        """
        SELECT custom_coverage_start_date, custom_coverage_end_date
        FROM `tabSales Invoice`
        WHERE customer = %(customer)s
        AND docstatus = 1
        AND custom_coverage_start_date IS NOT NULL
        AND custom_coverage_end_date IS NOT NULL
        AND custom_coverage_end_date >= %(from_date)s
        AND custom_coverage_start_date <= %(to_date)s
        ORDER BY custom_coverage_start_date ASC
        """,
        {"customer": customer, "from_date": from_date, "to_date": to_date},
        as_dict=True,
    )

    if not invoices:
        # No coverage at all - entire period is a gap
        return [{"start": from_date, "end": to_date}]

    gaps = []
    current_date = from_date

    for inv in invoices:
        inv_start = getdate(inv["custom_coverage_start_date"])
        inv_end = getdate(inv["custom_coverage_end_date"])

        # Gap before this invoice?
        if inv_start > current_date:
            gap_end = min(inv_start, to_date)
            if gap_end > current_date:
                gaps.append({"start": current_date, "end": gap_end})

        # Move current_date past this invoice's coverage (add 1 day since coverage is inclusive)
        if inv_end >= current_date:
            current_date = inv_end + timedelta(days=1)

    # Gap after all invoices?
    if current_date < to_date:
        gaps.append({"start": current_date, "end": to_date})

    return gaps
