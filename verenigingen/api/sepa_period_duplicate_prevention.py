"""
SEPA Period-Based Duplicate Prevention
Prevents double invoicing for the same dues schedule period
"""

from datetime import datetime, timedelta
from typing import Dict, List

import frappe
from frappe import _
from frappe.utils import add_months, flt, get_first_day, get_last_day, getdate

from verenigingen.utils.security.api_security_framework import OperationType, critical_api

# =============================================================================
# PERIOD-BASED DUPLICATE PREVENTION
# =============================================================================


def check_period_invoicing_duplicates(
    member_name: str, period_start: str, period_end: str, membership_type: str = None
) -> Dict:
    """
    Check if member has already been invoiced for a specific period

    Args:
        member_name: Member document name
        period_start: Start date of billing period (YYYY-MM-DD)
        period_end: End date of billing period (YYYY-MM-DD)
        membership_type: Optional membership type filter

    Returns:
        Dict with duplicate status and existing invoices

    Raises:
        ValidationError: If duplicates found and strict mode enabled
    """
    try:
        # Get member details
        member = frappe.get_doc("Member", member_name)
        if not member.customer:
            return {"has_duplicates": False, "reason": "No customer linked to member"}

        # Build search filters
        filters = {
            "customer": member.customer,
            "docstatus": ["!=", 2],  # Not cancelled
            "posting_date": ["between", [period_start, period_end]],
        }

        # Get existing invoices in the period
        existing_invoices = frappe.get_all(
            "Sales Invoice",
            filters=filters,
            fields=[
                "name",
                "posting_date",
                "grand_total",
                "status",
                "docstatus",
                "remarks",
            ],
        )

        # Filter for membership-related invoices
        membership_invoices = []
        for invoice in existing_invoices:
            # Check if invoice contains membership-related items
            invoice_items = frappe.get_all(
                "Sales Invoice Item",
                filters={"parent": invoice.name},
                fields=["item_code", "item_name", "description", "amount"],
            )

            # Identify membership invoices by item codes or descriptions
            is_membership_invoice = any(_is_membership_item(item) for item in invoice_items)

            if is_membership_invoice:
                invoice["items"] = invoice_items
                membership_invoices.append(invoice)

        # Check for exact period overlaps
        period_duplicates = []
        for invoice in membership_invoices:
            # Calculate period from posting_date (monthly period)
            invoice_period_start, invoice_period_end = _calculate_monthly_period_from_posting_date(
                invoice.posting_date
            )

            # Check if periods overlap
            if _periods_overlap(period_start, period_end, invoice_period_start, invoice_period_end):
                period_duplicates.append(
                    {
                        "invoice": invoice.name,
                        "posting_date": invoice.posting_date,
                        "amount": invoice.grand_total,
                        "period_start": invoice_period_start,
                        "period_end": invoice_period_end,
                        "overlap_type": _get_overlap_type(
                            period_start,
                            period_end,
                            invoice_period_start,
                            invoice_period_end,
                        ),
                    }
                )

        # Determine result
        has_duplicates = len(period_duplicates) > 0

        result = {
            "has_duplicates": has_duplicates,
            "member": member_name,
            "customer": member.customer,
            "period_start": period_start,
            "period_end": period_end,
            "existing_invoices": len(membership_invoices),
            "period_duplicates": period_duplicates,
            "total_amount_in_period": sum(flt(inv.grand_total) for inv in membership_invoices),
        }

        # Check if strict mode is enabled
        if has_duplicates and _is_strict_mode_enabled():
            raise frappe.ValidationError(
                _(
                    "Member {0} already has invoices for period {1} to {2}. Found {3} overlapping invoice(s): {4}"
                ).format(
                    member.full_name,
                    period_start,
                    period_end,
                    len(period_duplicates),
                    ", ".join([dup["invoice"] for dup in period_duplicates[:3]]),
                )
            )

        return result

    except Exception as e:
        frappe.log_error(f"Error checking period duplicates for member {member_name}: {str(e)}")
        return {"has_duplicates": False, "error": str(e), "member": member_name}


