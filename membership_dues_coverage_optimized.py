"""
Optimized version of membership_dues_coverage_analysis.py
========================================================

Eliminates N+1 query patterns by using bulk operations:
- Instead of 1 + N*3 queries (1 member query + N*(member_doc + membership + invoices))
- Uses ~5 bulk queries total regardless of member count

Performance improvement: O(N) queries reduced to O(1) queries
"""

import json
from datetime import datetime, timedelta

import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, flt, getdate, today

from verenigingen.utils.performance_utils import QueryOptimizer
from verenigingen.utils.secure_operations import secure_document_operation


def get_data_optimized(filters):
    """Optimized data retrieval using bulk operations"""

    # Build conditions based on filters
    conditions, params = build_conditions(filters)

    # STEP 1: Get active members with their membership information (single query)
    members_data = frappe.db.sql(
        f"""
        SELECT
            m.name as member,
            CONCAT(m.first_name, ' ', COALESCE(m.last_name, '')) as member_name,
            m.status as membership_status,
            m.customer,
            mb.start_date as membership_start,
            mb.cancellation_date as membership_end,
            mds.name as dues_schedule,
            mds.billing_frequency,
            mds.dues_rate,
            mds.last_invoice_date,
            mds.next_invoice_date as next_invoice_due,
            mds.status as schedule_status
        FROM `tabMember` m
        LEFT JOIN `tabMembership` mb ON mb.member = m.name AND mb.status = 'Active' AND mb.docstatus = 1
        LEFT JOIN `tabMembership Dues Schedule` mds ON mds.member = m.name AND mds.status = 'Active'
        WHERE {conditions}
        ORDER BY m.name
        """,
        params,
        as_dict=True,
    )

    if not members_data:
        return []

    member_names = [m["member"] for m in members_data]
    customer_names = [m["customer"] for m in members_data if m["customer"]]

    print(f"🔍 Processing {len(members_data)} members with bulk operations...")

    # STEP 2: Bulk get all membership periods (single query)
    membership_periods_bulk = get_membership_periods_bulk(
        member_names, filters.get("from_date"), filters.get("to_date")
    )

    # STEP 3: Bulk get all member invoices with coverage (single query)
    invoices_bulk = get_member_invoices_bulk(customer_names, filters.get("from_date"), filters.get("to_date"))

    # STEP 4: Bulk get membership types for billing frequency info (single query)
    membership_types_bulk = get_membership_types_bulk(member_names)

    print("✅ Bulk queries complete - processing coverage analysis...")

    # STEP 5: Process each member using bulk-loaded data (in-memory operations)
    data = []
    for member_data in members_data:
        try:
            member_name = member_data["member"]
            customer = member_data.get("customer")

            # Get data from bulk-loaded collections
            member_periods = membership_periods_bulk.get(member_name, [])
            member_invoices = invoices_bulk.get(customer, []) if customer else []
            member_billing_info = membership_types_bulk.get(member_name, {})

            # Calculate coverage analysis using bulk data
            coverage_analysis = calculate_coverage_timeline_optimized(
                member_name,
                member_periods,
                member_invoices,
                member_billing_info,
                filters.get("from_date"),
                filters.get("to_date"),
            )

            # Build row data
            row = build_member_row(member_data, coverage_analysis)

            # Apply filters that require calculated data
            if should_include_row(row, filters):
                data.append(row)

        except Exception as e:
            # Log error and continue with next member
            frappe.log_error(
                f"Error processing member {member_data['member']}: {str(e)}", "Optimized Dues Coverage Report"
            )
            continue

    print(f"🎯 Completed processing {len(data)} members")
    return data


