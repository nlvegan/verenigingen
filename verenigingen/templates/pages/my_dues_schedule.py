import calendar
import csv
import io

import frappe
from frappe import _
from frappe.utils import add_days, add_months, flt, format_date, getdate, now_datetime, today

from verenigingen.services.billing.billing_period_calculator import get_periods_per_year
from verenigingen.templates.pages.payment_dashboard import get_current_dues_schedule
from verenigingen.utils.member_portal_utils import setup_portal_context
from verenigingen.utils.member_utils import get_current_user_member_name_required
from verenigingen.utils.security.api_security_framework import OperationType, self_service_api
from verenigingen.utils.validation_utilities import DateRangeValidator


def get_context(context):
    """Get context for the dues schedule page"""

    member = setup_portal_context(context, "My Dues Schedule")
    if not member:
        return context

    # Get current dues schedule
    current_schedule = get_current_dues_schedule(member)

    # Get payment method dynamically
    payment_method = None
    if current_schedule:
        # Check for active SEPA mandate
        active_mandate = frappe.db.exists(
            "SEPA Mandate", {"member": member, "status": "Active", "is_active": 1, "used_for_memberships": 1}
        )
        payment_method = "SEPA Direct Debit" if active_mandate else "Bank Transfer"

    # Approved as a SEPA applicant who has not signed yet (#1836): until then dues are paid by transfer
    from verenigingen.services.payment.sepa_mandate_manager import member_needs_mandate_signature

    mandate_to_sign = member_needs_mandate_signature(member)

    # Get payment data
    payment_data = get_payment_data(member)
    payment_timeline = get_payment_timeline(member)

    # Get coverage information
    coverage_info = get_coverage_info(member, current_schedule)

    # Get calendar data
    calendar_data = get_calendar_data()

    # Get next payment
    next_payment = get_next_payment(member)

    # Get contact email
    from verenigingen.utils.email_utils import get_member_contact_email

    member_contact_email = get_member_contact_email()

    context.update(
        {
            "member": member,
            "current_schedule": current_schedule,
            "payment_method": payment_method,
            "mandate_to_sign": mandate_to_sign,
            "payment_data": payment_data,
            "payment_timeline": payment_timeline,
            "next_payment": next_payment,
            "coverage_percentage": coverage_info["percentage"],
            "covered_months": coverage_info["covered_months"],
            "total_months": coverage_info["total_months"],
            "calendar_month": calendar_data["month_name"],
            "calendar_year": calendar_data["year"],
            "calendar_month_num": calendar_data["month_num"],
            "member_contact_email": member_contact_email,
        }
    )

    return context


def get_payment_data(member):
    """Get payment data for calendar display"""

    payment_data = []

    # Get all sales invoices for this member
    invoices = frappe.get_all(
        "Sales Invoice",
        filters={
            "customer": frappe.db.get_value("Member", member, "customer"),
            "docstatus": 1,
            "posting_date": ["between", [add_months(today(), -12), add_months(today(), 12)]],
        },
        fields=["name", "due_date", "outstanding_amount", "grand_total", "status"],
        order_by="due_date",
    )

    for invoice in invoices:
        status = "paid"
        if invoice.outstanding_amount > 0:
            if DateRangeValidator.is_date_in_past(invoice.due_date):
                status = "overdue"
            else:
                status = "due"

        payment_data.append(
            {
                "date": str(invoice.due_date),
                "amount": flt(invoice.grand_total, 2),
                "status": status,
                "description": _("Invoice {0}").format(invoice.name),
            }
        )

    return payment_data


def get_payment_timeline(member):
    """Get payment timeline for display"""

    timeline = []

    # Get recent payments and upcoming dues
    customer = frappe.db.get_value("Member", member, "customer")

    # Get recent payment entries
    payments = frappe.get_all(
        "Payment Entry",
        filters={
            "party_type": "Customer",
            "party": customer,
            "docstatus": 1,
            "posting_date": [">=", add_months(today(), -6)],
        },
        fields=["name", "posting_date", "paid_amount", "reference_no"],
        order_by="posting_date desc",
        limit=5,
    )

    for payment in payments:
        timeline.append(
            {
                "due_date": payment.posting_date,
                "amount": flt(payment.paid_amount, 2),
                "status": "Paid",
                "description": _("Payment {0}").format(payment.name),
            }
        )

    # Get upcoming invoices
    upcoming_invoices = frappe.get_all(
        "Sales Invoice",
        filters={
            "customer": customer,
            "docstatus": 1,
            "outstanding_amount": [">", 0],
            "due_date": [">=", today()],
        },
        fields=["name", "due_date", "outstanding_amount"],
        order_by="due_date",
        limit=5,
    )

    for invoice in upcoming_invoices:
        timeline.append(
            {
                "due_date": invoice.due_date,
                "amount": flt(invoice.outstanding_amount, 2),
                "status": "Due",
                "description": _("Invoice {0}").format(invoice.name),
            }
        )

    # Sort by date
    timeline.sort(key=lambda x: getdate(x["due_date"]), reverse=True)

    return timeline[:10]  # Return most recent 10 items


