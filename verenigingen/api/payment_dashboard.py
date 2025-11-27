import traceback
from datetime import datetime
from typing import Any, Dict

import frappe
from frappe import _
from frappe.utils import add_months, flt, getdate, today

from verenigingen.utils.constants import Limits, Membership, PaymentStatus
from verenigingen.utils.error_handling import cache_with_ttl, handle_api_error, validate_required_fields
from verenigingen.utils.member_utils import get_member_name_for_user
from verenigingen.utils.migration.migration_performance import BatchProcessor
from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.performance_utils import performance_monitor

# Import security decorators
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)


def validate_member_exists(member_id: str | None) -> str:
    """Validate member exists and return member ID - development helper"""
    member = get_member_from_user(member_id)
    if not member:
        frappe.throw(_("Member not found"), frappe.DoesNotExistError)
    return member


@high_security_api(operation_type=OperationType.MEMBER_DATA)
@frappe.whitelist()
@performance_monitor()
def get_dashboard_data(member=None) -> OperationResult[Dict[str, Any]]:
    """Get payment dashboard summary data"""
    try:
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
                fields=["name"],
                limit=1,  # Usually only one active schedule per member
                order_by="creation DESC",  # Get most recent if multiple exist
            )

            if active_schedules:
                # Simply check for any overdue invoices for this customer
                # No need to filter by billing period - overdue is overdue
                invoice_filters = {
                    "customer": member_doc.customer,
                    "status": PaymentStatus.INVOICE_OVERDUE,
                    "docstatus": 1,
                }

                # Use count() for efficiency - indexed query
                failed_count = frappe.db.count("Sales Invoice", invoice_filters)
                has_failed_payments = failed_count > 0

        # Get next payment info
        # Note: get_next_payment returns dict (from security decorator to_dict()) for internal calls
        next_payment_result = get_next_payment(member)
        if isinstance(next_payment_result, dict):
            next_payment = next_payment_result.get("data") if next_payment_result.get("success") else None
        else:
            next_payment = next_payment_result.data if next_payment_result.success else None

        # Check if mandate is expiring soon
        mandate_expiring_soon = False
        active_mandates = member_doc.get_active_sepa_mandates()
        if active_mandates:
            # Get the first active mandate
            active_mandate = frappe.get_doc("SEPA Mandate", active_mandates[0].name)
            if active_mandate.expiry_date:
                days_to_expiry = (getdate(active_mandate.expiry_date) - getdate(today())).days
                mandate_expiring_soon = 0 < days_to_expiry <= 30

        data = {
            "total_paid_year": flt(total_paid_year, 2) if total_paid_year else 0.0,
            "payment_count": payment_count or 0,
            "has_failed_payments": has_failed_payments,
            "next_payment": next_payment,
            "mandate_expiring_soon": mandate_expiring_soon,
        }

        return OperationResult.ok(data, message=_("Dashboard data retrieved successfully"))

    except frappe.DoesNotExistError:
        frappe.log_error(title=_("Member Not Found"), message=traceback.format_exc())
        return OperationResult.fail(_("Member not found"))
    except Exception as e:
        frappe.log_error(title=_("Dashboard Data Error"), message=traceback.format_exc())
        return OperationResult.fail(_("Failed to retrieve dashboard data: {0}").format(str(e)))


