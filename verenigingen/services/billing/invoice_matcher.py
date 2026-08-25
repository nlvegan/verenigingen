# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Invoice Matcher Service - Centralized invoice matching for payments.

Consolidates invoice matching logic from:
- BulkPaymentChecker.find_matching_unpaid_dues_invoice() - SQL-based matching with buffer
- payment_processing_recovery - Coverage-based matching with overlap detection

Provides a single source of truth for matching payments to unpaid dues invoices.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, Union

import frappe

from verenigingen.verenigingen_payments.utils.invoice_candidates import (
    InvoiceChoice,
    choose_unambiguous,
    log_ambiguous_refusal,
    unambiguous_invoice,
)

# Configuration constants (from BulkPaymentChecker)
INVOICE_MATCH_BUFFER_MONTHS = 3  # Allow matching within 3 months of coverage period
INVOICE_AMOUNT_TOLERANCE_EUR = 0.01  # 1 cent tolerance for floating-point comparison


@dataclass
class InvoiceMatchResult:
    """
    Result of invoice matching operation.

    Attributes:
        invoice_name: Matched invoice name or None if no match
        match_type: Type of match found:
            - 'exact_coverage': Payment date falls within invoice coverage period
            - 'within_buffer': Payment date within buffer period (3 months)
            - 'coverage_calculated': Matched via calculated coverage period
            - None: No match found
        invoice_amount: Invoice grand_total if matched
        outstanding_amount: Invoice outstanding_amount if matched
        coverage_start: Invoice coverage start date if matched
        coverage_end: Invoice coverage end date if matched
        overlap_warning: Warning message if coverage overlap detected
        ambiguous_candidates: How many candidates the matcher REFUSED to choose
            between, or None if it never faced a choice. A caller has to be able to
            tell "no invoice this payment could be for" from "several, and picking one
            would be a guess" -- they are different operator-facing outcomes, and #567
            asks specifically that the second be visible rather than resolved silently
            by an ORDER BY.
    """

    invoice_name: Optional[str]
    match_type: Optional[str]
    invoice_amount: Optional[float] = None
    outstanding_amount: Optional[float] = None
    coverage_start: Optional[date] = None
    coverage_end: Optional[date] = None
    overlap_warning: Optional[str] = None
    ambiguous_candidates: Optional[int] = None

    @property
    def found(self) -> bool:
        """Whether a matching invoice was found."""
        return self.invoice_name is not None

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "invoice_name": self.invoice_name,
            "match_type": self.match_type,
            "invoice_amount": self.invoice_amount,
            "outstanding_amount": self.outstanding_amount,
            "coverage_start": str(self.coverage_start) if self.coverage_start else None,
            "coverage_end": str(self.coverage_end) if self.coverage_end else None,
            "overlap_warning": self.overlap_warning,
            "ambiguous_candidates": self.ambiguous_candidates,
            "found": self.found,
        }


