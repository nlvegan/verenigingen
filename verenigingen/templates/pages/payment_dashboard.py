from datetime import datetime

import frappe
from frappe import _
from frappe.utils import add_months, flt, getdate, today

from verenigingen.utils.member_utils import get_current_user_member_name, get_member_customer


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
            "status",
        ],
        as_dict=True,
    )

    if schedule:
        dues_rate = flt(schedule.dues_rate, 2) or 0
        # Calculate monthly amount from billing frequency
        if schedule.billing_frequency == "Monthly":
            schedule["monthly_amount"] = dues_rate
        elif schedule.billing_frequency == "Quarterly":
            schedule["monthly_amount"] = flt(dues_rate / 3, 2)
        elif schedule.billing_frequency == "Semi-Annual":
            schedule["monthly_amount"] = flt(dues_rate / 6, 2)
        elif schedule.billing_frequency == "Annual":
            schedule["monthly_amount"] = flt(dues_rate / 12, 2)
        else:
            schedule["monthly_amount"] = dues_rate

    return schedule


def get_financial_overview(member):
    """Get financial overview data for the member"""
    customer = get_member_customer(member)
    if not customer:
        return {
            "next_payment": None,
            "total_paid_year": 0,
            "yearly_progress": 0,
            "payment_count": 0,
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
    from verenigingen.utils.payment_utils import get_total_payments_for_year

    total_paid_year = get_total_payments_for_year(customer, datetime.now().year)

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

    return {
        "next_payment": next_payment,
        "total_paid_year": total_paid_year,
        "yearly_progress": round(yearly_progress, 1),
        "payment_count": get_payment_count_for_year(customer),
    }


def get_payment_count_for_year(customer):
    """Get count of payments made this year"""
    year_start = f"{datetime.now().year}-01-01"
    return frappe.db.count(
        "Payment Entry",
        {
            "party_type": "Customer",
            "party": customer,
            "docstatus": 1,
            "posting_date": [">=", year_start],
        },
    )


def get_recent_activity(member):
    """Get recent financial activity for the member"""
    customer = get_member_customer(member)
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
        fields=["name", "posting_date", "paid_amount"],
        order_by="posting_date desc",
        limit=3,
    )

    for payment in recent_payments:
        activity.append(
            {
                "title": _("Payment Made"),
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
        status = "paid" if flt(invoice.outstanding_amount, 2) <= 0.01 else "due"
        activity.append(
            {
                "title": _("Dues invoice generated"),
                "description": f"Invoice {invoice.name}",
                "date": invoice.posting_date,
                "amount": invoice.grand_total,
                "status": status,
            }
        )

    # Sort by date
    activity.sort(key=lambda x: getdate(x["date"]), reverse=True)
    return activity[:5]


def get_notification_settings(member):
    """Get notification settings for the member"""
    return {
        "email_enabled": True,
        "reminders_enabled": True,
        "failure_enabled": True,
    }


def get_context(context):
    # Check if user is logged in
    if frappe.session.user == "Guest":
        frappe.throw(_("You need to be logged in to access this page"), frappe.PermissionError)

    # Check if user has appropriate permissions
    is_member = frappe.db.exists("Has Role", {"parent": frappe.session.user, "role": "Verenigingen Member"})
    is_admin = frappe.db.exists(
        "Has Role",
        {
            "parent": frappe.session.user,
            "role": ["in", ["System Manager", "Verenigingen Staff", "Verenigingen Administrator"]],
        },
    )

    if not is_member and not is_admin:
        frappe.throw(_("You don't have permission to access this page"), frappe.PermissionError)

    # Get member parameter from URL if admin is viewing
    member_param = frappe.form_dict.get("member")

    if is_admin and member_param:
        # Admin viewing specific member's dashboard
        # Validate member parameter is not empty or None
        if not member_param or member_param.strip() == "":
            frappe.throw(_("Invalid member parameter provided"), frappe.ValidationError)

        if frappe.db.exists("Member", member_param):
            context.member = member_param
            context.viewing_as_admin = True
            member_doc = frappe.get_doc("Member", member_param)
            context.member_name = member_doc.full_name
        else:
            frappe.throw(_("Member {0} not found").format(member_param), frappe.DoesNotExistError)
    else:
        # Get member record for logged in user using standardized utility
        member = get_current_user_member_name()

        if not member and is_member:
            frappe.throw(_("No member record found for your account"), frappe.DoesNotExistError)
        elif not member and is_admin:
            # Admin without member record - show member selection
            context.show_member_selection = True
            context.members = frappe.get_all(
                "Member", fields=["name", "full_name", "email"], order_by="full_name"
            )
        else:
            context.member = member

    context.title = _("Payment Dashboard")
    context.is_admin = is_admin

    # Add brand CSS
    context.brand_css = "/brand_css"

    # Add bank details context data when member is available
    if context.get("member"):
        _add_bank_details_context(context)

    return context


def _add_bank_details_context(context):
    """Add bank details context data"""
    # Import helpers from their new locations
    from verenigingen.services.payment.sepa_mandate_manager import get_active_sepa_mandate
    from verenigingen.utils.mollie_data_validator import parse_mollie_customer_ids

    # Ensure CSRF token is available
    context.csrf_token = frappe.session.csrf_token

    # Get member document
    member_doc = frappe.get_doc("Member", context.member)
    context.member_doc = member_doc

    # Get current bank details
    current_details = {
        "iban": member_doc.iban,
        "bic": member_doc.bic,
        "bank_account_name": member_doc.bank_account_name,
    }
    context.current_details = current_details

    # Check for active SEPA mandate
    context.current_mandate = get_active_sepa_mandate(context.member)

    # Get Mollie subscription information from MEMBER record only (not donor)
    # Dues/payment dashboard should only check membership payment methods, not donation methods
    mollie_customers = []

    # Check member record for Mollie customer ID (regardless of payment method)
    # Support comma-separated customer IDs for members with multiple Mollie accounts
    if member_doc.mollie_customer_id:
        customer_ids = parse_mollie_customer_ids(member_doc.mollie_customer_id, max_ids=5)
        for customer_id in customer_ids:
            mollie_customers.append(
                {
                    "customer_id": customer_id,
                    "subscription_id": member_doc.mollie_subscription_id,
                    "status": member_doc.subscription_status,
                    "next_payment_date": member_doc.next_payment_date,
                    "cancelled_date": member_doc.subscription_cancelled_date,
                    "source": "member",
                    "payment_method": member_doc.payment_method,  # Track what it's used for
                }
            )

    # Store Mollie customers from member record only
    context.mollie_customers = mollie_customers
    # Keep legacy field for backward compatibility
    context.mollie_subscription = mollie_customers[0] if mollie_customers else None

    # Get active dues schedule for displaying current rate
    if member_doc.current_dues_schedule:
        try:
            schedule = frappe.get_doc("Membership Dues Schedule", member_doc.current_dues_schedule)
            context.active_dues_schedule = {
                "name": schedule.name,
                "amount": schedule.dues_rate,  # Use dues_rate instead of amount
                "billing_frequency": schedule.billing_frequency,
            }
        except Exception:
            context.active_dues_schedule = None
    else:
        context.active_dues_schedule = None

    # Add merged financial dashboard data
    context.current_schedule = get_current_dues_schedule(context.member)
    context.financial_overview = get_financial_overview(context.member)
    context.recent_activity = get_recent_activity(context.member)
    context.notification_settings = get_notification_settings(context.member)
