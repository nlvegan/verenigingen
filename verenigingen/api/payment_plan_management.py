"""
Payment Plan Management API
Handles payment plan creation, management, and processing
"""

import traceback
from typing import Any, Dict

import frappe
from frappe import _
from frappe.utils import add_months, flt, getdate, today

# Import security framework and OperationResult
from verenigingen.utils.constants import Roles
from verenigingen.utils.member_utils import get_current_user_member_name
from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.security.api_security_framework import OperationType, self_service_api
from verenigingen.verenigingen_payments.hooks.payment_hook import PaymentHook
from verenigingen.verenigingen_payments.services.mollie_configuration_service import get_mollie_config


@frappe.whitelist()
@self_service_api(operation_type=OperationType.FINANCIAL, implicit_allowed=True)
def request_payment_plan(
    member: str | None,
    total_amount: float,
    preferred_installments: int | None = None,
    preferred_frequency: str | None = None,
    reason: str | None = None,
) -> OperationResult[Dict[str, Any]]:
    """
    Submit a payment plan request from member portal
    """
    try:
        # The member portal (payment_plans.html) submits member=null and expects
        # the member to be resolved from the session, mirroring get_member_payment_plans.
        if not member:
            member = get_current_user_member_name()
            if not member:
                return OperationResult.fail(message=_("No member record found for current user"))

        # Validate member access
        if frappe.session.user != "Administrator":
            member_email = frappe.db.get_value("Member", member, "email")
            if member_email != frappe.session.user:
                frappe.throw(_("Access denied"))

        # Validate amount
        total_amount = flt(total_amount)
        if total_amount <= 0:
            frappe.throw(_("Total amount must be greater than 0"))

        # Set defaults
        installments = int(preferred_installments) if preferred_installments else 3
        frequency = preferred_frequency or "Monthly"

        # Validate installments
        if installments < 2 or installments > 12:
            frappe.throw(_("Number of installments must be between 2 and 12"))

        # Create payment plan
        payment_plan = frappe.new_doc("Payment Plan")
        payment_plan.member = member
        payment_plan.plan_type = "Equal Installments"
        payment_plan.total_amount = total_amount
        payment_plan.number_of_installments = installments
        payment_plan.frequency = frequency
        payment_plan.start_date = today()
        payment_plan.status = "Draft"  # Will be submitted after approval
        payment_plan.approval_required = 1
        payment_plan.reason = reason or "Member requested payment plan via portal"

        # Set payment method from member's active SEPA mandate
        sepa_mandate = get_member_active_sepa_mandate(member)
        if sepa_mandate:
            payment_plan.payment_method = "SEPA Direct Debit"
            payment_plan.payment_account = sepa_mandate
        else:
            payment_plan.payment_method = "Bank Transfer"

        payment_plan.save()

        # Send notification to administrators
        send_payment_plan_request_notification(payment_plan)

        data = {
            "payment_plan_id": payment_plan.name,
            "installment_amount": payment_plan.installment_amount,
            "start_date": payment_plan.start_date,
            "end_date": payment_plan.end_date,
        }

        return OperationResult.ok(
            data,
            message=_("Payment plan request submitted successfully. You will be notified once reviewed."),
        )

    except Exception as e:
        frappe.log_error(
            title=_("Error requesting payment plan"), message=f"{str(e)}\n\n{traceback.format_exc()}"
        )
        return OperationResult.from_exception(e, message=_("Failed to request payment plan"))


