from datetime import datetime

import frappe
from frappe import _
from frappe.utils import add_months, flt, getdate, today

from verenigingen.utils.constants import Limits, Membership, PaymentStatus
from verenigingen.utils.error_handling import cache_with_ttl, handle_api_error, validate_required_fields
from verenigingen.utils.migration.migration_performance import BatchProcessor
from verenigingen.utils.performance_utils import performance_monitor


def validate_member_exists(member_id: str | None) -> str:
    """Validate member exists and return member ID - development helper"""
    member = get_member_from_user(member_id)
    if not member:
        frappe.throw(_("Member not found"), frappe.DoesNotExistError)
    return member


@handle_api_error
@performance_monitor()
@frappe.whitelist()
def get_dashboard_data(member=None):
    """Get payment dashboard summary data"""
    # Get actual member ID
    # Modernized validation with helper
    member = validate_member_exists(member)

    member_doc = frappe.get_doc("Member", member)

    # Get payment summary
    current_year = datetime.now().year

    # Get total paid this year
    total_paid_year = (
        frappe.db.sql(
            """
        SELECT COALESCE(SUM(paid_amount), 0)
        FROM `tabPayment Entry`
        WHERE party_type = 'Customer'
        AND party = %s
        AND YEAR(posting_date) = %s
        AND docstatus = 1
    """,
            (member_doc.customer, current_year),
        )[0][0]
        if member_doc.customer
        else 0
    )

    # Get payment count
    payment_count = (
        frappe.db.count(
            "Payment Entry", {"party_type": "Customer", "party": member_doc.customer, "docstatus": 1}
        )
        if member_doc.customer
        else 0
    )

    # Check for failed payments - optimized ORM approach
    has_failed_payments = False
    if member_doc.customer:
        # Get active dues schedule for date range validation - optimized query
        active_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member, "status": Membership.STATUS_ACTIVE},
            fields=["next_billing_period_start_date", "next_billing_period_end_date"],
            limit=1,  # Usually only one active schedule per member
            order_by="creation DESC",  # Get most recent if multiple exist
        )

        if active_schedules:
            schedule = active_schedules[0]
            # Build filters for overdue invoices within dues schedule period
            invoice_filters = {
                "customer": member_doc.customer,
                "status": PaymentStatus.INVOICE_OVERDUE,
                "docstatus": 1,
                "posting_date": [">=", schedule.next_billing_period_start_date],
            }

            # Add end date filter if schedule has one
            if schedule.next_billing_period_end_date:
                invoice_filters["posting_date"] = [
                    "between",
                    [schedule.next_billing_period_start_date, schedule.next_billing_period_end_date],
                ]

            # Use count() for efficiency - indexed query
            failed_count = frappe.db.count("Sales Invoice", invoice_filters)
            has_failed_payments = failed_count > 0

    # Get next payment info
    next_payment = get_next_payment(member)

    # Check if mandate is expiring soon
    mandate_expiring_soon = False
    active_mandate = member_doc.get_active_sepa_mandate()
    if active_mandate and active_mandate.expiry_date:
        days_to_expiry = (getdate(active_mandate.expiry_date) - getdate(today())).days
        mandate_expiring_soon = 0 < days_to_expiry <= 30

    return {
        "total_paid_year": flt(total_paid_year, 2),
        "payment_count": payment_count,
        "has_failed_payments": has_failed_payments,
        "next_payment": next_payment,
        "mandate_expiring_soon": mandate_expiring_soon,
    }


@frappe.whitelist()
def get_payment_method(member=None):
    """Get active payment method details"""
    # Get actual member ID
    # Modernized validation with helper
    member = validate_member_exists(member)

    member_doc = frappe.get_doc("Member", member)
    active_mandate = member_doc.get_active_sepa_mandate()

    if active_mandate:
        from verenigingen.utils.validation.iban_validator import format_iban

        return {
            "has_active_mandate": True,
            "mandate": {
                "mandate_id": active_mandate.mandate_id,
                "iban": format_iban(active_mandate.iban),
                "bic": active_mandate.bic,
                "account_holder": active_mandate.account_holder_name,
                "sign_date": str(active_mandate.sign_date),
                "status": active_mandate.status,
                "expiry_date": str(active_mandate.expiry_date) if active_mandate.expiry_date else None,
            },
        }

    return {"has_active_mandate": False}


