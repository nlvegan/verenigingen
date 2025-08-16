# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

import json
from datetime import datetime, timedelta

import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, flt, getdate, today


def execute(filters=None):
    """Main report execution function"""
    if not filters:
        filters = {}

    # Validate input filters
    try:
        validate_filters(filters)
    except Exception as e:
        frappe.throw(_("Invalid filters: {0}").format(str(e)))

    columns = get_columns()
    data = get_data(filters)

    return columns, data


def validate_filters(filters):
    """Validate input filters to prevent issues"""

    # Validate date range
    if filters.get("from_date") and filters.get("to_date"):
        from_date = getdate(filters["from_date"])
        to_date = getdate(filters["to_date"])

        if from_date > to_date:
            raise ValueError("From date cannot be after to date")

        # Prevent overly large date ranges that could cause performance issues
        if date_diff(to_date, from_date) > 365 * 5:  # 5 years max
            raise ValueError("Date range too large (maximum 5 years)")

    # Validate member exists if specified
    if filters.get("member"):
        if not frappe.db.exists("Member", filters["member"]):
            raise ValueError(f"Member {filters['member']} does not exist")

    # Validate chapter exists if specified
    if filters.get("chapter"):
        if not frappe.db.exists("Chapter", filters["chapter"]):
            raise ValueError(f"Chapter {filters['chapter']} does not exist")

    # Validate billing frequency
    if filters.get("billing_frequency"):
        valid_frequencies = ["Daily", "Monthly", "Quarterly", "Annual", "Custom"]
        if filters["billing_frequency"] not in valid_frequencies:
            raise ValueError(f"Invalid billing frequency: {filters['billing_frequency']}")

    # Validate gap severity
    if filters.get("gap_severity"):
        valid_severities = ["Minor", "Moderate", "Significant", "Critical"]
        if filters["gap_severity"] not in valid_severities:
            raise ValueError(f"Invalid gap severity: {filters['gap_severity']}")


def get_columns():
    """Define report columns"""
    return [
        # Member Information
        {"fieldname": "member", "label": _("Member"), "fieldtype": "Link", "options": "Member", "width": 120},
        {"fieldname": "member_name", "label": _("Member Name"), "fieldtype": "Data", "width": 200},
        {"fieldname": "membership_start", "label": _("Membership Start"), "fieldtype": "Date", "width": 120},
        {"fieldname": "membership_status", "label": _("Status"), "fieldtype": "Data", "width": 100},
        # Coverage Analysis
        {"fieldname": "total_active_days", "label": _("Total Active Days"), "fieldtype": "Int", "width": 120},
        {"fieldname": "covered_days", "label": _("Covered Days"), "fieldtype": "Int", "width": 120},
        {"fieldname": "gap_days", "label": _("Gap Days"), "fieldtype": "Int", "width": 100},
        {"fieldname": "coverage_percentage", "label": _("Coverage %"), "fieldtype": "Percent", "width": 100},
        # Gap Details
        {"fieldname": "current_gaps", "label": _("Current Gaps"), "fieldtype": "Small Text", "width": 300},
        {
            "fieldname": "unpaid_coverage",
            "label": _("Unpaid Coverage Days"),
            "fieldtype": "Int",
            "width": 150,
        },
        {
            "fieldname": "outstanding_amount",
            "label": _("Outstanding Amount"),
            "fieldtype": "Currency",
            "width": 120,
        },
        # Billing Information
        {
            "fieldname": "billing_frequency",
            "label": _("Billing Frequency"),
            "fieldtype": "Data",
            "width": 120,
        },
        {"fieldname": "dues_rate", "label": _("Dues Rate"), "fieldtype": "Currency", "width": 100},
        {"fieldname": "last_invoice_date", "label": _("Last Invoice"), "fieldtype": "Date", "width": 120},
        {"fieldname": "next_invoice_due", "label": _("Next Invoice Due"), "fieldtype": "Date", "width": 120},
        # Catch-up Information
        {
            "fieldname": "catchup_required",
            "label": _("Catch-up Required"),
            "fieldtype": "Check",
            "width": 100,
        },
        {"fieldname": "catchup_amount", "label": _("Catch-up Amount"), "fieldtype": "Currency", "width": 120},
        {
            "fieldname": "catchup_periods",
            "label": _("Catch-up Periods"),
            "fieldtype": "Small Text",
            "width": 200,
        },
    ]