@frappe.whitelist()
@self_service_api(operation_type=OperationType.FINANCIAL, implicit_allowed=True)
def get_member_payment_plans(member: str | None = None) -> OperationResult[Dict[str, Any]]:
    """
    Get payment plans for a member
    """
    try:
        # Determine member
        if not member:
            # Get member from current user (uses user field, with email fallback)
            member = get_current_user_member_name()
            if not member:
                return OperationResult.fail(message=_("No member record found for current user"))

        # Validate access
        if frappe.session.user != "Administrator":
            member_email = frappe.db.get_value("Member", member, "email")
            if member_email != frappe.session.user:
                frappe.throw(_("Access denied"))

        # Get payment plans
        payment_plans = frappe.get_all(
            "Payment Plan",
            filters={"member": member},
            fields=[
                "name",
                "plan_type",
                "total_amount",
                "installment_amount",
                "number_of_installments",
                "frequency",
                "start_date",
                "end_date",
                "status",
                "total_paid",
                "remaining_balance",
                "next_payment_date",
                "consecutive_missed_payments",
            ],
            order_by="creation desc",
        )

        # Get installment details for each plan
        for plan in payment_plans:
            installments = frappe.get_all(
                "Payment Plan Installment",
                filters={"parent": plan.name},
                fields=[
                    "installment_number",
                    "due_date",
                    "amount",
                    "status",
                    "payment_date",
                    "payment_reference",
                    "notes",
                ],
                order_by="installment_number",
            )
            plan["installments"] = installments

        return OperationResult.ok(
            {"payment_plans": payment_plans}, message=_("Payment plans retrieved successfully")
        )

    except Exception as e:
        frappe.log_error(
            title=_("Error getting member payment plans"), message=f"{str(e)}\n\n{traceback.format_exc()}"
        )
        return OperationResult.from_exception(e, message=_("Failed to retrieve payment plans"))


# Helper Functions


def get_member_active_sepa_mandate(member):
    """Get member's active SEPA mandate"""
    try:
        mandate = frappe.db.get_value(
            "SEPA Mandate", {"member": member, "status": "Active"}, "name", order_by="creation desc"
        )
        return mandate
    except:
        return None


def send_payment_plan_request_notification(payment_plan):
    """Send notification to admins about new payment plan request"""
    try:
        member = frappe.get_doc("Member", payment_plan.member)

        # Get admin users
        admin_users = frappe.get_all(
            "Has Role",
            filters={"role": ["in", list(Roles.ADMIN_PAIR)]},
            fields=["parent"],
            pluck="parent",
        )

        admin_emails = frappe.get_all(
            "User", filters={"name": ["in", admin_users], "enabled": 1}, fields=["email"], pluck="email"
        )

        if not admin_emails:
            return

        # MIGRATED: Use unified EmailService with payment notification template
        from verenigingen.services.communication.email_service import get_email_service

        email_service = get_email_service()

        context = {
            "member_name": "System Administrator",
            "notification_message": f"A new payment plan request has been submitted by {member.full_name} ({member.email}).",
            "payment_reference": payment_plan.name,
            "amount": f"€{payment_plan.total_amount:.2f}",
            "payment_date": str(frappe.utils.today()),
            "payment_method": f"Payment Plan - {payment_plan.frequency}",
            "action_required": f"Total Amount: €{payment_plan.total_amount:.2f}. Installments: {payment_plan.number_of_installments} x €{payment_plan.installment_amount:.2f}. Reason: {payment_plan.reason}",
            "next_steps": "Please review and approve/reject this request in the system.",
            "company": get_mollie_config().get_default_company(),
        }

        email_service.send_templated_email(
            template_name="payment_notification",
            recipients=admin_emails,
            context=context,
            subject_override=f"Payment Plan Request - {member.full_name}",
            reference_doctype="Payment Plan",
            reference_name=payment_plan.name,
            notification_key="payment_plan_request",
        )

    except Exception as e:
        frappe.log_error(f"Error sending payment plan request notification: {str(e)}")


@frappe.whitelist()
@self_service_api(operation_type=OperationType.FINANCIAL, implicit_allowed=True)
def calculate_payment_plan_preview(total_amount, installments, frequency) -> OperationResult[Dict[str, Any]]:
    """
    Calculate payment plan preview for display
    """
    try:
        total_amount = flt(total_amount)
        installments = int(installments)

        if total_amount <= 0 or installments <= 0:
            return OperationResult.fail(message=_("Invalid amount or installments"))

        installment_amount = flt(total_amount / installments, 2)

        # Calculate dates
        from frappe.utils import add_days

        start_date = getdate(today())

        if frequency == "Weekly":
            end_date = add_days(start_date, (installments - 1) * 7)
        elif frequency == "Bi-weekly":
            end_date = add_days(start_date, (installments - 1) * 14)
        elif frequency == "Monthly":
            end_date = add_months(start_date, installments - 1)
        else:
            end_date = add_days(start_date, installments * 30)  # Default

        data = {
            "preview": {
                "total_amount": total_amount,
                "installment_amount": installment_amount,
                "number_of_installments": installments,
                "frequency": frequency,
                "start_date": start_date,
                "end_date": end_date,
            },
        }

        return OperationResult.ok(data, message=_("Payment plan preview calculated successfully"))

    except Exception as e:
        frappe.log_error(
            title=_("Error calculating payment plan preview"), message=f"{str(e)}\n\n{traceback.format_exc()}"
        )
        return OperationResult.from_exception(e, message=_("Failed to calculate payment plan preview"))


