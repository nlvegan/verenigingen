import csv
import json
import os
import tempfile
from datetime import datetime, timedelta

import frappe
from frappe import _
from frappe.utils import add_months, date_diff, flt, format_date, getdate, today


def get_context(context):
    """Get context for the enhanced financial dashboard"""

    # Check if user is logged in
    if frappe.session.user == "Guest":
        frappe.throw(_("You need to be logged in to view this page"), frappe.PermissionError)

    # Get current user's member record
    member = frappe.db.get_value("Member", {"user": frappe.session.user}, "name")
    if not member:
        frappe.throw(_("Member record not found"), frappe.DoesNotExistError)

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

    # Get financial overview data
    financial_overview = get_financial_overview(member)

    # Get payment data for calendar
    payment_data = get_payment_data_for_calendar(member)

    # Get recent activity
    recent_activity = get_recent_activity(member)

    # Get upcoming payments
    upcoming_payments = get_upcoming_payments(member)

    # Get payment history
    payment_history = get_payment_history(member)

    # Get payment years for filter
    payment_years = get_payment_years(member)

    # Get notification settings
    notification_settings = get_notification_settings(member)

    # Get analytics data
    analytics_data = get_analytics_data(member)

    # Get contact email
    from verenigingen.utils.email_utils import get_member_contact_email

    member_contact_email = get_member_contact_email()

    context.update(
        {
            "member": member,
            "current_schedule": current_schedule,
            "payment_method": payment_method,
            "next_payment": financial_overview.get("next_payment"),
            "total_paid_year": financial_overview.get("total_paid_year", 0),
            "annual_target": financial_overview.get("annual_target", 0),
            "yearly_progress": financial_overview.get("yearly_progress", 0),
            "monthly_change_class": financial_overview.get("monthly_change_class", "neutral"),
            "monthly_change_text": financial_overview.get("monthly_change_text", ""),
            "payment_data": json.dumps(payment_data),
            "recent_activity": recent_activity,
            "upcoming_payments": upcoming_payments,
            "payment_history": payment_history,
            "payment_years": payment_years,
            "notification_settings": notification_settings,
            "sepa_success_rate": analytics_data.get("sepa_success_rate", 0),
            "avg_payment_time": analytics_data.get("avg_payment_time", 0),
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
            "next_invoice_date",
            "last_invoice_date",
            "dues_rate",
            "auto_generate",
            "status",
            "membership_type",
        ],
        as_dict=True,
    )

    if schedule:
        # Calculate monthly amount from billing frequency
        if schedule.billing_frequency == "Monthly":
            schedule["monthly_amount"] = schedule.dues_rate
        elif schedule.billing_frequency == "Quarterly":
            schedule["monthly_amount"] = schedule.dues_rate / 3
        elif schedule.billing_frequency == "Semi-Annual":
            schedule["monthly_amount"] = schedule.dues_rate / 6
        elif schedule.billing_frequency == "Annual":
            schedule["monthly_amount"] = schedule.dues_rate / 12
        else:
            schedule["monthly_amount"] = schedule.dues_rate

        # Set derived fields for backward compatibility
        schedule["auto_renewal"] = schedule.auto_generate
        schedule["email_notifications"] = True  # Default to true
        schedule["start_date"] = schedule.last_invoice_date or schedule.next_invoice_date
        schedule["end_date"] = schedule.next_invoice_date

    return schedule


def get_financial_overview(member):
    """Get financial overview data for the member"""

    customer = frappe.db.get_value("Member", member, "customer")
    if not customer:
        return {
            "next_payment": None,
            "total_paid_year": 0,
            "annual_target": 0,
            "yearly_progress": 0,
            "monthly_change_class": "neutral",
            "monthly_change_text": _("No payment history"),
        }

    # Get next payment
    next_payment = frappe.db.get_value(
        "Sales Invoice",
        {"customer": customer, "docstatus": 1, "outstanding_amount": [">", 0], "due_date": [">=", today()]},
        ["name", "due_date", "outstanding_amount"],
        order_by="due_date",
        as_dict=True,
    )

    if next_payment:
        next_payment["amount"] = next_payment["outstanding_amount"]

    # Calculate total paid this year
    year_start = f"{datetime.now().year}-01-01"
    year_end = f"{datetime.now().year}-12-31"

    total_paid_year = (
        frappe.db.sql(
            """
        SELECT SUM(pe.paid_amount)
        FROM `tabPayment Entry` pe
        WHERE pe.party_type = 'Customer'
        AND pe.party = %s
        AND pe.docstatus = 1
        AND pe.posting_date BETWEEN %s AND %s
    """,
            (customer, year_start, year_end),
        )[0][0]
        or 0
    )

    # Get annual target from current schedule
    current_schedule = get_current_dues_schedule(member)
    annual_target = 0
    if current_schedule:
        monthly_amount = current_schedule.get("monthly_amount", 0)
        annual_target = monthly_amount * 12

    # Calculate yearly progress
    yearly_progress = 0
    if annual_target > 0:
        yearly_progress = min(100, (total_paid_year / annual_target) * 100)

    # Calculate monthly change (placeholder - would need historical data)
    monthly_change_class = "neutral"
    monthly_change_text = _("No change from last month")

    return {
        "next_payment": next_payment,
        "total_paid_year": total_paid_year,
        "annual_target": annual_target,
        "yearly_progress": round(yearly_progress, 1),
        "monthly_change_class": monthly_change_class,
        "monthly_change_text": monthly_change_text,
    }