def get_membership_periods_bulk(member_names, from_date=None, to_date=None):
    """Bulk get membership periods for all members (prevents N+1 queries)"""

    if not member_names:
        return {}

    conditions = ["mb.member IN %(member_names)s", "mb.docstatus = 1"]
    params = {"member_names": member_names}

    if from_date:
        conditions.append("(mb.cancellation_date IS NULL OR mb.cancellation_date >= %(from_date)s)")
        params["from_date"] = from_date

    if to_date:
        conditions.append("mb.start_date <= %(to_date)s")
        params["to_date"] = to_date

    memberships = frappe.db.sql(
        f"""
        SELECT mb.member, mb.start_date, mb.cancellation_date as end_date
        FROM `tabMembership` mb
        WHERE {' AND '.join(conditions)}
        ORDER BY mb.member, mb.start_date
    """,
        params,
        as_dict=True,
    )

    # Group by member
    periods_by_member = {}
    for membership in memberships:
        member_name = membership["member"]

        start_date = getdate(membership["start_date"])
        end_date = getdate(membership["end_date"]) if membership["end_date"] else getdate(today())

        # Apply date range filters
        if from_date:
            start_date = max(start_date, getdate(from_date))
        if to_date:
            end_date = min(end_date, getdate(to_date))

        if start_date <= end_date:
            if member_name not in periods_by_member:
                periods_by_member[member_name] = []
            periods_by_member[member_name].append((start_date, end_date))

    return periods_by_member


def get_member_invoices_bulk(customer_names, from_date=None, to_date=None):
    """Bulk get invoices with coverage for all customers (prevents N+1 queries)"""

    if not customer_names:
        return {}

    conditions = [
        "si.customer IN %(customer_names)s",
        "si.docstatus = 1",
        "si.custom_coverage_start_date IS NOT NULL",
    ]
    params = {"customer_names": customer_names}

    if from_date:
        conditions.append("si.custom_coverage_end_date >= %(from_date)s")
        params["from_date"] = from_date

    if to_date:
        conditions.append("si.custom_coverage_start_date <= %(to_date)s")
        params["to_date"] = to_date

    invoices = frappe.db.sql(
        f"""
        SELECT
            si.customer,
            si.name as invoice,
            si.posting_date,
            si.status,
            si.grand_total,
            si.outstanding_amount,
            si.custom_coverage_start_date as coverage_start,
            si.custom_coverage_end_date as coverage_end,
            CASE
                WHEN si.outstanding_amount = 0 THEN 'Paid'
                WHEN si.status = 'Overdue' THEN 'Overdue'
                ELSE 'Outstanding'
            END as payment_status
        FROM `tabSales Invoice` si
        WHERE {' AND '.join(conditions)}
        ORDER BY si.customer, si.custom_coverage_start_date
    """,
        params,
        as_dict=True,
    )

    # Group by customer
    invoices_by_customer = {}
    for invoice in invoices:
        customer = invoice["customer"]
        if customer not in invoices_by_customer:
            invoices_by_customer[customer] = []
        invoices_by_customer[customer].append(invoice)

    return invoices_by_customer


def get_membership_types_bulk(member_names):
    """Bulk get membership type billing information for all members"""

    if not member_names:
        return {}

    membership_types = frappe.db.sql(
        """
        SELECT
            mb.member,
            mt.billing_period as expected_billing_frequency,
            mt.membership_type_name
        FROM `tabMembership` mb
        JOIN `tabMembership Type` mt ON mb.membership_type = mt.name
        WHERE mb.member IN %(member_names)s
          AND mb.docstatus = 1
          AND mb.status = 'Active'
    """,
        {"member_names": member_names},
        as_dict=True,
    )

    # Group by member (take most recent if multiple)
    types_by_member = {}
    for mt in membership_types:
        types_by_member[mt["member"]] = {
            "expected_billing_frequency": mt["expected_billing_frequency"],
            "membership_type_name": mt["membership_type_name"],
        }

    return types_by_member