PAYABLE_INSTALLMENT_STATUSES = ("Pending", "Overdue")


def get_next_payable_installment(plan_doc):
    """Return the earliest Pending/Overdue installment (dict) or None."""
    payable = [i for i in plan_doc.installments if i.status in PAYABLE_INSTALLMENT_STATUSES]
    if not payable:
        return None
    nxt = min(payable, key=lambda i: (i.due_date or plan_doc.start_date, i.installment_number))
    return {
        "installment_number": nxt.installment_number,
        "amount": nxt.amount,
        "status": nxt.status,
        "due_date": nxt.due_date,
    }


@frappe.whitelist()
@self_service_api(operation_type=OperationType.FINANCIAL, implicit_allowed=True)
def initiate_installment_payment(plan, installment_number, method="mollie") -> OperationResult:
    """Start an online payment for one payment-plan installment.

    Validates the plan belongs to the current member and the installment is
    payable (Pending/Overdue), creates a Payment Plan Payment intent for the
    server-derived installment amount, and initiates the gateway payment,
    returning the redirect URL. Never marks anything Paid — that happens only on
    the confirmed webhook.
    """
    try:
        installment_number = int(installment_number)
        plan_doc = frappe.get_doc("Payment Plan", plan)

        # Ownership: the plan's member must map to the current user.
        member_name = get_current_user_member_name()
        if not member_name or plan_doc.member != member_name:
            return OperationResult.fail(message=_("You can only pay your own payment plans"))

        if plan_doc.status != "Active":
            return OperationResult.fail(message=_("This payment plan is not active"))

        installment = next(
            (i for i in plan_doc.installments if i.installment_number == installment_number), None
        )
        if not installment:
            return OperationResult.fail(message=_("Installment not found"))
        if installment.status not in PAYABLE_INSTALLMENT_STATUSES:
            return OperationResult.fail(message=_("This installment is not payable"))

        # Amount is server-derived from the stored installment.
        amount = flt(installment.amount)

        intent = frappe.get_doc(
            {
                "doctype": "Payment Plan Payment",
                "payment_plan": plan_doc.name,
                "installment_number": installment_number,
                "amount": amount,
                "currency": "EUR",
                "member": member_name,
                "gateway": "Mollie",
                "status": "Pending",
            }
        )
        # Security: intent is scoped to the caller's own plan (ownership checked
        # above); created on their behalf so the gateway has a reference doc.
        intent.insert(ignore_permissions=True)

        member_doc = frappe.get_doc("Member", member_name)
        result = PaymentHook.initiate_payment(
            method=method,
            amount=amount,
            reference_doctype="Payment Plan Payment",
            reference_name=intent.name,
            payer_info={"email": member_doc.email, "name": member_doc.full_name},
            description=_("Payment plan {0} installment {1}").format(plan_doc.name, installment_number),
        )

        if not result.get("success"):
            intent.db_set("status", "Failed")
            return OperationResult.fail(message=result.get("message") or _("Payment could not be started"))

        # PaymentHook.initiate_payment nests the checkout URL at data["url"]
        # (see _normalize_gateway_response redirect branch); there is no
        # top-level "redirect_url" key.
        redirect_url = (result.get("data") or {}).get("url")
        return OperationResult.ok(
            {"redirect_url": redirect_url, "intent": intent.name},
            message=_("Payment started"),
        )

    except Exception as e:
        frappe.log_error(
            f"initiate_installment_payment failed for {plan}/{installment_number}: {e}",
            "Payment Plan Payment",
        )
        return OperationResult.from_exception(e, message=_("Failed to start payment"))