def check_dues_schedule_period_duplicates(
    dues_schedule_name: str, period_start: str, period_end: str
) -> Dict:
    """
    Check if dues schedule has already generated invoices for a specific period

    Args:
        dues_schedule_name: Membership Dues Schedule document name
        period_start: Start date of billing period
        period_end: End date of billing period

    Returns:
        Dict with duplicate status and existing invoices
    """
    try:
        # Get dues schedule details
        dues_schedule = frappe.get_doc("Membership Dues Schedule", dues_schedule_name)

        # Get member's customer
        member = frappe.get_doc("Member", dues_schedule.member)
        if not member.customer:
            return {"has_duplicates": False, "reason": "No customer linked to member"}

        # Get all invoices for this member within the period
        member_invoices = frappe.get_all(
            "Sales Invoice",
            filters={
                "customer": member.customer,
                "docstatus": ["!=", 2],
                "posting_date": ["between", [period_start, period_end]],
            },
            fields=[
                "name",
                "posting_date",
                "grand_total",
                "status",
                "docstatus",
                "remarks",
            ],
        )

        # Check for period overlaps
        overlapping_invoices = []
        for invoice in member_invoices:
            # Calculate monthly period from posting date
            invoice_start, invoice_end = _calculate_monthly_period_from_posting_date(invoice.posting_date)

            if _periods_overlap(period_start, period_end, invoice_start, invoice_end):
                overlapping_invoices.append(
                    {
                        "invoice": invoice.name,
                        "posting_date": invoice.posting_date,
                        "from_date": invoice_start,
                        "to_date": invoice_end,
                        "amount": invoice.grand_total,
                        "status": invoice.status,
                    }
                )

        has_duplicates = len(overlapping_invoices) > 0

        return {
            "has_duplicates": has_duplicates,
            "dues_schedule": dues_schedule_name,
            "member": dues_schedule.member,
            "customer": member.customer,
            "period_start": period_start,
            "period_end": period_end,
            "overlapping_invoices": overlapping_invoices,
            "total_member_invoices": len(member_invoices),
        }

    except Exception as e:
        frappe.log_error(f"Error checking dues schedule period duplicates: {str(e)}")
        return {"has_duplicates": False, "error": str(e), "dues_schedule": dues_schedule_name}


def prevent_sepa_batch_period_duplicates(batch_name: str) -> Dict:
    """
    Check if SEPA batch contains invoices that duplicate existing periods

    Args:
        batch_name: SEPA Direct Debit Batch name

    Returns:
        Validation result with any period conflicts
    """
    try:
        # Get SEPA batch
        batch = frappe.get_doc("Direct Debit Batch", batch_name)

        conflicts = []
        validated_items = []

        for item in batch.invoices:
            # Get invoice details
            invoice = frappe.get_doc("Sales Invoice", item.sales_invoice)

            # Determine billing period from invoice (calculate monthly period)
            period_start, period_end = _calculate_monthly_period_from_posting_date(invoice.posting_date)

            # Check for period duplicates
            duplicate_check = check_period_invoicing_duplicates(
                member_name=_get_member_from_customer(invoice.customer),
                period_start=period_start,
                period_end=period_end,
            )

            if duplicate_check.get("has_duplicates"):
                conflicts.append(
                    {
                        "invoice": item.sales_invoice,
                        "customer": invoice.customer,
                        "period_start": period_start,
                        "period_end": period_end,
                        "existing_duplicates": duplicate_check["period_duplicates"],
                    }
                )
            else:
                validated_items.append(
                    {
                        "invoice": item.sales_invoice,
                        "customer": invoice.customer,
                        "period_start": period_start,
                        "period_end": period_end,
                    }
                )

        has_conflicts = len(conflicts) > 0

        result = {
            "batch": batch_name,
            "has_conflicts": has_conflicts,
            "total_items": len(batch.invoices),
            "validated_items_count": len(validated_items),
            "conflict_items": len(conflicts),
            "conflicts": conflicts,
            "validated_items": validated_items[:10],  # Limit for display
        }

        if has_conflicts and _is_strict_mode_enabled():
            raise frappe.ValidationError(
                _(
                    "SEPA batch {0} contains {1} invoice(s) with period conflicts. Cannot process batch with duplicate periods."
                ).format(batch_name, len(conflicts))
            )

        return result

    except Exception as e:
        frappe.log_error(f"Error validating SEPA batch periods: {str(e)}")
        return {"batch": batch_name, "has_conflicts": False, "error": str(e)}


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================