def get_coverage_info(member, current_schedule):
    """Share of the trailing 12 months covered by paid invoices' running periods (#2767).

    Billing runs on rolling periods, and `custom_coverage_start_date` /
    `custom_coverage_end_date` on the Sales Invoice record which period an invoice
    discharges. Coverage is therefore read from those dates, never from the invoice
    posting date or a calendar year: a running Annual period that began last December
    still covers today. An invoice without coverage dates discharges no known period
    and does not count.
    """

    if not current_schedule or not member:
        return {"percentage": 0, "covered_months": 0, "total_months": 12}

    customer = frappe.db.get_value("Member", member, "customer")
    if not customer:
        return {"percentage": 0, "covered_months": 0, "total_months": 12}

    # Period unknown (Custom without an interval): show nothing, not a guess (#2611).
    if (
        get_periods_per_year(
            current_schedule.get("billing_frequency"),
            current_schedule.get("custom_frequency_number"),
            current_schedule.get("custom_frequency_unit"),
        )
        is None
    ):
        return {"percentage": None, "covered_months": None, "total_months": 12}

    as_of = getdate(today())
    window_start = add_days(add_months(as_of, -12), 1)
    periods = frappe.get_all(
        "Sales Invoice",
        filters={
            "customer": customer,
            "docstatus": 1,
            # Not outstanding_amount=0: a credit note that settles an UNPAID invoice also takes
            # it to 0 ("Credit Note Issued"), and the return copies the coverage dates (#2767).
            "status": "Paid",
            "custom_coverage_start_date": ["<=", as_of],
            "custom_coverage_end_date": [">=", window_start],
        },
        fields=["custom_coverage_start_date", "custom_coverage_end_date"],
    )
    window_days = (as_of - window_start).days + 1
    covered_days = count_covered_days(
        [(p.custom_coverage_start_date, p.custom_coverage_end_date) for p in periods], window_start, as_of
    )

    covered_months = min(round(covered_days * 12 / window_days), 12)
    return {
        "percentage": round(covered_days * 100 / window_days),
        "covered_months": covered_months,
        "total_months": 12,
    }


def count_covered_days(periods, window_start, window_end):
    """Days in [window_start, window_end] inside at least one (start, end) period, inclusive."""
    clipped = sorted(
        (max(getdate(start), window_start), min(getdate(end), window_end)) for start, end in periods
    )
    covered_days = 0
    counted_until = None
    for start, end in clipped:
        if counted_until is not None:
            start = max(start, add_days(counted_until, 1))
        if start > end:
            continue
        covered_days += (end - start).days + 1
        counted_until = end
    return covered_days


def get_calendar_data():
    """Get current calendar data"""

    # Site-tz: the month/year shown must be the site's, matching every date this
    # page renders beside it (#637).
    now = now_datetime()
    month_names = [
        _("January"),
        _("February"),
        _("March"),
        _("April"),
        _("May"),
        _("June"),
        _("July"),
        _("August"),
        _("September"),
        _("October"),
        _("November"),
        _("December"),
    ]

    return {"month_name": month_names[now.month - 1], "month_num": now.month, "year": now.year}


def get_next_payment(member):
    """Get next payment due"""

    customer = frappe.db.get_value("Member", member, "customer")

    next_invoice = frappe.db.get_value(
        "Sales Invoice",
        {"customer": customer, "docstatus": 1, "outstanding_amount": [">", 0], "due_date": [">=", today()]},
        ["name", "due_date", "outstanding_amount"],
        order_by="due_date",
        as_dict=True,
    )

    return next_invoice


@frappe.whitelist()
@self_service_api(operation_type=OperationType.MEMBER_DATA, implicit_allowed=True)
def export_schedule():
    """Export dues schedule as CSV via Frappe response download."""
    # Get current user's member record
    member = get_current_user_member_name_required()

    # Get payment data
    payment_data = get_payment_data(member)

    # Build CSV content with proper quoting via csv module
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([_("Date"), _("Amount"), _("Status"), _("Description")])
    for payment in payment_data:
        writer.writerow([payment["date"], payment["amount"], payment["status"], payment["description"]])
    csv_content = output.getvalue()

    # Serve file via Frappe response mechanism
    frappe.response["filename"] = f"dues_schedule_{member}_{today().replace('-', '')}.csv"
    frappe.response["filecontent"] = csv_content
    frappe.response["type"] = "download"


@frappe.whitelist()
@self_service_api(operation_type=OperationType.MEMBER_DATA, implicit_allowed=True)
def get_payment_details(date):
    """Get payment details for a specific date"""
    # Get current user's member record
    member = get_current_user_member_name_required()

    # Get payment data
    payment_data = get_payment_data(member)

    # Find payment for the specific date
    payment = next((p for p in payment_data if p["date"] == date), None)

    if payment:
        return payment
    else:
        frappe.throw(_("No payment found for the specified date"), frappe.DoesNotExistError)
