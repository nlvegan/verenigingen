from datetime import datetime

import frappe
from frappe import _
from frappe.utils import add_months, flt, getdate, today


@frappe.whitelist()
def get_dashboard_data(member=None):
    """Get payment dashboard summary data"""
    # Get actual member ID
    member = get_member_from_user(member)

    if not member:
        frappe.throw(_("Member not found"))

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

    # Check for failed payments
    has_failed_payments = False
    if member_doc.customer:
        # Get failed invoices through subscription relationship
        failed_invoices = frappe.db.sql(
            """
            SELECT COUNT(DISTINCT si.name)
            FROM `tabSales Invoice` si
            INNER JOIN `tabSubscription Invoice` sub_inv ON sub_inv.invoice = si.name
            INNER JOIN `tabSubscription` sub ON sub.name = sub_inv.parent
            INNER JOIN `tabMembership` m ON m.subscription = sub.name
            WHERE m.member = %s
            AND si.status = 'Overdue'
            AND si.docstatus = 1
        """,
            member,
        )[0][0]
        has_failed_payments = failed_invoices > 0

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
    member = get_member_from_user(member)

    if not member:
        frappe.throw(_("Member not found"))

    member_doc = frappe.get_doc("Member", member)
    active_mandate = member_doc.get_active_sepa_mandate()

    if active_mandate:
        from verenigingen.utils.iban_validator import format_iban

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


@frappe.whitelist()
def get_payment_history(member=None, year=None, status=None):
    """Get payment history for member"""
    # Get actual member ID
    member = get_member_from_user(member)

    if not member:
        frappe.throw(_("Member not found"))

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
    )

    # Get sales invoices with membership info through subscription
    invoice_conditions = "si.customer = %(customer)s AND si.docstatus = 1"
    params = {"customer": member_doc.customer}

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
            m.name as membership
        FROM `tabSales Invoice` si
        LEFT JOIN `tabSubscription Invoice` sub_inv ON sub_inv.invoice = si.name
        LEFT JOIN `tabSubscription` sub ON sub.name = sub_inv.parent
        LEFT JOIN `tabMembership` m ON m.subscription = sub.name
        WHERE {conditions}
        ORDER BY si.posting_date DESC
    """.format(
            conditions=invoice_conditions
        ),
        params,
        as_dict=True,
    )

    # Format payment history
    history = []

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
        if invoice.status in ["Paid", "Credit Note Issued"]:
            status = "Paid"
        elif invoice.status == "Overdue":
            status = "Failed"
        else:
            status = "Pending"

        description = "Membership Fee"
        if invoice.membership:
            membership_year = frappe.db.get_value("Membership", invoice.membership, "membership_year")
            if membership_year:
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
    member = get_member_from_user(member)

    if not member:
        frappe.throw(_("Member not found"))

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
    from verenigingen.utils.iban_validator import format_iban, get_bank_from_iban

    for mandate in mandates:
        mandate["iban_formatted"] = format_iban(mandate.iban)
        bank_info = get_bank_from_iban(mandate.iban)
        mandate["bank_name"] = bank_info["bank_name"] if bank_info else "Unknown Bank"
        mandate["is_active"] = mandate.status == "Active"

    return mandates


@frappe.whitelist()
def get_payment_schedule(member=None):
    """Get upcoming payment schedule"""
    # Get actual member ID
    member = get_member_from_user(member)

    if not member:
        frappe.throw(_("Member not found"))

    # Get active membership
    active_membership = frappe.get_all(
        "Membership",
        filters={"member": member, "status": ["in", ["Active", "Current"]]},
        fields=["name", "membership_type", "subscription", "membership_fee"],
        limit=1,
    )

    if not active_membership:
        return []

    membership = active_membership[0]
    schedule = []

    # Generate next 12 months of payments
    if membership.subscription:
        subscription = frappe.get_doc("Subscription", membership.subscription)

        # Get payment frequency from subscription plan or period settings
        # Check if subscription has a plan
        if hasattr(subscription, "plans") and subscription.plans:
            # Get interval from first plan
            plan = subscription.plans[0]
            if plan.plan:
                plan_doc = frappe.get_doc("Subscription Plan", plan.plan)
                # Subscription plans typically have billing_interval field
                if hasattr(plan_doc, "billing_interval"):
                    if plan_doc.billing_interval == "Month":
                        months = 1
                    elif plan_doc.billing_interval == "Quarter":
                        months = 3
                    elif plan_doc.billing_interval == "Year":
                        months = 12
                    else:
                        months = 1
                else:
                    # Default to monthly if no interval found
                    months = 1
            else:
                months = 1
        else:
            # Default to monthly
            months = 1

        current_date = getdate(today())
        for i in range(0, 12, months):
            payment_date = add_months(current_date, i)

            # Skip if payment date is in the past
            if payment_date < getdate(today()):
                continue

            schedule.append(
                {
                    "date": str(payment_date),
                    "amount": flt(membership.membership_fee, 2),
                    "description": f'{membership.membership_type} - {"Monthly" if months == 1 else "Quarterly" if months == 3 else "Yearly"} Payment',
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


def get_member_from_user(user=None):
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