def _is_membership_item(item: Dict) -> bool:
    """Check if invoice item is membership-related"""
    membership_keywords = [
        "membership",
        "lidmaatschap",
        "contributie",
        "dues_schedule",
        "fee",
        "dues",
        "annual",
        "monthly",
        "yearly",
    ]

    item_text = " ".join(
        [item.get("item_code", ""), item.get("item_name", ""), item.get("description", "")]
    ).lower()

    return any(keyword in item_text for keyword in membership_keywords)


def _periods_overlap(start1: str, end1: str, start2: str, end2: str) -> bool:
    """Check if two date periods overlap"""
    if not all([start1, end1, start2, end2]):
        return False

    try:
        s1 = getdate(start1)
        e1 = getdate(end1)
        s2 = getdate(start2)
        e2 = getdate(end2)

        # Periods overlap if: start1 <= end2 AND start2 <= end1
        return s1 <= e2 and s2 <= e1

    except Exception:
        return False


def _get_overlap_type(start1: str, end1: str, start2: str, end2: str) -> str:
    """Determine the type of period overlap"""
    if not _periods_overlap(start1, end1, start2, end2):
        return "none"

    try:
        s1, e1 = getdate(start1), getdate(end1)
        s2, e2 = getdate(start2), getdate(end2)

        if s1 == s2 and e1 == e2:
            return "exact"
        elif s1 >= s2 and e1 <= e2:
            return "contained"
        elif s2 >= s1 and e2 <= e1:
            return "contains"
        elif s1 < s2:
            return "partial_end"
        else:
            return "partial_start"

    except Exception:
        return "unknown"


def _get_member_from_customer(customer_name: str) -> str:
    """Get member name from customer"""
    member_name = frappe.db.get_value("Member", {"customer": customer_name}, "name")
    return member_name or customer_name


def _is_strict_mode_enabled() -> bool:
    """Check if strict period duplicate prevention is enabled"""
    # Check system setting or default to True for safety
    return frappe.db.get_single_value("Verenigingen Settings", "sepa_strict_period_mode") != 0


# =============================================================================
# MEMBERSHIP BILLING PERIOD FUNCTIONS
# =============================================================================


def generate_membership_billing_periods(
    member_name: str, start_date: str, billing_frequency: str = "Monthly"
) -> List[Dict]:
    """
    Generate standard billing periods for a member

    Args:
        member_name: Member document name
        start_date: Start date for period generation
        billing_frequency: Monthly, Quarterly, Yearly

    Returns:
        List of billing periods with start/end dates
    """
    periods = []
    current_date = getdate(start_date)

    # Determine period increment
    if billing_frequency == "Monthly":
        increment_months = 1
        period_count = 12  # Generate one year
    elif billing_frequency == "Quarterly":
        increment_months = 3
        period_count = 4
    elif billing_frequency == "Yearly":
        increment_months = 12
        period_count = 1
    else:
        raise frappe.ValidationError(f"Unsupported billing frequency: {billing_frequency}")

    for i in range(period_count):
        period_start = add_months(current_date, i * increment_months)
        period_end = add_months(period_start, increment_months) - timedelta(days=1)

        periods.append(
            {
                "period_number": i + 1,
                "period_start": period_start.strftime("%Y-%m-%d"),
                "period_end": period_end.strftime("%Y-%m-%d"),
                "period_description": f"{billing_frequency} period {i + 1}",
                "billing_frequency": billing_frequency,
            }
        )

    return periods


def _calculate_monthly_period_from_posting_date(posting_date):
    """
    Calculate monthly billing period from posting date

    Args:
        posting_date: Date string or date object

    Returns:
        tuple: (period_start, period_end) as date strings
    """
    try:
        posting_date = getdate(posting_date)
        period_start = get_first_day(posting_date)
        period_end = get_last_day(posting_date)
        return period_start.strftime("%Y-%m-%d"), period_end.strftime("%Y-%m-%d")
    except Exception:
        # Fallback to using posting_date as both start and end
        date_str = str(posting_date) if posting_date else str(getdate())
        return date_str, date_str