def get_data(filters):
    """Get report data"""

    # Build conditions based on filters
    conditions, params = build_conditions(filters)

    # Get active members with their membership information
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

    data = []

    for member_data in members_data:
        try:
            # Calculate coverage analysis for this member
            coverage_analysis = calculate_coverage_timeline(
                member_data["member"], filters.get("from_date"), filters.get("to_date")
            )

            # Build row data
            row = build_member_row(member_data, coverage_analysis)

            # Apply filters that require calculated data
            if should_include_row(row, filters):
                data.append(row)

        except Exception as e:
            # Log error and continue with next member
            frappe.log_error(
                f"Error processing member {member_data['member']}: {str(e)}", "Dues Coverage Report"
            )
            continue

    return data


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

    # gap_severity is filtered after calculation

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


def calculate_coverage_timeline(member_name, from_date=None, to_date=None):
    """
    Calculate comprehensive coverage timeline for a member
    Returns detailed coverage analysis including gaps and catch-up requirements
    """

    try:
        # Get member information
        if not frappe.db.exists("Member", member_name):
            frappe.log_error(f"Member {member_name} does not exist", "Coverage Timeline Calculation")
            return get_empty_coverage_analysis()

        member = frappe.get_doc("Member", member_name)

        if not member.customer:
            frappe.log_error(f"Member {member_name} has no customer record", "Coverage Timeline Calculation")
            return get_empty_coverage_analysis()

        # Get membership periods
        membership_periods = get_membership_periods(member_name, from_date, to_date)

        if not membership_periods:
            return get_empty_coverage_analysis()

    except Exception as e:
        frappe.log_error(
            f"Error in calculate_coverage_timeline for {member_name}: {str(e)}",
            "Coverage Timeline Calculation",
        )
        return get_empty_coverage_analysis()

    # Get all invoices with coverage dates for this member
    invoices = get_member_invoices_with_coverage(member.customer, from_date, to_date)

    # Build comprehensive coverage analysis
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

        # Build coverage map for this membership period
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

        # Identify gaps in this period (includes both missing coverage and billing pattern issues)
        period_gaps = identify_coverage_gaps(period_coverage, membership_start, membership_end, member_name)
        all_gaps.extend(period_gaps)

        # Also identify billing pattern inconsistencies
        billing_inconsistencies = identify_billing_pattern_issues(
            period_coverage, membership_start, membership_end, member_name
        )
        all_gaps.extend(billing_inconsistencies)

    # Calculate catch-up requirements
    catchup_analysis = calculate_catchup_requirements(member_name, all_gaps)

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


def get_membership_periods(member_name, from_date=None, to_date=None):
    """Get all membership periods for a member within date range"""

    conditions = ["mb.member = %s", "mb.docstatus = 1"]
    params = [member_name]

    if from_date:
        conditions.append("(mb.cancellation_date IS NULL OR mb.cancellation_date >= %s)")
        params.append(from_date)

    if to_date:
        conditions.append("mb.start_date <= %s")
        params.append(to_date)

    memberships = frappe.db.sql(
        f"""
        SELECT mb.start_date, mb.cancellation_date as end_date
        FROM `tabMembership` mb
        WHERE {' AND '.join(conditions)}
        ORDER BY mb.start_date
    """,
        params,
        as_dict=True,
    )

    periods = []
    for membership in memberships:
        start_date = getdate(membership["start_date"])
        end_date = getdate(membership["end_date"]) if membership["end_date"] else getdate(today())

        # Apply date range filters
        if from_date:
            start_date = max(start_date, getdate(from_date))
        if to_date:
            end_date = min(end_date, getdate(to_date))

        if start_date <= end_date:
            periods.append((start_date, end_date))

    return periods


def get_member_invoices_with_coverage(customer, from_date=None, to_date=None):
    """Get all invoices with coverage information for a customer"""

    conditions = ["si.customer = %s", "si.docstatus = 1", "si.custom_coverage_start_date IS NOT NULL"]
    params = [customer]

    if from_date:
        conditions.append("si.custom_coverage_end_date >= %s")
        params.append(from_date)

    if to_date:
        conditions.append("si.custom_coverage_start_date <= %s")
        params.append(to_date)

    return frappe.db.sql(
        f"""
        SELECT
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
        ORDER BY si.custom_coverage_start_date
    """,
        params,
        as_dict=True,
    )