@handle_api_error
@frappe.whitelist()
def get_payment_history(member=None, year=None, status=None, **kwargs):
    """Get payment history for member"""
    # Get actual member ID
    # Modernized validation with helper
    member = validate_member_exists(member)

    member_doc = frappe.get_doc("Member", member)

    if not member_doc.customer:
        return []

    # Build filters
    filters = {"party_type": "Customer", "party": member_doc.customer, "docstatus": 1}

    if year:
        filters["posting_date"] = ["between", [f"{year}-01-01", f"{year}-12-31"]]

    # Get payment entries
    payments = frappe.get_all(
        "Payment Entry",
        filters=filters,
        fields=[
            "name",
            "posting_date as date",
            "paid_amount as amount",
            "reference_no",
            "remarks",
            "mode_of_payment",
        ],
        order_by="posting_date desc",
        limit=limit,
        start=offset,
    )

    # Pagination support with constants for limits
    limit = frappe.utils.cint(kwargs.get("limit", Limits.DEFAULT_PAGE_SIZE * 5))  # 100 default
    offset = frappe.utils.cint(kwargs.get("offset", 0))
    if limit > Limits.MAX_PAGE_SIZE:
        limit = Limits.MAX_PAGE_SIZE  # Max limit for performance

    # Get sales invoices with membership info through dues schedule
    invoice_conditions = "si.customer = %(customer)s AND si.docstatus = 1"
    params = {"customer": member_doc.customer, "member": member}

    if year:
        invoice_conditions += " AND si.posting_date BETWEEN %(start_date)s AND %(end_date)s"
        params["start_date"] = f"{year}-01-01"
        params["end_date"] = f"{year}-12-31"

    invoices = frappe.db.sql(
        """
        SELECT
            si.name,
            si.posting_date as date,
            si.grand_total as amount,
            si.status,
            m.name as membership,
            mds.name as dues_schedule
        FROM `tabSales Invoice` si
        LEFT JOIN `tabMembership Dues Schedule` mds ON mds.member = %(member)s
        LEFT JOIN `tabMembership` m ON m.member = %(member)s
        WHERE {conditions}
        AND (mds.next_billing_period_start_date IS NULL OR si.posting_date >= mds.next_billing_period_start_date)
        AND (mds.next_billing_period_end_date IS NULL OR si.posting_date <= mds.next_billing_period_end_date)
        ORDER BY si.posting_date DESC
        LIMIT %(limit)s OFFSET %(offset)s
    """.format(
            conditions=invoice_conditions
        ),
        {**params, "limit": limit, "offset": offset},
        as_dict=True,
    )

    # Format payment history
    history = []

    # Batch fetch membership start dates to avoid N+1 queries - performance optimization
    membership_ids = [inv.membership for inv in invoices if inv.membership]
    membership_start_dates = {}
    if membership_ids:
        memberships = frappe.get_all(
            "Membership", filters={"name": ["in", membership_ids]}, fields=["name", "start_date"]
        )
        membership_start_dates = {m.name: m.start_date for m in memberships}

    for payment in payments:
        history.append(
            {
                "id": payment.name,
                "date": str(payment.date),
                "amount": flt(payment.amount, 2),
                "description": payment.remarks or f"Payment - {payment.mode_of_payment}",
                "status": "Paid",
                "type": "payment",
            }
        )

    for invoice in invoices:
        # Modernized with centralized status constants
        if invoice.status in PaymentStatus.PAID_STATUSES:
            status = PaymentStatus.STATUS_PAID
        elif invoice.status == PaymentStatus.INVOICE_OVERDUE:
            status = PaymentStatus.STATUS_FAILED
        else:
            status = PaymentStatus.STATUS_PENDING

        description = "Membership Fee"
        if invoice.membership and invoice.membership in membership_start_dates:
            start_date = membership_start_dates[invoice.membership]
            if start_date:
                from frappe.utils import getdate

                membership_year = getdate(start_date).year
                description = f"Membership Fee {membership_year}"

        history.append(
            {
                "id": invoice.name,
                "date": str(invoice.date),
                "amount": flt(invoice.amount, 2),
                "description": description,
                "status": status,
                "type": "invoice",
            }
        )

    # Sort by date
    history.sort(key=lambda x: x["date"], reverse=True)

    # Apply status filter if provided
    if status:
        history = [h for h in history if h["status"] == status]

    return history


@frappe.whitelist()
def get_mandate_history(member=None):
    """Get SEPA mandate history"""
    # Get actual member ID
    # Modernized validation with helper
    member = validate_member_exists(member)

    mandates = frappe.get_all(
        "SEPA Mandate",
        filters={"member": member},
        fields=[
            "name",
            "mandate_id",
            "iban",
            "bic",
            "status",
            "sign_date",
            "expiry_date",
            "cancelled_date",
            "cancellation_reason",
            "creation",
        ],
        order_by="creation desc",
    )

    # Format mandate data
    from verenigingen.utils.validation.iban_validator import format_iban, get_bank_from_iban

    for mandate in mandates:
        mandate["iban_formatted"] = format_iban(mandate.iban)
        bank_info = get_bank_from_iban(mandate.iban)
        mandate["bank_name"] = bank_info["bank_name"] if bank_info else "Unknown Bank"
        mandate["is_active"] = mandate.status == "Active"

    return mandates