def find_matching_invoice(
    member_name: str,
    payment_date: Union[date, datetime],
    payment_amount: Union[float, Decimal],
    check_overlap: bool = True,
) -> InvoiceMatchResult:
    """
    Find best matching unpaid dues invoice for a member payment.

    This is the primary entry point for invoice matching. It combines:
    1. Direct SQL matching (finds invoices where payment date falls within coverage + buffer)
    2. Coverage-based matching (calculates expected coverage from member's billing frequency)

    Matching priority:
    1. Payment date within invoice coverage period (exact_coverage)
    2. Payment date within 3-month buffer of coverage period (within_buffer)
    3. Coverage calculated from member's billing frequency (coverage_calculated)

    Args:
        member_name: Member record name
        payment_date: Payment date (datetime or date)
        payment_amount: Payment amount in EUR
        check_overlap: If True, warns about coverage overlaps

    Returns:
        InvoiceMatchResult with match details or empty result if no match
    """
    # Validate and convert payment_date to date
    if isinstance(payment_date, datetime):
        payment_date_only = payment_date.date()
    elif isinstance(payment_date, date):
        payment_date_only = payment_date
    else:
        raise ValueError(f"payment_date must be date or datetime, got {type(payment_date).__name__}")

    # Convert payment_amount to float
    payment_amount_float = float(payment_amount)

    # Get member's customer
    customer = frappe.db.get_value("Member", member_name, "customer")
    if not customer:
        return InvoiceMatchResult(
            invoice_name=None,
            match_type=None,
            overlap_warning="Member has no linked customer",
        )

    # Strategy 1: Direct SQL matching with coverage + buffer
    sql_choice = _find_invoice_by_coverage_sql(
        customer=customer,
        payment_date=payment_date_only,
        payment_amount=payment_amount_float,
    )
    sql_match = sql_choice.invoice

    if sql_match:
        result = InvoiceMatchResult(
            invoice_name=sql_match["name"],
            match_type=sql_match["match_type"],
            invoice_amount=float(sql_match["grand_total"]),
            outstanding_amount=float(sql_match["outstanding_amount"]),
            coverage_start=sql_match["custom_coverage_start_date"],
            coverage_end=sql_match["custom_coverage_end_date"],
        )

        # Check for overlap warnings if requested
        if check_overlap:
            overlap_warning = _check_for_overlap_warning(
                customer=customer,
                coverage_start=result.coverage_start,
                coverage_end=result.coverage_end,
                exclude_invoice=result.invoice_name,
            )
            if overlap_warning:
                result.overlap_warning = overlap_warning

        return result

    # Strategy 2: Calculate coverage from member's billing frequency.
    # Runs even when strategy 1 REFUSED, because it narrows on different evidence: an
    # invoice whose coverage period equals the one calculated from the member's own
    # billing sequence is better attested than "one of several invoices near this
    # date". Narrowing by real evidence is not the arbitrary pick #567 forbids.
    calculated_choice = _find_invoice_by_calculated_coverage(
        member_name=member_name,
        customer=customer,
        payment_date=payment_date_only,
        payment_amount=payment_amount_float,
    )
    calculated_match = calculated_choice.invoice

    # ...but it must not LAUNDER the refusal. Strategy 2 answers a different question --
    # which window does this date fall in -- and its answer can be an invoice strategy 1
    # never had as a candidate, because the SQL filters on the amount. Accepting one of
    # those would reproduce exactly the harm #578 describes: with two equal-amount
    # invoices in arrears and a third, differently-priced invoice covering the payment
    # date, the money would go to the third and both arrears stay open, with nothing
    # logged. Narrowing WITHIN the refused set is the legitimate case, and the only one.
    if calculated_match and sql_choice.is_ambiguous:
        if calculated_match["name"] not in sql_choice.candidate_names:
            calculated_match = None

    if calculated_match:
        result = InvoiceMatchResult(
            invoice_name=calculated_match["name"],
            match_type="coverage_calculated",
            invoice_amount=float(calculated_match["grand_total"]),
            outstanding_amount=float(calculated_match["outstanding_amount"]),
            coverage_start=calculated_match["custom_coverage_start_date"],
            coverage_end=calculated_match["custom_coverage_end_date"],
        )

        if check_overlap:
            overlap_warning = _check_for_overlap_warning(
                customer=customer,
                coverage_start=result.coverage_start,
                coverage_end=result.coverage_end,
                exclude_invoice=result.invoice_name,
            )
            if overlap_warning:
                result.overlap_warning = overlap_warning

        return result

    # Neither strategy resolved one. Refusing because there were SEVERAL candidates is
    # a different outcome from finding none, and the caller allocates money on the
    # answer, so it is reported rather than flattened into "no match".
    refused = sql_choice if sql_choice.is_ambiguous else calculated_choice
    if refused.is_ambiguous:
        _log_ambiguous_match(
            customer=customer,
            payment_date=payment_date_only,
            payment_amount=payment_amount_float,
            refused=refused,
        )
        return InvoiceMatchResult(
            invoice_name=None,
            match_type=None,
            ambiguous_candidates=refused.candidates,
        )

    # No match found
    return InvoiceMatchResult(invoice_name=None, match_type=None)