def build_period_coverage_map(invoices, period_start, period_end):
    """Build coverage map for a specific membership period"""

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


def identify_coverage_gaps(coverage_map, period_start, period_end, member_name=None):
    """Identify gaps in coverage within a membership period, including missing expected invoices"""

    gaps = []
    current_date = period_start

    # Get membership type to understand expected billing pattern
    expected_billing_frequency = (
        get_expected_billing_frequency(member_name, period_start, period_end) if member_name else None
    )

    for coverage in coverage_map:
        coverage_start = coverage["coverage_start"]

        # Check for gap before this coverage period
        if current_date < coverage_start:
            gap_days = date_diff(coverage_start, current_date)
            gap_type = classify_gap_type(gap_days)

            # Enhance gap classification if we know the expected billing frequency
            if expected_billing_frequency:
                gap_type = classify_gap_with_billing_context(gap_days, expected_billing_frequency, gap_type)

            gaps.append(
                {
                    "gap_start": current_date,
                    "gap_end": add_days(coverage_start, -1),
                    "gap_days": gap_days,
                    "gap_type": gap_type,
                    "gap_reason": get_gap_reason(current_date, coverage_start, expected_billing_frequency),
                }
            )

        # Move current date forward
        current_date = max(current_date, add_days(coverage["coverage_end"], 1))

    # Check for gap after last coverage period
    if current_date <= period_end:
        gap_days = date_diff(period_end, current_date) + 1
        gap_type = classify_gap_type(gap_days)

        # Enhance gap classification if we know the expected billing frequency
        if expected_billing_frequency:
            gap_type = classify_gap_with_billing_context(gap_days, expected_billing_frequency, gap_type)

        gaps.append(
            {
                "gap_start": current_date,
                "gap_end": period_end,
                "gap_days": gap_days,
                "gap_type": gap_type,
                "gap_reason": get_gap_reason(
                    current_date, period_end, expected_billing_frequency, is_final_gap=True
                ),
            }
        )

    return gaps


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


def get_expected_billing_frequency(member_name, period_start, period_end):
    """Get the expected billing frequency for a member during a period"""

    try:
        # Get membership for this period
        membership = frappe.db.sql(
            """
            SELECT mb.membership_type
            FROM `tabMembership` mb
            WHERE mb.member = %s
              AND mb.docstatus = 1
              AND mb.start_date <= %s
              AND (mb.cancellation_date IS NULL OR mb.cancellation_date >= %s)
            ORDER BY mb.start_date DESC
            LIMIT 1
        """,
            [member_name, period_end, period_start],
            as_dict=True,
        )

        if not membership:
            return None

        membership_type = membership[0]["membership_type"]

        # Get the billing period from membership type
        billing_period = frappe.db.get_value("Membership Type", membership_type, "billing_period")

        return billing_period

    except Exception as e:
        frappe.log_error(
            f"Error getting billing frequency for {member_name}: {str(e)}", "Coverage Gap Analysis"
        )
        return None


def classify_gap_with_billing_context(gap_days, expected_billing_frequency, base_classification):
    """Enhance gap classification based on expected billing frequency"""

    if not expected_billing_frequency:
        return base_classification

    # For daily billing, any gap is more serious
    if expected_billing_frequency == "Daily":
        if gap_days >= 14:  # Missing 2+ weeks of daily billing
            return "Critical"
        elif gap_days >= 7:  # Missing 1+ week of daily billing
            return "Significant"
        elif gap_days >= 3:  # Missing 3+ days of daily billing
            return "Moderate"
        else:
            return "Minor"

    # For monthly billing, adjust thresholds
    elif expected_billing_frequency == "Monthly":
        if gap_days >= 60:  # Missing 2+ months
            return "Critical"
        elif gap_days >= 35:  # Missing 1+ month
            return "Significant"
        elif gap_days >= 14:  # Half month missing
            return "Moderate"
        else:
            return "Minor"

    # For other frequencies, use base classification but with context
    return base_classification