@handle_api_error
@frappe.whitelist()
def get_payment_schedule(member=None):
    """Get upcoming payment schedule"""
    # Get actual member ID
    # Modernized validation with helper
    member = validate_member_exists(member)

    # Get active dues schedule
    active_dues_schedule = frappe.get_all(
        "Membership Dues Schedule",
        filters={"member": member, "status": "Active"},
        fields=[
            "name",
            "contribution_mode",
            "billing_frequency",
            "dues_rate",
            "next_invoice_date",
            "last_invoice_date",
        ],
        limit=1,
    )

    if not active_dues_schedule:
        return []

    dues_schedule = active_dues_schedule[0]
    schedule = []

    # Generate next 12 months of payments based on billing frequency - modernized with constants
    billing_frequency = dues_schedule.billing_frequency
    months = Membership.BILLING_FREQUENCY_MONTHS.get(billing_frequency, 1)  # Default to monthly

    # Calculate amount based on billing frequency
    dues_rate = flt(dues_schedule.dues_rate, 2)
    payment_amount = dues_rate * months

    current_date = getdate(today())
    for i in range(0, 12, months):
        payment_date = add_months(current_date, i)

        # Skip if payment date is in the past
        if payment_date < getdate(today()):
            continue

        # Check if payment date is beyond last invoice date (if set)
        if dues_schedule.last_invoice_date and payment_date > getdate(dues_schedule.last_invoice_date):
            break

        schedule.append(
            {
                "date": str(payment_date),
                "amount": payment_amount,
                "description": f"{dues_schedule.contribution_mode} - {billing_frequency} Payment",
                "status": "Scheduled",
            }
        )

    return schedule


@frappe.whitelist()
def get_next_payment(member=None):
    """Get next scheduled payment"""
    # Get actual member ID
    member = get_member_from_user(member)

    if not member:
        return None

    schedule = get_payment_schedule(member)

    if schedule:
        return {
            "date": schedule[0]["date"],
            "amount": schedule[0]["amount"],
            "description": schedule[0]["description"],
        }

    return None


@frappe.whitelist()
def retry_failed_payment(invoice_id):
    """Manually trigger payment retry"""
    invoice = frappe.get_doc("Sales Invoice", invoice_id)

    # Verify permissions
    member = get_member_from_user()

    # Allow administrators
    if frappe.has_permission("Sales Invoice", "write"):
        pass
    else:
        # Check if user is the member for this invoice
        membership = frappe.db.get_value("Membership", invoice.membership, "member")
        if membership != member:
            frappe.throw(_("You don't have permission to retry this payment"))

    # Check if already being retried
    existing_retry = frappe.db.exists(
        "SEPA Payment Retry", {"invoice": invoice_id, "status": ["in", ["Scheduled", "Pending"]]}
    )

    if existing_retry:
        frappe.throw(_("This payment is already scheduled for retry"))

    # Schedule retry
    from verenigingen.utils.payment_retry import PaymentRetryManager

    retry_manager = PaymentRetryManager()
    result = retry_manager.schedule_retry(invoice_id, "MANUAL", "Manual retry requested by member")

    if result["scheduled"]:
        return {"success": True, "message": result["message"], "next_retry": result["next_retry"]}
    else:
        return {"success": False, "message": result["message"]}


@frappe.whitelist()
def download_payment_receipt(payment_id):
    """Generate payment receipt PDF"""
    payment = frappe.get_doc("Payment Entry", payment_id)

    # Verify permissions
    member = get_member_from_user()
    member_doc = frappe.get_doc("Member", member)

    if payment.party != member_doc.customer:
        frappe.throw(_("You don't have permission to download this receipt"))

    # Generate PDF (this would use a print format)
    pdf = frappe.get_print("Payment Entry", payment_id, "Payment Receipt", as_pdf=True)

    frappe.local.response.filename = f"payment_receipt_{payment_id}.pdf"
    frappe.local.response.filecontent = pdf
    frappe.local.response.type = "pdf"


@frappe.whitelist()
def export_payment_history_csv(year=None):
    """Export payment history as CSV"""
    member = get_member_from_user()
    history = get_payment_history(member, year)

    import csv
    from io import StringIO

    output = StringIO()
    writer = csv.writer(output)

    # Write headers
    writer.writerow(["Date", "Description", "Amount", "Status", "Reference"])

    # Write data
    for payment in history:
        writer.writerow(
            [payment["date"], payment["description"], payment["amount"], payment["status"], payment["id"]]
        )

    csv_content = output.getvalue()

    frappe.local.response.filename = f"payment_history_{year or 'all'}.csv"
    frappe.local.response.filecontent = csv_content
    frappe.local.response.type = "csv"


@cache_with_ttl(ttl=300)  # Cache for 5 minutes - frequently accessed lookup
def get_member_from_user(user: str = None) -> str | None:
    """Get member record for logged in user or specified user"""
    if not user:
        user = frappe.session.user

    if user == "Guest":
        return None

    # First check if the passed value is already a member ID
    if frappe.db.exists("Member", user):
        return user

    # Try to find by email
    member = frappe.db.get_value("Member", {"email": user}, "name")
    if member:
        return member

    # Try to find by user link
    member = frappe.db.get_value("Member", {"user": user}, "name")
    if member:
        return member

    # Try to find by user's email (in case user email differs from member email)
    user_email = frappe.db.get_value("User", user, "email")
    if user_email:
        member = frappe.db.get_value("Member", {"email": user_email}, "name")
        if member:
            return member

    return None