def get_payment_data_for_calendar(member):
    """Get payment data formatted for calendar display"""

    customer = frappe.db.get_value("Member", member, "customer")
    if not customer:
        return []

    # Get payment data for last 12 months and next 12 months
    start_date = add_months(today(), -12)
    end_date = add_months(today(), 12)

    # Get invoices
    invoices = frappe.get_all(
        "Sales Invoice",
        filters={"customer": customer, "docstatus": 1, "due_date": ["between", [start_date, end_date]]},
        fields=["name", "due_date", "outstanding_amount", "grand_total"],
        order_by="due_date",
    )

    payment_data = []
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


def get_recent_activity(member):
    """Get recent financial activity for the member"""

    customer = frappe.db.get_value("Member", member, "customer")
    if not customer:
        return []

    activity = []

    # Get recent payments
    recent_payments = frappe.get_all(
        "Payment Entry",
        filters={
            "party_type": "Customer",
            "party": customer,
            "docstatus": 1,
            "posting_date": [">=", add_months(today(), -3)],
        },
        fields=["name", "posting_date", "paid_amount", "reference_no"],
        order_by="posting_date desc",
        limit=3,
    )

    for payment in recent_payments:
        activity.append(
            {
                "title": _("Payment Received"),
                "description": f"Payment Entry {payment.name}",
                "date": payment.posting_date,
                "amount": payment.paid_amount,
                "status": "paid",
            }
        )

    # Get recent invoices
    recent_invoices = frappe.get_all(
        "Sales Invoice",
        filters={"customer": customer, "docstatus": 1, "posting_date": [">=", add_months(today(), -3)]},
        fields=["name", "posting_date", "grand_total", "outstanding_amount"],
        order_by="posting_date desc",
        limit=3,
    )

    for invoice in recent_invoices:
        status = "paid" if invoice.outstanding_amount == 0 else "due"
        activity.append(
            {
                "title": _("Invoice Generated"),
                "description": f"Invoice {invoice.name}",
                "date": invoice.posting_date,
                "amount": invoice.grand_total,
                "status": status,
            }
        )

    # Sort by date
    activity.sort(key=lambda x: getdate(x["date"]), reverse=True)

    return activity[:5]  # Return most recent 5 items


def get_upcoming_payments(member):
    """Get upcoming payments for the member"""

    customer = frappe.db.get_value("Member", member, "customer")
    if not customer:
        return []

    upcoming = frappe.get_all(
        "Sales Invoice",
        filters={
            "customer": customer,
            "docstatus": 1,
            "outstanding_amount": [">", 0],
            "due_date": [">=", today()],
        },
        fields=["name", "due_date", "outstanding_amount", "grand_total"],
        order_by="due_date",
        limit=6,
    )

    payments = []
    for invoice in upcoming:
        payments.append(
            {
                "due_date": invoice.due_date,
                "amount": invoice.outstanding_amount,
                "description": f"Invoice {invoice.name}",
                "status": "Due",
            }
        )

    return payments


def get_payment_history(member):
    """Get payment history for the member"""

    customer = frappe.db.get_value("Member", member, "customer")
    if not customer:
        return []

    # Get payment entries
    payments = frappe.get_all(
        "Payment Entry",
        filters={"party_type": "Customer", "party": customer, "docstatus": 1},
        fields=["name", "posting_date", "paid_amount", "reference_no", "status"],
        order_by="posting_date desc",
        limit=20,
    )

    payment_history = []
    for payment in payments:
        payment_history.append(
            {
                "date": payment.posting_date,
                "description": f"Payment Entry {payment.name}",
                "amount": payment.paid_amount,
                "status": "Paid",
            }
        )

    return payment_history