def validate_invoice_period_fields(invoice_doc) -> None:
    """
    Validate and auto-populate period fields on invoice
    Called from invoice validation hooks
    """
    if not invoice_doc.customer:
        return

    # Check if this is a membership invoice
    has_membership_items = any(
        _is_membership_item(
            {"item_code": item.item_code, "item_name": item.item_name, "description": item.description}
        )
        for item in invoice_doc.items
    )

    if not has_membership_items:
        return

    # Calculate billing period from posting date (monthly period)
    period_start, period_end = _calculate_monthly_period_from_posting_date(invoice_doc.posting_date)

    # Check for period duplicates if strict mode enabled
    if _is_strict_mode_enabled():
        member_name = _get_member_from_customer(invoice_doc.customer)
        if member_name:
            check_period_invoicing_duplicates(
                member_name=member_name,
                period_start=period_start,
                period_end=period_end,
            )
            # Note: This will raise ValidationError if duplicates found


# =============================================================================
# REPORTING FUNCTIONS
# =============================================================================


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def generate_period_duplicate_report(date_range: str = "Last 3 Months") -> Dict:
    """
    Generate comprehensive report on period duplicates

    Args:
        date_range: "Last Month", "Last 3 Months", "Last Year"

    Returns:
        Report with duplicate analysis
    """
    # Determine date range
    if date_range == "Last Month":
        start_date = add_months(getdate(), -1)
    elif date_range == "Last 3 Months":
        start_date = add_months(getdate(), -3)
    elif date_range == "Last Year":
        start_date = add_months(getdate(), -12)
    else:
        start_date = add_months(getdate(), -3)

    end_date = getdate()

    # Get all membership invoices in date range
    membership_invoices = frappe.get_all(
        "Sales Invoice",
        filters={"posting_date": ["between", [start_date, end_date]], "docstatus": ["!=", 2]},
        fields=[
            "name",
            "customer",
            "posting_date",
            "grand_total",
            "remarks",
        ],
    )

    # Filter for membership invoices
    filtered_invoices = []
    for invoice in membership_invoices:
        invoice_items = frappe.get_all(
            "Sales Invoice Item",
            filters={"parent": invoice.name},
            fields=["item_code", "item_name", "description"],
        )

        if any(_is_membership_item(item) for item in invoice_items):
            filtered_invoices.append(invoice)

    # Group by customer and analyze periods
    customer_analysis = {}
    total_duplicates = 0

    for invoice in filtered_invoices:
        customer = invoice.customer
        if customer not in customer_analysis:
            customer_analysis[customer] = {"invoices": [], "periods": [], "duplicates": []}

        customer_analysis[customer]["invoices"].append(invoice)

        # Check for period overlaps with other invoices
        period_start, period_end = _calculate_monthly_period_from_posting_date(invoice.posting_date)

        for other_invoice in customer_analysis[customer]["invoices"][:-1]:
            other_start, other_end = _calculate_monthly_period_from_posting_date(other_invoice.posting_date)

            if _periods_overlap(period_start, period_end, other_start, other_end):
                duplicate_entry = {
                    "invoice1": invoice.name,
                    "invoice2": other_invoice.name,
                    "period_start": period_start,
                    "period_end": period_end,
                    "overlap_type": _get_overlap_type(period_start, period_end, other_start, other_end),
                    "amount1": invoice.grand_total,
                    "amount2": other_invoice.grand_total,
                }
                customer_analysis[customer]["duplicates"].append(duplicate_entry)
                total_duplicates += 1

    # Generate summary
    summary = {
        "date_range": f"{start_date} to {end_date}",
        "total_membership_invoices": len(filtered_invoices),
        "customers_analyzed": len(customer_analysis),
        "customers_with_duplicates": sum(1 for c in customer_analysis.values() if c["duplicates"]),
        "total_duplicate_pairs": total_duplicates,
        "potential_overcharged_amount": sum(
            min(dup["amount1"], dup["amount2"])
            for customer_data in customer_analysis.values()
            for dup in customer_data["duplicates"]
        ),
    }

    # Top 10 customers with most duplicates
    top_duplicates = sorted(
        [
            (customer, len(data["duplicates"]))
            for customer, data in customer_analysis.items()
            if data["duplicates"]
        ],
        key=lambda x: x[1],
        reverse=True,
    )[:10]

    return {
        "summary": summary,
        "top_duplicate_customers": top_duplicates,
        "detailed_analysis": {k: v for k, v in customer_analysis.items() if v["duplicates"]},
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