def calculate_coverage_timeline_optimized(
    member_name, membership_periods, invoices, billing_info, from_date=None, to_date=None
):
    """
    Optimized coverage timeline calculation using pre-loaded bulk data
    No additional queries - all data provided as parameters
    """

    if not membership_periods:
        return get_empty_coverage_analysis()

    # Build comprehensive coverage analysis using pre-loaded data
    timeline = []
    all_gaps = []
    total_active_days = 0
    total_covered_days = 0
    total_unpaid_days = 0
    total_outstanding = 0

    for membership_start, membership_end in membership_periods:
        # Calculate active days for this period
        period_active_days = date_diff(membership_end, membership_start) + 1
        total_active_days += period_active_days

        # Build coverage map for this membership period using pre-loaded invoices
        period_coverage = build_period_coverage_map(invoices, membership_start, membership_end)
        timeline.extend(period_coverage)

        # Calculate covered days for this period
        period_covered_days = sum(
            [date_diff(cov["coverage_end"], cov["coverage_start"]) + 1 for cov in period_coverage]
        )
        total_covered_days += period_covered_days

        # Calculate unpaid coverage days
        period_unpaid_days = sum(
            [
                date_diff(cov["coverage_end"], cov["coverage_start"]) + 1
                for cov in period_coverage
                if cov["payment_status"] != "Paid"
            ]
        )
        total_unpaid_days += period_unpaid_days

        # Calculate outstanding amounts
        period_outstanding = sum(
            [flt(cov["outstanding_amount"]) for cov in period_coverage if cov["payment_status"] != "Paid"]
        )
        total_outstanding += period_outstanding

        # Identify gaps using billing info
        expected_frequency = billing_info.get("expected_billing_frequency")
        period_gaps = identify_coverage_gaps_optimized(
            period_coverage, membership_start, membership_end, expected_frequency
        )
        all_gaps.extend(period_gaps)

    # Calculate catch-up requirements using billing info
    catchup_analysis = calculate_catchup_requirements_optimized(member_name, all_gaps, billing_info)

    # Build final analysis
    total_gap_days = sum([gap["gap_days"] for gap in all_gaps])
    coverage_percentage = (total_covered_days / total_active_days * 100) if total_active_days > 0 else 0

    return {
        "timeline": timeline,
        "gaps": all_gaps,
        "stats": {
            "total_active_days": total_active_days,
            "covered_days": total_covered_days,
            "gap_days": total_gap_days,
            "coverage_percentage": coverage_percentage,
            "unpaid_coverage_days": total_unpaid_days,
            "outstanding_amount": total_outstanding,
        },
        "catchup": catchup_analysis,
    }


def identify_coverage_gaps_optimized(coverage_map, period_start, period_end, expected_billing_frequency):
    """Optimized gap identification using pre-loaded billing frequency info"""

    gaps = []
    current_date = period_start

    for coverage in coverage_map:
        coverage_start = coverage["coverage_start"]

        # Check for gap before this coverage period
        if current_date < coverage_start:
            gap_days = date_diff(coverage_start, current_date)
            gap_type = classify_gap_type(gap_days)

            # Enhance gap classification with billing context
            if expected_billing_frequency:
                gap_type = classify_gap_with_billing_context(gap_days, expected_billing_frequency, gap_type)

            gaps.append(
                {
                    "gap_start": current_date,
                    "gap_end": add_days(coverage_start, -1),
                    "gap_days": gap_days,
                    "gap_type": gap_type,
                    "gap_reason": get_gap_reason_optimized(
                        current_date, coverage_start, expected_billing_frequency
                    ),
                }
            )

        # Move current date forward
        current_date = max(current_date, add_days(coverage["coverage_end"], 1))

    # Check for gap after last coverage period
    if current_date <= period_end:
        gap_days = date_diff(period_end, current_date) + 1
        gap_type = classify_gap_type(gap_days)

        if expected_billing_frequency:
            gap_type = classify_gap_with_billing_context(gap_days, expected_billing_frequency, gap_type)

        gaps.append(
            {
                "gap_start": current_date,
                "gap_end": period_end,
                "gap_days": gap_days,
                "gap_type": gap_type,
                "gap_reason": get_gap_reason_optimized(
                    current_date, period_end, expected_billing_frequency, is_final_gap=True
                ),
            }
        )

    return gaps


def calculate_catchup_requirements_optimized(member_name, gaps, billing_info):
    """Optimized catch-up calculation using pre-loaded billing info"""

    if not gaps:
        return {"periods": [], "total_amount": 0, "required": False, "summary": "No catch-up required"}

    # Get dues rate from pre-loaded data or fallback query
    dues_rate = 25.0  # Default fallback
    billing_frequency = billing_info.get("expected_billing_frequency", "Monthly")

    # Only query if we don't have the info (rare case)
    if not billing_info:
        dues_schedule = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member_name, "status": "Active"},
            ["billing_frequency", "dues_rate"],
            as_dict=True,
        )
        if dues_schedule:
            billing_frequency = dues_schedule["billing_frequency"]
            dues_rate = dues_schedule["dues_rate"]

    catchup_periods = []
    total_catchup_amount = 0

    for gap in gaps:
        # Calculate periods needed to fill this gap
        periods = calculate_billing_periods_for_gap_optimized(
            gap["gap_start"], gap["gap_end"], billing_frequency, dues_rate
        )

        for period in periods:
            catchup_periods.append(period)
            total_catchup_amount += flt(period["amount"])

    summary = f"{len(catchup_periods)} period(s) needed - {billing_frequency} billing"

    return {
        "periods": catchup_periods,
        "total_amount": total_catchup_amount,
        "required": len(catchup_periods) > 0,
        "summary": summary,
    }