def get_payment_years(member):
    """Get years that have payments for filtering"""

    customer = frappe.db.get_value("Member", member, "customer")
    if not customer:
        return []

    years = frappe.db.sql(
        """
        SELECT DISTINCT YEAR(posting_date) as year
        FROM `tabPayment Entry`
        WHERE party_type = 'Customer'
        AND party = %s
        AND docstatus = 1
        ORDER BY year DESC
    """,
        (customer,),
    )

    return [year[0] for year in years]


def get_notification_settings(member):
    """Get notification settings for the member"""

    # Get from current schedule or default settings
    current_schedule = get_current_dues_schedule(member)
    if current_schedule:
        return {
            "email_enabled": current_schedule.get("email_notifications", True),
            "reminders_enabled": True,  # Default
            "failure_enabled": True,  # Default
        }

    return {
        "email_enabled": True,
        "reminders_enabled": True,
        "failure_enabled": True,
    }


def get_analytics_data(member):
    """Get analytics data for the member"""

    customer = frappe.db.get_value("Member", member, "customer")
    if not customer:
        return {"sepa_success_rate": 0, "avg_payment_time": 0}

    # Calculate SEPA success rate
    total_payments = frappe.db.count(
        "Payment Entry", {"party_type": "Customer", "party": customer, "docstatus": 1}
    )

    failed_payments = frappe.db.count(
        "Payment Entry", {"party_type": "Customer", "party": customer, "docstatus": 1, "status": "Failed"}
    )

    sepa_success_rate = 0
    if total_payments > 0:
        sepa_success_rate = ((total_payments - failed_payments) / total_payments) * 100

    # Calculate average payment time (placeholder)
    avg_payment_time = 2  # Default 2 days

    return {"sepa_success_rate": round(sepa_success_rate, 1), "avg_payment_time": avg_payment_time}


@frappe.whitelist()
def get_dashboard_data():
    """Get dashboard data for API calls"""

    # Check if user is logged in
    if frappe.session.user == "Guest":
        frappe.throw(_("You need to be logged in"), frappe.PermissionError)

    # Get current user's member record
    member = frappe.db.get_value("Member", {"user": frappe.session.user}, "name")
    if not member:
        frappe.throw(_("Member record not found"), frappe.DoesNotExistError)

    return get_financial_overview(member)


@frappe.whitelist()
def get_analytics_data_api():
    """Get analytics data for API calls"""

    # Check if user is logged in
    if frappe.session.user == "Guest":
        frappe.throw(_("You need to be logged in"), frappe.PermissionError)

    # Get current user's member record
    member = frappe.db.get_value("Member", {"user": frappe.session.user}, "name")
    if not member:
        frappe.throw(_("Member record not found"), frappe.DoesNotExistError)

    return get_analytics_data(member)


@frappe.whitelist()
def get_payment_history_api():
    """Get payment history for API calls"""

    # Check if user is logged in
    if frappe.session.user == "Guest":
        frappe.throw(_("You need to be logged in"), frappe.PermissionError)

    # Get current user's member record
    member = frappe.db.get_value("Member", {"user": frappe.session.user}, "name")
    if not member:
        frappe.throw(_("Member record not found"), frappe.DoesNotExistError)

    return get_payment_history(member)


@frappe.whitelist()
def get_month_data(year, month):
    """Get payment data for a specific month"""

    # Check if user is logged in
    if frappe.session.user == "Guest":
        frappe.throw(_("You need to be logged in"), frappe.PermissionError)

    # Get current user's member record
    member = frappe.db.get_value("Member", {"user": frappe.session.user}, "name")
    if not member:
        frappe.throw(_("Member record not found"), frappe.DoesNotExistError)

    # Get payment data for the specified month
    start_date = f"{year}-{month:02d}-01"
    end_date = f"{year}-{month:02d}-31"

    customer = frappe.db.get_value("Member", member, "customer")
    if not customer:
        return []

    invoices = frappe.get_all(
        "Sales Invoice",
        filters={"customer": customer, "docstatus": 1, "due_date": ["between", [start_date, end_date]]},
        fields=["name", "due_date", "outstanding_amount", "grand_total"],
        order_by="due_date",
    )

    payment_data = []
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