def _log_ambiguous_match(
    customer: str,
    payment_date: date,
    payment_amount: float,
    refused: InvoiceChoice,
) -> None:
    """Record a refusal where an operator will actually find it."""
    log_ambiguous_refusal(
        title="Invoice Match Ambiguous",
        refused=refused,
        detail=(
            f"Refused to choose between {refused.candidates} candidate invoices for a "
            f"payment of {payment_amount} on {payment_date} from customer {customer}. "
            f"No payment was allocated; allocate it manually to the intended invoice."
        ),
    )


def _find_invoice_by_coverage_sql(
    customer: str,
    payment_date: date,
    payment_amount: float,
) -> InvoiceChoice:
    """
    Find invoice using SQL with coverage period and buffer matching.

    Uses CASE to rank invoices where the payment date falls within the coverage period
    above invoices merely within the buffer period. That ranking is a FILTER, not a
    tie-break: it narrows the candidate set on real evidence, and whatever survives it
    goes through the shared #567 rule.

    This query used to end `ORDER BY match_priority ASC, custom_coverage_start_date
    DESC LIMIT 1`, which meant the second key decided every tie the first one left --
    so a member two months in arrears on a flat fee, paying late, had the money
    allocated to the NEWEST period while the oldest stayed open (#578). Raw SQL is also
    why PR #575's AST sweep could not see this site at all.

    Args:
        customer: Customer name
        payment_date: Payment date
        payment_amount: Payment amount in EUR

    Returns:
        InvoiceChoice -- the one invoice, or a refusal carrying the candidate count
    """
    invoices = frappe.db.sql(
        f"""
        SELECT
            name,
            grand_total,
            outstanding_amount,
            custom_coverage_start_date,
            custom_coverage_end_date,
            posting_date,
            CASE
                WHEN %(payment_date)s BETWEEN custom_coverage_start_date AND custom_coverage_end_date
                THEN 0
                ELSE 1
            END as match_priority
        FROM `tabSales Invoice`
        WHERE customer = %(customer)s
          AND is_membership_invoice = 1
          AND docstatus = 1
          AND outstanding_amount > 0
          AND ABS(grand_total - %(amount)s) < {INVOICE_AMOUNT_TOLERANCE_EUR}
          AND custom_coverage_start_date IS NOT NULL
          AND custom_coverage_end_date IS NOT NULL
          AND %(payment_date)s BETWEEN
              DATE_SUB(custom_coverage_start_date, INTERVAL {INVOICE_MATCH_BUFFER_MONTHS} MONTH)
              AND DATE_ADD(custom_coverage_end_date, INTERVAL {INVOICE_MATCH_BUFFER_MONTHS} MONTH)
        ORDER BY match_priority ASC, custom_coverage_start_date DESC
        """,
        {
            "customer": customer,
            "payment_date": payment_date,
            "amount": payment_amount,
        },
        as_dict=True,
    )

    # Prefer the invoices whose coverage period actually CONTAINS the payment date.
    # Every row here already passed the amount filter in the SQL above, so among a set
    # that all agree on the amount the coverage window is the only real discriminator
    # left -- and it is a discriminator, unlike the start-date ordering it replaces.
    inside_window = [row for row in invoices if row["match_priority"] == 0]
    candidates = inside_window or invoices

    # `outstanding_amount`, NOT `grand_total`. The SQL above already filters on
    # `grand_total`, so comparing on it again is inert -- every surviving row matches, so
    # rule 2 could never separate anything and this degenerated to "one candidate or
    # refuse". Outstanding is also the right question for an incoming payment (what is
    # still owed): invoice A grand_total 25 / outstanding 25 and invoice B grand_total 25
    # / outstanding 5 both pass the SQL, and only A is an invoice with 25 still owed.
    choice = choose_unambiguous(candidates, payment_amount, "outstanding_amount")
    if choice.invoice:
        choice.invoice["match_type"] = (
            "exact_coverage" if choice.invoice["match_priority"] == 0 else "within_buffer"
        )
    return choice