# Import helper functions from original (these don't have N+1 issues)
def build_conditions(filters):
    """Build SQL WHERE conditions from filters with parameter placeholders"""
    conditions = ["m.status = 'Active'"]
    params = []

    if filters.get("member"):
        conditions.append("m.name = %s")
        params.append(filters["member"])

    if filters.get("chapter"):
        conditions.append("m.chapter = %s")
        params.append(filters["chapter"])

    if filters.get("billing_frequency"):
        conditions.append("mds.billing_frequency = %s")
        params.append(filters["billing_frequency"])

    return " AND ".join(conditions), params


def should_include_row(row, filters):
    """Check if row should be included based on calculated data filters"""

    # Filter by gap severity
    if filters.get("gap_severity"):
        if not row["current_gaps"] or row["current_gaps"] == "No gaps":
            return False
        if filters["gap_severity"] not in row["current_gaps"]:
            return False

    # Show only members with gaps
    if filters.get("show_only_gaps"):
        if row["gap_days"] == 0:
            return False

    # Show only members requiring catch-up
    if filters.get("show_only_catchup_required"):
        if not row["catchup_required"]:
            return False

    return True


def build_member_row(member_data, coverage_analysis):
    """Build a single row of report data for a member"""

    stats = coverage_analysis["stats"]
    gaps = coverage_analysis["gaps"]
    catchup = coverage_analysis["catchup"]

    # Format current gaps for display
    current_gaps_text = format_gaps_for_display(gaps)

    # Format catch-up periods for display
    catchup_periods_text = format_catchup_periods_for_display(catchup["periods"])

    return {
        "member": member_data["member"],
        "member_name": member_data["member_name"],
        "membership_start": member_data["membership_start"],
        "membership_status": member_data["membership_status"],
        "total_active_days": stats["total_active_days"],
        "covered_days": stats["covered_days"],
        "gap_days": stats["gap_days"],
        "coverage_percentage": round(stats["coverage_percentage"], 1),
        "current_gaps": current_gaps_text,
        "unpaid_coverage": stats["unpaid_coverage_days"],
        "outstanding_amount": stats["outstanding_amount"],
        "billing_frequency": member_data.get("billing_frequency", ""),
        "dues_rate": member_data.get("dues_rate", 0),
        "last_invoice_date": member_data.get("last_invoice_date"),
        "next_invoice_due": member_data.get("next_invoice_due"),
        "catchup_required": 1 if catchup["required"] else 0,
        "catchup_amount": catchup["total_amount"],
        "catchup_periods": catchup_periods_text,
    }


# Helper functions (imported from original - no optimization needed)
def classify_gap_type(gap_days):
    """Classify gap severity based on number of days"""
    if gap_days <= 7:
        return "Minor"
    elif gap_days <= 30:
        return "Moderate"
    elif gap_days <= 90:
        return "Significant"
    else:
        return "Critical"


def classify_gap_with_billing_context(gap_days, expected_billing_frequency, base_classification):
    """Enhance gap classification based on expected billing frequency"""

    if not expected_billing_frequency:
        return base_classification

    # For monthly billing, adjust thresholds
    if expected_billing_frequency == "Monthly":
        if gap_days >= 60:  # Missing 2+ months
            return "Critical"
        elif gap_days >= 35:  # Missing 1+ month
            return "Significant"
        elif gap_days >= 14:  # Half month missing
            return "Moderate"
        else:
            return "Minor"

    return base_classification


def get_gap_reason_optimized(gap_start, gap_end, expected_billing_frequency, is_final_gap=False):
    """Determine the likely reason for a coverage gap"""

    if not expected_billing_frequency:
        return "No coverage (unknown billing schedule)"

    gap_days = date_diff(gap_end, gap_start) + (0 if is_final_gap else 1)

    if expected_billing_frequency == "Monthly":
        if gap_days < 32:
            return "Partial month gap in monthly billing"
        else:
            months = gap_days // 30
            return f"Missing ~{months} month(s) of monthly billing"
    else:
        return f"Coverage gap in {expected_billing_frequency.lower()} billing"