def get_gap_reason(gap_start, gap_end, expected_billing_frequency, is_final_gap=False):
    """Determine the likely reason for a coverage gap"""

    if not expected_billing_frequency:
        return "No coverage (unknown billing schedule)"

    gap_days = date_diff(gap_end, gap_start) + (0 if is_final_gap else 1)

    if expected_billing_frequency == "Daily":
        if gap_days == 1:
            return "Missing 1 day of daily billing"
        else:
            return f"Missing {gap_days} days of daily billing"

    elif expected_billing_frequency == "Monthly":
        if gap_days < 32:
            return "Partial month gap in monthly billing"
        else:
            months = gap_days // 30
            return f"Missing ~{months} month(s) of monthly billing"

    elif expected_billing_frequency == "Quarterly":
        if gap_days < 90:
            return "Partial quarter gap in quarterly billing"
        else:
            quarters = gap_days // 90
            return f"Missing ~{quarters} quarter(s) of quarterly billing"

    elif expected_billing_frequency == "Annual":
        if gap_days < 365:
            return "Partial year gap in annual billing"
        else:
            years = gap_days // 365
            return f"Missing ~{years} year(s) of annual billing"

    else:
        return f"Coverage gap in {expected_billing_frequency.lower()} billing"


def identify_billing_pattern_issues(coverage_map, period_start, period_end, member_name):
    """Identify periods where billing pattern doesn't match expected membership type"""

    issues = []

    # Get expected billing frequency
    expected_billing_frequency = get_expected_billing_frequency(member_name, period_start, period_end)

    if not expected_billing_frequency or expected_billing_frequency != "Daily":
        # Only check daily billing patterns for now
        return issues

    # For daily billing, we need to check if long-duration invoices are replacing missing daily invoices
    # or if they're legitimate adjustments alongside proper daily invoices

    for coverage in coverage_map:
        coverage_days = date_diff(coverage["coverage_end"], coverage["coverage_start"]) + 1

        # If a single invoice covers more than 7 days for daily billing, investigate further
        if coverage_days > 7:
            # Check if there are other invoices covering individual days within this period
            period_has_daily_invoices = any(
                other_cov
                for other_cov in coverage_map
                if other_cov != coverage
                and other_cov["coverage_start"] >= coverage["coverage_start"]
                and other_cov["coverage_end"] <= coverage["coverage_end"]
                and date_diff(other_cov["coverage_end"], other_cov["coverage_start"]) + 1
                <= 2  # Daily or 2-day invoices
            )

            # If there are no daily invoices for this period, it might be a billing issue
            if not period_has_daily_invoices:
                # Check if this might be a legitimate adjustment or special case
                is_likely_adjustment = (
                    coverage["amount"] < 10
                    or "adjustment"  # Very low amount suggests adjustment
                    in coverage.get("invoice", "").lower()
                    or "correction" in coverage.get("invoice", "").lower()
                )

                if is_likely_adjustment:
                    # This looks like a manual adjustment covering a period that should have daily invoices
                    # Calculate how many daily invoices should have been generated
                    expected_daily_invoices = coverage_days
                    missing_daily_invoices = expected_daily_invoices - 1  # -1 because we have this adjustment

                    if missing_daily_invoices > 0:
                        # Report this as a billing pattern issue
                        issues.append(
                            {
                                "gap_start": coverage["coverage_start"],
                                "gap_end": coverage["coverage_end"],
                                "gap_days": missing_daily_invoices,
                                "gap_type": classify_gap_with_billing_context(
                                    missing_daily_invoices, "Daily", "Moderate"
                                ),
                                "gap_reason": f"Billing schedule misconfiguration: {coverage_days}-day adjustment invoice instead of {expected_daily_invoices} daily invoices (Missing {missing_daily_invoices} invoices)",
                                "issue_type": "billing_pattern_mismatch",
                                "covering_invoice": coverage["invoice"],
                            }
                        )

    return issues