def _find_invoice_by_calculated_coverage(
    member_name: str,
    customer: str,
    payment_date: date,
    payment_amount: float,
) -> InvoiceChoice:
    """
    Find invoice by calculating expected coverage period from member's billing frequency.

    This handles cases where the payment amount doesn't match exactly but the
    coverage period does (e.g., price changes) -- rule 1 of the shared #567 rule keeps
    that working: ONE candidate is the match whatever the amount. The amount is only
    consulted to separate SEVERAL candidates, where previously there was nothing: this
    was a `frappe.db.get_value` with no `order_by`, i.e. `creation DESC`, so it silently
    returned the most recently created of however many invoices share the window.

    PR #575 cleared this site on the reasoning that `(customer, coverage_start,
    coverage_end)` is unique. It is not, and this codebase says so itself by shipping
    `coverage_overlap_detector.find_overlapping_invoices` and
    `_check_for_overlap_warning` below -- which used to WARN about the sibling invoice
    while the money was allocated to the other one anyway (#578).

    Args:
        member_name: Member record name
        customer: Customer name
        payment_date: Payment date
        payment_amount: Payment amount. NOT used to choose -- see the amount=None note
            below; kept because the caller and the log message need it.

    Returns:
        InvoiceChoice -- the one invoice, or a refusal carrying the candidate count
    """
    try:
        from verenigingen.services.billing.coverage_calculator import calculate_coverage_for_payment_date

        coverage_start, coverage_end = calculate_coverage_for_payment_date(member_name, payment_date)

        # `amount=None` deliberately: the whole point of this strategy is that the
        # amount is NOT evidence here -- it exists so a price change still matches on
        # coverage alone. Handing the payment amount to rule 2 would be worse than no
        # discriminator: a duplicate on this window usually EXISTS because the price
        # changed, so the invoice matching an unchanged standing order is the stale one,
        # and rule 2 would pick it every time rather than sometimes. With no amount,
        # one candidate still wins (rule 1, unchanged) and several are refused.
        return unambiguous_invoice(
            filters={
                "customer": customer,
                "custom_coverage_start_date": coverage_start,
                "custom_coverage_end_date": coverage_end,
                "docstatus": 1,
                "outstanding_amount": [">", 0],
            },
            amount=None,
            fields=[
                "name",
                "grand_total",
                "outstanding_amount",
                "custom_coverage_start_date",
                "custom_coverage_end_date",
            ],
        )

    except Exception as e:
        # This handler still SWALLOWS -- deliberately: strategy 2 is a fallback, and a
        # coverage-calculation failure should not fail the whole match. But it dropped
        # out of `scripts/validation/error_swallow_baseline.txt` when the return changed
        # from `None` to `InvoiceChoice(None, 0)`, because `_is_falsy_return` recognises
        # only literals and this is an `ast.Call`. The swallow did not go away; the
        # RATCHET went blind to it. So the observability the baseline entry stood for is
        # made explicit here instead: `frappe.logger()` writes to a rotating file at
        # level ERROR with `propagate=False`, so a `.warning` from CI reaches nobody
        # (CLAUDE.md records this as having caused three defects). Blind spot filed.
        frappe.log_error(
            title="Invoice Coverage Calculation Failed",
            message=(
                f"Could not calculate a coverage period for member {member_name} on "
                f"{payment_date}, so the coverage strategy contributed no candidates "
                f"for a payment of {payment_amount}: {e}"
            ),
        )
        return InvoiceChoice(None, 0)