@high_security_api(operation_type=OperationType.FINANCIAL)
@frappe.whitelist()
def get_payment_method(member=None) -> OperationResult[Dict[str, Any]]:
    """Get active payment method details"""
    try:
        # Get actual member ID
        # Modernized validation with helper
        member = validate_member_exists(member)

        member_doc = frappe.get_doc("Member", member)
        active_mandates = member_doc.get_active_sepa_mandates()

        if active_mandates:
            # Get the first active mandate details
            active_mandate = frappe.get_doc("SEPA Mandate", active_mandates[0].name)
            from verenigingen.utils.validation.iban_validator import format_iban

            data = {
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
        else:
            data = {"has_active_mandate": False}

        return OperationResult.ok(data, message=_("Payment method retrieved successfully"))

    except frappe.DoesNotExistError:
        frappe.log_error(title=_("Member Not Found"), message=traceback.format_exc())
        return OperationResult.fail(_("Member not found"))
    except Exception as e:
        frappe.log_error(title=_("Payment Method Error"), message=traceback.format_exc())
        return OperationResult.fail(_("Failed to retrieve payment method: {0}").format(str(e)))


@high_security_api(operation_type=OperationType.MEMBER_DATA)
@frappe.whitelist()
def get_payment_history(member=None, year=None, status=None, **kwargs) -> OperationResult[Dict[str, Any]]:
    """Get payment history for member"""
    try:
        # Get actual member ID
        # Modernized validation with helper
        member = validate_member_exists(member)

        member_doc = frappe.get_doc("Member", member)

        if not member_doc.customer:
            return OperationResult.ok([], message=_("No payment history available"))

        # Pagination support with constants for limits
        limit = frappe.utils.cint(kwargs.get("limit", Limits.DEFAULT_PAGE_SIZE * 5))  # 100 default
        offset = frappe.utils.cint(kwargs.get("offset", 0))
        if limit > Limits.MAX_PAGE_SIZE:
            limit = Limits.MAX_PAGE_SIZE  # Max limit for performance

        # Build filters
        filters = {"party_type": "Customer", "party": member_doc.customer, "docstatus": 1}

        if year:
            filters["posting_date"] = ["between", [f"{year}-01-01", f"{year}-12-31"]]

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
                si.custom_coverage_start_date,
                si.custom_coverage_end_date,
                si.member,
                si.membership_dues_schedule_display as dues_schedule
            FROM `tabSales Invoice` si
            WHERE {conditions}
            ORDER BY si.posting_date DESC
            LIMIT %(limit)s OFFSET %(offset)s
        """.format(
                conditions=invoice_conditions
            ),
            {**params, "limit": limit, "offset": offset},
            as_dict=True,
        )

        # Get invoice names for filtering standalone payments
        invoice_names = [inv.name for inv in invoices]

        # Get standalone payments (not linked to any invoice in our list)
        payment_filters = {"party_type": "Customer", "party": member_doc.customer, "docstatus": 1}
        if year:
            payment_filters["posting_date"] = ["between", [f"{year}-01-01", f"{year}-12-31"]]

        standalone_payments = frappe.db.sql(
            """
            SELECT
                pe.name,
                pe.posting_date as date,
                pe.paid_amount as amount,
                pe.remarks,
                pe.mode_of_payment,
                COUNT(per.name) as has_refs
            FROM `tabPayment Entry` pe
            LEFT JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
                AND per.reference_doctype = 'Sales Invoice'
                AND per.reference_name IN %(invoice_names)s
            WHERE pe.party_type = %(party_type)s
            AND pe.party = %(party)s
            AND pe.docstatus = 1
            {year_filter}
            GROUP BY pe.name
            HAVING has_refs = 0
            ORDER BY pe.posting_date DESC
            LIMIT %(limit)s
        """.format(
                year_filter="AND pe.posting_date BETWEEN %(start_date)s AND %(end_date)s" if year else ""
            ),
            {
                "party_type": "Customer",
                "party": member_doc.customer,
                "invoice_names": invoice_names or [""],
                "start_date": f"{year}-01-01" if year else None,
                "end_date": f"{year}-12-31" if year else None,
                "limit": limit,
            },
            as_dict=True,
        )

        # Format payment history
        history = []

        # Add standalone payments (not linked to invoices in our list)
        for payment in standalone_payments:
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
                inv_status = PaymentStatus.STATUS_PAID
            elif invoice.status == PaymentStatus.INVOICE_OVERDUE:
                inv_status = PaymentStatus.STATUS_FAILED
            else:
                inv_status = PaymentStatus.STATUS_PENDING

            # Build description based on coverage period
            description = "Membership Fee"

            # Use coverage dates for accurate period labeling
            if invoice.custom_coverage_start_date:
                from frappe.utils import formatdate, getdate

                coverage_start = getdate(invoice.custom_coverage_start_date)
                coverage_year = coverage_start.year

                # If there's also an end date, show period
                if invoice.custom_coverage_end_date:
                    coverage_end = getdate(invoice.custom_coverage_end_date)

                    # If same year, just show year
                    if coverage_start.year == coverage_end.year:
                        description = f"Membership Fee {coverage_year}"
                    else:
                        # Multi-year period - show month range
                        description = f"Membership Fee {formatdate(invoice.custom_coverage_start_date, 'MMM yyyy')} - {formatdate(invoice.custom_coverage_end_date, 'MMM yyyy')}"
                else:
                    # Just start date available
                    description = f"Membership Fee {coverage_year}"

            history.append(
                {
                    "id": invoice.name,
                    "date": str(invoice.date),
                    "amount": flt(invoice.amount, 2),
                    "description": description,
                    "status": inv_status,
                    "type": "invoice",
                }
            )

        # Sort by date
        history.sort(key=lambda x: x["date"], reverse=True)

        # Apply status filter if provided
        if status:
            history = [h for h in history if h["status"] == status]

        return OperationResult.ok(history, message=_("Payment history retrieved successfully"))

    except frappe.DoesNotExistError:
        frappe.log_error(title=_("Member Not Found"), message=traceback.format_exc())
        return OperationResult.fail(_("Member not found"))
    except Exception as e:
        frappe.log_error(title=_("Payment History Error"), message=traceback.format_exc())
        return OperationResult.fail(_("Failed to retrieve payment history: {0}").format(str(e)))


@high_security_api(operation_type=OperationType.FINANCIAL)
@frappe.whitelist()
def get_mandate_history(member=None) -> OperationResult[Dict[str, Any]]:
    """Get SEPA mandate history"""
    try:
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

        return OperationResult.ok(mandates, message=_("Mandate history retrieved successfully"))

    except frappe.DoesNotExistError:
        frappe.log_error(title=_("Member Not Found"), message=traceback.format_exc())
        return OperationResult.fail(_("Member not found"))
    except Exception as e:
        frappe.log_error(title=_("Mandate History Error"), message=traceback.format_exc())
        return OperationResult.fail(_("Failed to retrieve mandate history: {0}").format(str(e)))


@high_security_api(operation_type=OperationType.MEMBER_DATA)
@frappe.whitelist()
def get_payment_schedule(member=None) -> OperationResult[Dict[str, Any]]:
    """Get upcoming payment schedule"""
    try:
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
            return OperationResult.ok([], message=_("No active payment schedule found"))

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

        return OperationResult.ok(schedule, message=_("Payment schedule retrieved successfully"))

    except frappe.DoesNotExistError:
        frappe.log_error(title=_("Member Not Found"), message=traceback.format_exc())
        return OperationResult.fail(_("Member not found"))
    except Exception as e:
        frappe.log_error(title=_("Payment Schedule Error"), message=traceback.format_exc())
        return OperationResult.fail(_("Failed to retrieve payment schedule: {0}").format(str(e)))


@standard_api(operation_type=OperationType.MEMBER_DATA)
@frappe.whitelist()
def get_next_payment(member=None) -> OperationResult[Dict[str, Any]]:
    """Get next scheduled payment"""
    try:
        # Get actual member ID
        member = get_member_from_user(member)

        if not member:
            return OperationResult.ok(None, message=_("No member found for current user"))

        schedule_result = get_payment_schedule(member)

        # Handle OperationResult from get_payment_schedule
        if not schedule_result.success:
            return schedule_result

        schedule = schedule_result.data

        if schedule and len(schedule) > 0:
            next_payment_data = {
                "date": schedule[0]["date"],
                "amount": schedule[0]["amount"],
                "description": schedule[0]["description"],
            }
            return OperationResult.ok(next_payment_data, message=_("Next payment retrieved successfully"))

        return OperationResult.ok(None, message=_("No upcoming payments scheduled"))

    except Exception as e:
        frappe.log_error(title=_("Next Payment Error"), message=traceback.format_exc())
        return OperationResult.fail(_("Failed to retrieve next payment: {0}").format(str(e)))


@critical_api(operation_type=OperationType.FINANCIAL)
@frappe.whitelist()
def retry_failed_payment(invoice_id) -> OperationResult[Dict[str, Any]]:
    """Manually trigger payment retry"""
    try:
        invoice = frappe.get_doc("Sales Invoice", invoice_id)

        # Verify permissions
        member = get_member_from_user()

        # Allow administrators
        if not frappe.has_permission("Sales Invoice", "write"):
            # Check if user is the member for this invoice
            membership = frappe.db.get_value("Membership", invoice.membership, "member")
            if membership != member:
                return OperationResult.fail(_("You don't have permission to retry this payment"))

        # Check if already being retried
        existing_retry = frappe.db.exists(
            "SEPA Payment Retry", {"invoice": invoice_id, "status": ["in", ["Scheduled", "Pending"]]}
        )

        if existing_retry:
            return OperationResult.fail(_("This payment is already scheduled for retry"))

        # Schedule retry
        from verenigingen.utils.payment_retry import PaymentRetryManager

        retry_manager = PaymentRetryManager()
        result = retry_manager.schedule_retry(invoice_id, "MANUAL", "Manual retry requested by member")

        if result["scheduled"]:
            data = {"next_retry": result["next_retry"]}
            return OperationResult.ok(data, message=result["message"])
        else:
            return OperationResult.fail(result["message"])

    except frappe.DoesNotExistError:
        frappe.log_error(title=_("Invoice Not Found"), message=traceback.format_exc())
        return OperationResult.fail(_("Invoice not found"))
    except Exception as e:
        frappe.log_error(title=_("Payment Retry Error"), message=traceback.format_exc())
        return OperationResult.fail(_("Failed to retry payment: {0}").format(str(e)))


@high_security_api(operation_type=OperationType.FINANCIAL)
@frappe.whitelist()
def download_payment_receipt(payment_id) -> OperationResult[Dict[str, Any]]:
    """Generate payment receipt PDF"""
    try:
        payment = frappe.get_doc("Payment Entry", payment_id)

        # Verify permissions
        member = get_member_from_user()
        member_doc = frappe.get_doc("Member", member)

        if payment.party != member_doc.customer:
            frappe.log_error(
                title=_("Unauthorized Receipt Download"),
                message=f"User {frappe.session.user} attempted to download receipt for payment {payment_id}",
            )
            return OperationResult.fail(_("You don't have permission to download this receipt"))

        # Generate PDF (this would use a print format)
        pdf = frappe.get_print("Payment Entry", payment_id, "Payment Receipt", as_pdf=True)

        frappe.local.response.filename = f"payment_receipt_{payment_id}.pdf"
        frappe.local.response.filecontent = pdf
        frappe.local.response.type = "pdf"

        # For file downloads, we still return OperationResult but the actual file is sent via response
        return OperationResult.ok(
            {"filename": f"payment_receipt_{payment_id}.pdf"},
            message=_("Payment receipt generated successfully"),
        )

    except frappe.DoesNotExistError:
        frappe.log_error(title=_("Payment Not Found"), message=traceback.format_exc())
        return OperationResult.fail(_("Payment entry not found"))
    except Exception as e:
        frappe.log_error(title=_("Receipt Download Error"), message=traceback.format_exc())
        return OperationResult.fail(_("Failed to generate payment receipt: {0}").format(str(e)))


@high_security_api(operation_type=OperationType.MEMBER_DATA)
@frappe.whitelist()
def export_payment_history_csv(year=None) -> OperationResult[Dict[str, Any]]:
    """Export payment history as CSV"""
    try:
        member = get_member_from_user()

        if not member:
            return OperationResult.fail(_("No member found for current user"))

        history_result = get_payment_history(member, year)

        # Handle OperationResult from get_payment_history
        if not history_result.success:
            return history_result

        history = history_result.data

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

        # For file downloads, we still return OperationResult but the actual file is sent via response
        return OperationResult.ok(
            {"filename": f"payment_history_{year or 'all'}.csv"},
            message=_("Payment history CSV generated successfully"),
        )

    except Exception as e:
        frappe.log_error(title=_("CSV Export Error"), message=traceback.format_exc())
        return OperationResult.fail(_("Failed to export payment history: {0}").format(str(e)))


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
    member = get_member_name_for_user(user)
    if member:
        return member

    # Try to find by user link
    member = frappe.db.get_value("Member", {"user": user}, "name")
    if member:
        return member

    # Try to find by user's email (in case user email differs from member email)
    user_email = frappe.db.get_value("User", user, "email")
    if user_email:
        member = get_member_name_for_user(user_email)
        if member:
            return member

    return None
