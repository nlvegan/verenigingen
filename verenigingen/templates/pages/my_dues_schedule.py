import calendar
import json
from datetime import datetime, timedelta

import frappe
from frappe import _
from frappe.utils import add_months, flt, format_date, getdate, today


def get_context(context):
    """Get context for the dues schedule page"""

    # Check if user is logged in
    if frappe.session.user == "Guest":
        frappe.throw(_("You need to be logged in to view this page"), frappe.PermissionError)

    # Get current user's member record
    member = frappe.db.get_value("Member", {"user": frappe.session.user}, "name")
    if not member:
        frappe.throw(_("Member record not found"), frappe.DoesNotExistError)

    # Get current dues schedule
    current_schedule = get_current_dues_schedule(member)

    # Get payment data
    payment_data = get_payment_data(member)
    payment_timeline = get_payment_timeline(member)

    # Get coverage information
    coverage_info = get_coverage_info(current_schedule)

    # Get calendar data
    calendar_data = get_calendar_data()

    # Get next payment
    next_payment = get_next_payment(member)

    # Get contact email
    member_contact_email = (
        frappe.db.get_single_value("Verenigingen Settings", "member_contact_email") or "info@vereniging.nl"
    )

    context.update(
        {
            "member": member,
            "current_schedule": current_schedule,
            "payment_data": json.dumps(payment_data),
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


def get_current_dues_schedule(member):
    """Get the current active dues schedule for a member"""

    schedule = frappe.db.get_value(
        "Membership Dues Schedule",
        {"member": member, "status": "Active"},
        [
            "name",
            "contribution_mode",
            "billing_frequency",
            "start_date",
            "end_date",
            "monthly_amount",
            "payment_method",
            "auto_renewal",
            "email_notifications",
        ],
        as_dict=True,
    )

    return schedule


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
            if getdate(invoice.due_date) < getdate(today()):
                status = "overdue"
            else:
                status = "due"

        payment_data.append(
            {
                "date": str(invoice.due_date),
                "amount": flt(invoice.grand_total, 2),
                "status": status,
                "description": f"Invoice {invoice.name}",
                "invoice_link": f"/app/sales-invoice/{invoice.name}",
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
                "description": f"Payment {payment.name}",
                "invoice_link": f"/app/payment-entry/{payment.name}",
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
                "description": f"Invoice {invoice.name}",
                "invoice_link": f"/app/sales-invoice/{invoice.name}",
            }
        )

    # Sort by date
    timeline.sort(key=lambda x: getdate(x["due_date"]), reverse=True)

    return timeline[:10]  # Return most recent 10 items


def get_coverage_info(current_schedule):
    """Calculate coverage information"""

    if not current_schedule:
        return {"percentage": 0, "covered_months": 0, "total_months": 0}

    # For now, return sample data
    # In production, this would calculate actual coverage based on payments
    return {"percentage": 75, "covered_months": 9, "total_months": 12}


def get_calendar_data():
    """Get current calendar data"""

    now = datetime.now()
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
def export_schedule():
    """Export dues schedule as CSV"""

    # Check if user is logged in
    if frappe.session.user == "Guest":
        frappe.throw(_("You need to be logged in to export schedule"), frappe.PermissionError)

    # Get current user's member record
    member = frappe.db.get_value("Member", {"user": frappe.session.user}, "name")
    if not member:
        frappe.throw(_("Member record not found"), frappe.DoesNotExistError)

    # Get payment data
    payment_data = get_payment_data(member)

    # Create CSV content
    csv_content = "Date,Amount,Status,Description\n"
    for payment in payment_data:
        csv_content += f"{payment['date']},{payment['amount']},{payment['status']},{payment['description']}\n"

    # Create file
    filename = f"dues_schedule_{member}_{today().replace('-', '')}.csv"
    file_path = f"/tmp/{filename}"

    with open(file_path, "w") as f:
        f.write(csv_content)

    # Return file info
    return {"filename": filename, "url": f"/files/{filename}"}


@frappe.whitelist()
def get_payment_details(date):
    """Get payment details for a specific date"""

    # Check if user is logged in
    if frappe.session.user == "Guest":
        frappe.throw(_("You need to be logged in to view payment details"), frappe.PermissionError)

    # Get current user's member record
    member = frappe.db.get_value("Member", {"user": frappe.session.user}, "name")
    if not member:
        frappe.throw(_("Member record not found"), frappe.DoesNotExistError)

    # Get payment data
    payment_data = get_payment_data(member)

    # Find payment for the specific date
    payment = next((p for p in payment_data if p["date"] == date), None)

    if payment:
        return payment
    else:
        frappe.throw(_("No payment found for the specified date"), frappe.DoesNotExistError)


@frappe.whitelist()
def update_notification_settings(email_notifications=None, auto_renewal=None):
    """Update notification settings for current user's dues schedule"""

    # Check if user is logged in
    if frappe.session.user == "Guest":
        frappe.throw(_("You need to be logged in to update settings"), frappe.PermissionError)

    # Get current user's member record
    member = frappe.db.get_value("Member", {"user": frappe.session.user}, "name")
    if not member:
        frappe.throw(_("Member record not found"), frappe.DoesNotExistError)

    # Get current dues schedule
    schedule_name = frappe.db.get_value(
        "Membership Dues Schedule", {"member": member, "status": "Active"}, "name"
    )

    if not schedule_name:
        frappe.throw(_("No active dues schedule found"), frappe.DoesNotExistError)

    # Update settings
    schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)

    if email_notifications is not None:
        schedule.email_notifications = int(email_notifications)

    if auto_renewal is not None:
        schedule.auto_renewal = int(auto_renewal)

    schedule.save()

    return {"success": True, "message": _("Settings updated successfully")}