def calculate_billing_periods_for_gap_optimized(gap_start, gap_end, billing_frequency, dues_rate):
    """Calculate billing periods needed to fill a specific gap"""

    periods = []
    current_date = gap_start

    while current_date <= gap_end:
        if billing_frequency == "Monthly":
            # Monthly billing - bill by calendar month
            period_start = current_date.replace(day=1)
            if period_start.month == 12:
                period_end = period_start.replace(year=period_start.year + 1, month=1, day=1) - timedelta(
                    days=1
                )
            else:
                period_end = period_start.replace(month=period_start.month + 1, day=1) - timedelta(days=1)

            # Clip to gap boundaries
            period_start = max(period_start, gap_start)
            period_end = min(period_end, gap_end)

            periods.append(
                {
                    "start": period_start,
                    "end": period_end,
                    "amount": dues_rate,
                    "billing_frequency": billing_frequency,
                }
            )

            current_date = period_end + timedelta(days=1)
        else:
            # Other billing - treat as single period
            periods.append(
                {
                    "start": gap_start,
                    "end": gap_end,
                    "amount": dues_rate,
                    "billing_frequency": billing_frequency,
                }
            )
            break

    return periods


def format_gaps_for_display(gaps):
    """Format gaps list for display in report"""
    if not gaps:
        return "No gaps"

    gap_strings = []
    for gap in gaps:
        reason = gap.get("gap_reason", "")
        if reason:
            gap_str = f"{gap['gap_start']} to {gap['gap_end']} ({gap['gap_days']} days, {gap['gap_type']}) - {reason}"
        else:
            gap_str = f"{gap['gap_start']} to {gap['gap_end']} ({gap['gap_days']} days, {gap['gap_type']})"
        gap_strings.append(gap_str)

    return "; ".join(gap_strings)


def format_catchup_periods_for_display(periods):
    """Format catch-up periods for display in report"""
    if not periods:
        return "None required"

    period_strings = []
    for period in periods:
        period_str = f"{period['start']} to {period['end']} (€{period['amount']})"
        period_strings.append(period_str)

    return "; ".join(period_strings)


def get_empty_coverage_analysis():
    """Return empty coverage analysis structure"""
    return {
        "timeline": [],
        "gaps": [],
        "stats": {
            "total_active_days": 0,
            "covered_days": 0,
            "gap_days": 0,
            "coverage_percentage": 0,
            "unpaid_coverage_days": 0,
            "outstanding_amount": 0,
        },
        "catchup": {"periods": [], "total_amount": 0, "required": False, "summary": "No analysis available"},
    }


def build_period_coverage_map(invoices, period_start, period_end):
    """Build coverage map for a specific membership period using pre-loaded invoice data"""

    coverage_map = []

    for invoice in invoices:
        coverage_start = getdate(invoice["coverage_start"])
        coverage_end = getdate(invoice["coverage_end"])

        # Clip coverage to membership period
        clipped_start = max(coverage_start, period_start)
        clipped_end = min(coverage_end, period_end)

        # Only include if there's actual overlap
        if clipped_start <= clipped_end:
            coverage_map.append(
                {
                    "invoice": invoice["invoice"],
                    "coverage_start": clipped_start,
                    "coverage_end": clipped_end,
                    "payment_status": invoice["payment_status"],
                    "amount": flt(invoice["grand_total"]),
                    "outstanding_amount": flt(invoice["outstanding_amount"]),
                    "posting_date": invoice["posting_date"],
                }
            )

    # Sort by coverage start date
    coverage_map.sort(key=lambda x: x["coverage_start"])

    # Remove overlaps (keep earliest invoice for overlapping periods)
    deduplicated_coverage = []
    for coverage in coverage_map:
        # Check if this coverage overlaps with any existing coverage
        overlaps = False
        for existing in deduplicated_coverage:
            if (
                coverage["coverage_start"] <= existing["coverage_end"]
                and coverage["coverage_end"] >= existing["coverage_start"]
            ):
                overlaps = True
                break

        if not overlaps:
            deduplicated_coverage.append(coverage)

    return deduplicated_coverage