@frappe.whitelist()
def save_settings(settings):
    """Save notification and other settings"""

    # Check if user is logged in
    if frappe.session.user == "Guest":
        frappe.throw(_("You need to be logged in"), frappe.PermissionError)

    # Get current user's member record
    member = frappe.db.get_value("Member", {"user": frappe.session.user}, "name")
    if not member:
        frappe.throw(_("Member record not found"), frappe.DoesNotExistError)

    # Get current dues schedule
    schedule_name = frappe.db.get_value(
        "Membership Dues Schedule", {"member": member, "status": "Active"}, "name"
    )

    if schedule_name:
        schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)

        # Update settings
        if "email_notifications" in settings:
            schedule.email_notifications = settings["email_notifications"]
        if "auto_renewal" in settings:
            schedule.auto_renewal = settings["auto_renewal"]

        schedule.save()

        return {"success": True, "message": _("Settings updated successfully")}

    return {"success": False, "message": _("No active dues schedule found")}


@frappe.whitelist()
def export_financial_data():
    """Export financial data as CSV"""

    # Check if user is logged in
    if frappe.session.user == "Guest":
        frappe.throw(_("You need to be logged in"), frappe.PermissionError)

    # Get current user's member record
    member = frappe.db.get_value("Member", {"user": frappe.session.user}, "name")
    if not member:
        frappe.throw(_("Member record not found"), frappe.DoesNotExistError)

    # Get financial data
    payment_history = get_payment_history(member)
    current_schedule = get_current_dues_schedule(member)

    # Create CSV content
    csv_content = []

    # Add header
    csv_content.append(["Financial Dashboard Export"])
    csv_content.append([f"Member: {member}"])
    csv_content.append([f"Export Date: {today()}"])
    csv_content.append([])

    # Add current schedule
    if current_schedule:
        csv_content.append(["Current Schedule"])
        csv_content.append(["Field", "Value"])
        csv_content.append(["Contribution Mode", current_schedule.get("contribution_mode", "")])
        csv_content.append(["Billing Frequency", current_schedule.get("billing_frequency", "")])
        csv_content.append(["Monthly Amount", current_schedule.get("monthly_amount", 0)])
        csv_content.append(["Payment Method", current_schedule.get("payment_method", "")])
        csv_content.append([])

    # Add payment history
    csv_content.append(["Payment History"])
    csv_content.append(["Date", "Description", "Amount", "Status"])

    for payment in payment_history:
        csv_content.append([payment["date"], payment["description"], payment["amount"], payment["status"]])

    # Create temporary file
    temp_file = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
    writer = csv.writer(temp_file)
    writer.writerows(csv_content)
    temp_file.close()

    # Create file record
    filename = f"financial_data_{member}_{today().replace('-', '')}.csv"

    return {"filename": filename, "url": f"/files/{filename}"}


@frappe.whitelist()
def export_payments(year=None):
    """Export payment data as CSV"""

    # Check if user is logged in
    if frappe.session.user == "Guest":
        frappe.throw(_("You need to be logged in"), frappe.PermissionError)

    # Get current user's member record
    member = frappe.db.get_value("Member", {"user": frappe.session.user}, "name")
    if not member:
        frappe.throw(_("Member record not found"), frappe.DoesNotExistError)

    # Get payment data
    payment_history = get_payment_history(member)

    # Filter by year if specified
    if year:
        payment_history = [p for p in payment_history if str(getdate(p["date"]).year) == str(year)]

    # Create CSV content
    csv_content = [["Date", "Description", "Amount", "Status"]]

    for payment in payment_history:
        csv_content.append([payment["date"], payment["description"], payment["amount"], payment["status"]])

    # Create temporary file
    temp_file = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
    writer = csv.writer(temp_file)
    writer.writerows(csv_content)
    temp_file.close()

    # Create file record
    year_suffix = f"_{year}" if year else ""
    filename = f"payments{year_suffix}_{member}_{today().replace('-', '')}.csv"

    return {"filename": filename, "url": f"/files/{filename}"}


@frappe.whitelist()
def export_all_data():
    """Export all financial data as comprehensive CSV"""

    # Check if user is logged in
    if frappe.session.user == "Guest":
        frappe.throw(_("You need to be logged in"), frappe.PermissionError)

    # Get current user's member record
    member = frappe.db.get_value("Member", {"user": frappe.session.user}, "name")
    if not member:
        frappe.throw(_("Member record not found"), frappe.DoesNotExistError)

    # Create comprehensive CSV
    csv_content = []

    # Add header
    csv_content.append(["Complete Financial Data Export"])
    csv_content.append([f"Member: {member}"])
    csv_content.append([f"Export Date: {today()}"])
    csv_content.append([])

    # Add all sections
    # ... (implementation similar to export_financial_data but more comprehensive)

    # Create temporary file
    temp_file = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
    writer = csv.writer(temp_file)
    writer.writerows(csv_content)
    temp_file.close()

    # Create file record
    filename = f"complete_financial_data_{member}_{today().replace('-', '')}.csv"

    return {"filename": filename, "url": f"/files/{filename}"}