def calculate_catchup_requirements(member_name, gaps):
    """Calculate what invoices need to be generated to fill gaps"""

    if not gaps:
        return {"periods": [], "total_amount": 0, "required": False, "summary": "No catch-up required"}

    # Get member's dues schedule
    dues_schedule = frappe.db.get_value(
        "Membership Dues Schedule",
        {"member": member_name, "status": "Active"},
        ["billing_frequency", "dues_rate"],
        as_dict=True,
    )

    if not dues_schedule:
        return {"periods": [], "total_amount": 0, "required": False, "summary": "No active dues schedule"}

    catchup_periods = []
    total_catchup_amount = 0

    for gap in gaps:
        # Calculate periods needed to fill this gap
        periods = calculate_billing_periods_for_gap(
            gap["gap_start"], gap["gap_end"], dues_schedule["billing_frequency"], dues_schedule["dues_rate"]
        )

        for period in periods:
            catchup_periods.append(period)
            total_catchup_amount += flt(period["amount"])

    summary = f"{len(catchup_periods)} period(s) needed - {dues_schedule['billing_frequency']} billing"

    return {
        "periods": catchup_periods,
        "total_amount": total_catchup_amount,
        "required": len(catchup_periods) > 0,
        "summary": summary,
    }


def calculate_billing_periods_for_gap(gap_start, gap_end, billing_frequency, dues_rate):
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

        elif billing_frequency == "Quarterly":
            # Quarterly billing - Q1, Q2, Q3, Q4
            quarter = ((current_date.month - 1) // 3) + 1
            quarter_start_month = (quarter - 1) * 3 + 1

            period_start = current_date.replace(month=quarter_start_month, day=1)
            if quarter == 4:
                period_end = period_start.replace(year=period_start.year + 1, month=1, day=1) - timedelta(
                    days=1
                )
            else:
                period_end = period_start.replace(month=quarter_start_month + 3, day=1) - timedelta(days=1)

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

        elif billing_frequency == "Annual":
            # Annual billing - calendar year
            period_start = current_date.replace(month=1, day=1)
            period_end = current_date.replace(month=12, day=31)

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
            # Custom or daily billing - treat as single period
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


def format_gaps_for_display(gaps):
    """Format gaps list for display in report"""
    if not gaps:
        return "No gaps"

    gap_strings = []
    for gap in gaps:
        # Include gap reason if available
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


@frappe.whitelist()
def generate_catchup_invoices(members):
    """Generate catch-up invoices for members with coverage gaps"""

    # Check permissions
    if not frappe.has_permission("Sales Invoice", "create"):
        frappe.throw(_("Insufficient permissions to create invoices"))

    if isinstance(members, str):
        members = json.loads(members)

    generated_invoices = []
    errors = []

    for member_data in members:
        try:
            member_name = member_data["member"]

            # Get detailed coverage analysis
            coverage_analysis = calculate_coverage_timeline(member_name)

            if not coverage_analysis["catchup"]["required"]:
                continue

            # Generate invoices for each catch-up period
            member_doc = frappe.get_doc("Member", member_name)

            for period in coverage_analysis["catchup"]["periods"]:
                # Validate period data
                if not period.get("start") or not period.get("end") or not period.get("amount"):
                    error_msg = f"Invalid catch-up period data for {member_name}: {period}"
                    frappe.log_error(error_msg, "Catch-up Invoice Generation")
                    errors.append(error_msg)
                    continue

                # Check if invoice already exists for this period
                existing_invoice = frappe.db.exists(
                    "Sales Invoice",
                    {
                        "customer": member_doc.customer,
                        "custom_coverage_start_date": period["start"],
                        "custom_coverage_end_date": period["end"],
                        "docstatus": ["!=", 2],  # Not cancelled
                    },
                )

                if existing_invoice:
                    continue  # Skip if invoice already exists

                # Create Sales Invoice for this catch-up period
                invoice = frappe.new_doc("Sales Invoice")
                invoice.customer = member_doc.customer
                invoice.posting_date = today()
                invoice.due_date = add_days(today(), 30)  # 30 days to pay

                # Set coverage dates
                invoice.custom_coverage_start_date = period["start"]
                invoice.custom_coverage_end_date = period["end"]

                # Check if "Membership Dues" item exists, create fallback
                item_code = "Membership Dues"
                if not frappe.db.exists("Item", item_code):
                    item_code = frappe.db.get_value(
                        "Item", {"item_group": "Services", "is_stock_item": 0}, "name"
                    )
                    if not item_code:
                        # Create a basic service item if none exists
                        item_doc = frappe.new_doc("Item")
                        item_doc.item_code = "Membership Dues"
                        item_doc.item_name = "Membership Dues"
                        item_doc.item_group = "All Item Groups"  # Fallback group
                        item_doc.is_stock_item = 0
                        item_doc.insert(ignore_permissions=True)
                        item_code = item_doc.name

                # Add invoice item
                invoice.append(
                    "items",
                    {
                        "item_code": item_code,
                        "description": f"Catch-up Dues: {period['start']} to {period['end']}",
                        "qty": 1,
                        "rate": period["amount"],
                        "amount": period["amount"],
                    },
                )

                # Link to SEPA mandate if available
                if hasattr(member_doc, "sepa_mandate") and member_doc.sepa_mandate:
                    invoice.custom_sepa_mandate = member_doc.sepa_mandate

                # Save and submit invoice with error handling
                try:
                    invoice.insert()
                    invoice.submit()

                    generated_invoices.append(
                        {
                            "member": member_name,
                            "invoice": invoice.name,
                            "amount": period["amount"],
                            "period": f"{period['start']} to {period['end']}",
                        }
                    )
                except Exception as submit_error:
                    error_msg = f"Failed to create invoice for {member_name}: {str(submit_error)}"
                    frappe.log_error(error_msg, "Catch-up Invoice Generation")
                    errors.append(error_msg)

                    # Try to delete the failed invoice
                    try:
                        if invoice.name:
                            frappe.delete_doc("Sales Invoice", invoice.name, ignore_permissions=True)
                    except:
                        pass  # Ignore cleanup errors

        except Exception as e:
            error_msg = (
                f"Error generating catch-up invoice for {member_data.get('member', 'Unknown')}: {str(e)}"
            )
            frappe.log_error(error_msg, "Catch-up Invoice Generation")
            errors.append(error_msg)

    # Build response message
    success_count = len(generated_invoices)
    error_count = len(errors)

    message = f"Generated {success_count} catch-up invoices"
    if error_count > 0:
        message += f" ({error_count} errors - check error log)"

    return {"message": message, "generated_invoices": generated_invoices, "errors": errors}


@frappe.whitelist()
def export_gap_analysis(filters):
    """Export detailed gap analysis to Excel"""

    # Check permissions
    if not frappe.has_permission("Member", "read"):
        frappe.throw(_("Insufficient permissions to export member data"))

    if isinstance(filters, str):
        filters = json.loads(filters)

    # Get report data
    columns, data = execute(filters)

    # Create Excel file
    from frappe.utils.xlsxutils import make_xlsx

    # Add detailed timeline data for each member
    detailed_data = []

    for row in data:
        if row["gap_days"] > 0:  # Only include members with gaps
            member_name = row["member"]

            # Get detailed coverage analysis
            coverage_analysis = calculate_coverage_timeline(
                member_name, filters.get("from_date"), filters.get("to_date")
            )

            # Add summary row
            detailed_data.append(row)

            # Add gap details
            for gap in coverage_analysis["gaps"]:
                gap_row = {
                    "member": "",  # Empty for sub-rows
                    "member_name": f"  → Gap: {gap['gap_start']} to {gap['gap_end']}",
                    "gap_days": gap["gap_days"],
                    "gap_type": gap["gap_type"],
                    "coverage_percentage": "",
                    "current_gaps": f"{gap['gap_days']} days ({gap['gap_type']})",
                    # Clear other fields for gap rows
                    **{
                        col["fieldname"]: ""
                        for col in columns
                        if col["fieldname"] not in ["member", "member_name", "gap_days", "current_gaps"]
                    },
                }
                detailed_data.append(gap_row)

    # Generate Excel file
    file_name = f"dues_coverage_gap_analysis_{frappe.utils.now()}.xlsx"
    xlsx_file = make_xlsx(detailed_data, "Gap Analysis", file_name=file_name)

    return {"file_url": xlsx_file, "message": f"Gap analysis exported to {file_name}"}


@frappe.whitelist()
def debug_coverage_fields():
    """Debug function to check coverage field existence and data"""

    results = []
    results.append("=== COVERAGE ANALYSIS DEBUG ===")

    # 1. Check if coverage fields exist in Sales Invoice
    try:
        has_start = frappe.db.has_column("tabSales Invoice", "custom_coverage_start_date")
        has_end = frappe.db.has_column("tabSales Invoice", "custom_coverage_end_date")

        results.append("Coverage fields exist:")
        results.append(f"  - custom_coverage_start_date: {has_start}")
        results.append(f"  - custom_coverage_end_date: {has_end}")

        if not (has_start and has_end):
            # Show what custom fields do exist
            columns = frappe.db.sql("DESCRIBE `tabSales Invoice`", as_dict=True)
            custom_cols = [col["Field"] for col in columns if col["Field"].startswith("custom_")]
            results.append(f"\nFound {len(custom_cols)} custom fields in Sales Invoice:")
            for col in custom_cols[:10]:  # Show first 10
                results.append(f"  - {col}")

    except Exception as e:
        results.append(f"Error checking fields: {e}")

    # 2. Test with sample data
    try:
        # Get sample member with customer
        sample_member = frappe.db.sql(
            """
            SELECT m.name, m.full_name, m.customer
            FROM `tabMember` m
            WHERE m.status = 'Active' AND m.customer IS NOT NULL
            LIMIT 1
        """,
            as_dict=True,
        )

        if sample_member:
            member = sample_member[0]
            results.append(f"\nTesting with member: {member.name} ({member.full_name})")
            results.append(f"Customer: {member.customer}")

            # Test membership periods
            periods = get_membership_periods(member.name)
            results.append(f"Membership periods: {len(periods)}")
            for i, (start, end) in enumerate(periods):
                results.append(f"  Period {i + 1}: {start} to {end}")

            # Test invoice query (without coverage filter first)
            all_invoices = frappe.db.sql(
                """
                SELECT name, posting_date, grand_total, status
                FROM `tabSales Invoice`
                WHERE customer = %s AND docstatus = 1
                LIMIT 5
            """,
                [member.customer],
                as_dict=True,
            )

            results.append(f"\nAll invoices for customer: {len(all_invoices)}")
            for inv in all_invoices:
                results.append(f"  - {inv.name}: €{inv.grand_total} ({inv.status})")

            # Now test with coverage fields if they exist
            if has_start and has_end:
                coverage_invoices = get_member_invoices_with_coverage(member.customer)
                results.append(f"\nInvoices with coverage: {len(coverage_invoices)}")
                for inv in coverage_invoices:
                    results.append(f"  - {inv.invoice}: {inv.coverage_start} to {inv.coverage_end}")
            else:
                results.append("\n❌ Cannot test coverage invoices - fields don't exist!")

            # Test the main function
            coverage_analysis = calculate_coverage_timeline(member.name)
            stats = coverage_analysis["stats"]
            results.append("\nCoverage Analysis Results:")
            results.append(f"  - Total Active Days: {stats['total_active_days']}")
            results.append(f"  - Covered Days: {stats['covered_days']}")
            results.append(f"  - Gap Days: {stats['gap_days']}")
            results.append(f"  - Coverage %: {stats['coverage_percentage']:.1f}%")

        else:
            results.append("\n❌ No active members with customers found!")

    except Exception as e:
        results.append(f"\nError in testing: {e}")
        import traceback

        results.append(traceback.format_exc())

    return "\n".join(results)


@frappe.whitelist()
def get_coverage_timeline_data(member, from_date=None, to_date=None):
    """Get detailed coverage timeline data for visualization"""

    # Check permissions
    if not frappe.has_permission("Member", "read"):
        frappe.throw(_("Insufficient permissions to access member data"))

    coverage_analysis = calculate_coverage_timeline(member, from_date, to_date)

    # Format data for timeline visualization
    timeline_events = []

    # Add coverage periods
    for coverage in coverage_analysis["timeline"]:
        timeline_events.append(
            {
                "type": "coverage",
                "start": coverage["coverage_start"],
                "end": coverage["coverage_end"],
                "status": coverage["payment_status"],
                "invoice": coverage["invoice"],
                "amount": coverage["amount"],
                "title": f"Invoice {coverage['invoice']} - {coverage['payment_status']}",
            }
        )

    # Add gaps
    for gap in coverage_analysis["gaps"]:
        timeline_events.append(
            {
                "type": "gap",
                "start": gap["gap_start"],
                "end": gap["gap_end"],
                "severity": gap["gap_type"],
                "days": gap["gap_days"],
                "title": f"Gap: {gap['gap_days']} days ({gap['gap_type']})",
            }
        )

    # Sort by start date
    timeline_events.sort(key=lambda x: x["start"])

    return {
        "timeline_events": timeline_events,
        "stats": coverage_analysis["stats"],
        "catchup": coverage_analysis["catchup"],
    }