def _check_for_overlap_warning(
    customer: str,
    coverage_start: date,
    coverage_end: date,
    exclude_invoice: str,
) -> Optional[str]:
    """
    Check if there are other invoices with overlapping coverage.

    Used to warn about potential duplicate coverage, not to prevent matching.

    Args:
        customer: Customer name
        coverage_start: Coverage start date
        coverage_end: Coverage end date
        exclude_invoice: Invoice name to exclude from check

    Returns:
        Warning message if overlaps found, None otherwise
    """
    try:
        from verenigingen.services.billing.coverage_overlap_detector import find_overlapping_invoices

        overlapping = find_overlapping_invoices(
            customer=customer,
            proposed_start=coverage_start,
            proposed_end=coverage_end,
            exclude_cancelled=True,
            only_with_outstanding=False,
        )

        # Filter out the matched invoice and cancelled invoices
        other_overlapping = [
            inv for inv in overlapping if inv["name"] != exclude_invoice and inv.get("docstatus", 0) == 1
        ]

        if other_overlapping:
            names = [inv["name"] for inv in other_overlapping]
            return f"Other invoices with overlapping coverage: {', '.join(names)}"

    except Exception as e:
        frappe.logger().warning(f"Error checking coverage overlap: {e}")

    return None


# Convenience function for SDK payment objects
def find_matching_invoice_for_payment(
    sdk_payment,
    member_name: str,
    check_overlap: bool = True,
) -> InvoiceMatchResult:
    """
    Find matching invoice for a Mollie SDK payment object.

    Convenience wrapper that extracts amount and date from SDK payment
    and delegates to find_matching_invoice.

    Args:
        sdk_payment: Raw Mollie SDK payment object (supports dict-like access)
        member_name: Member record name
        check_overlap: If True, warns about coverage overlaps

    Returns:
        InvoiceMatchResult with match details
    """
    try:
        # Extract amount
        amount_obj = sdk_payment.amount if hasattr(sdk_payment, "amount") else sdk_payment.get("amount")
        if not amount_obj:
            return InvoiceMatchResult(
                invoice_name=None,
                match_type=None,
                overlap_warning="Payment has no amount",
            )

        payment_amount = float(
            amount_obj["value"] if isinstance(amount_obj, dict) else amount_obj.get("value")
        )

        # Parse payment date - prefer paid_at for accuracy
        paid_at = getattr(sdk_payment, "paid_at", None) or sdk_payment.get("paidAt")
        created_at = getattr(sdk_payment, "created_at", None) or sdk_payment.get("createdAt")

        date_str = paid_at or created_at
        if not date_str:
            return InvoiceMatchResult(
                invoice_name=None,
                match_type=None,
                overlap_warning="Payment has no date",
            )

        # Parse ISO date string to datetime
        if isinstance(date_str, str):
            payment_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        else:
            payment_date = date_str

        return find_matching_invoice(
            member_name=member_name,
            payment_date=payment_date,
            payment_amount=payment_amount,
            check_overlap=check_overlap,
        )

    except Exception as e:
        frappe.logger().warning(f"Error matching invoice for payment: {e}")
        return InvoiceMatchResult(
            invoice_name=None,
            match_type=None,
            overlap_warning=f"Error: {str(e)}",
        )


# Singleton accessor
_invoice_matcher_instance = None


def get_invoice_matcher():
    """Get singleton InvoiceMatcher instance (for backwards compatibility)."""
    # This module uses functions directly, but this provides a class-like interface
    # if needed for dependency injection or testing
    global _invoice_matcher_instance
    if _invoice_matcher_instance is None:
        _invoice_matcher_instance = InvoiceMatcherService()
    return _invoice_matcher_instance


class InvoiceMatcherService:
    """
    Service wrapper for invoice matching functions.

    Provides a class interface for dependency injection and testing.
    Delegates to module-level functions.
    """

    def find_matching_invoice(
        self,
        member_name: str,
        payment_date: Union[date, datetime],
        payment_amount: Union[float, Decimal],
        check_overlap: bool = True,
    ) -> InvoiceMatchResult:
        """Find best matching unpaid dues invoice."""
        return find_matching_invoice(
            member_name=member_name,
            payment_date=payment_date,
            payment_amount=payment_amount,
            check_overlap=check_overlap,
        )

    def find_matching_invoice_for_payment(
        self,
        sdk_payment,
        member_name: str,
        check_overlap: bool = True,
    ) -> InvoiceMatchResult:
        """Find matching invoice for SDK payment object."""
        return find_matching_invoice_for_payment(
            sdk_payment=sdk_payment,
            member_name=member_name,
            check_overlap=check_overlap,
        )
