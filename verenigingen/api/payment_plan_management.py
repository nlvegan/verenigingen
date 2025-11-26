"""
Payment Plan Management API
Handles payment plan creation, management, and processing
"""

import json
import traceback
from typing import Any, Dict

import frappe
from frappe import _
from frappe.utils import add_months, flt, getdate, today

# Import security framework and OperationResult
from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.security.api_security_framework import OperationType, critical_api, standard_api
from verenigingen.verenigingen_payments.services.mollie_configuration_service import get_mollie_config


@critical_api(operation_type=OperationType.FINANCIAL)
@frappe.whitelist()
def request_payment_plan(
    member, total_amount, preferred_installments=None, preferred_frequency=None, reason=None
) -> OperationResult[Dict[str, Any]]:
    """
    Submit a payment plan request from member portal
    """
    try:
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
        return OperationResult.fail(message=_("Failed to request payment plan"), error=str(e))


@standard_api(operation_type=OperationType.READ)
@frappe.whitelist()
def get_member_payment_plans(member=None) -> OperationResult[Dict[str, Any]]:
    """
    Get payment plans for a member
    """
    try:
        # Determine member
        if not member:
            # Get member from current user
            member = frappe.db.get_value("Member", {"email": frappe.session.user}, "name")
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
        return OperationResult.fail(message=_("Failed to retrieve payment plans"), error=str(e))


@critical_api(operation_type=OperationType.FINANCIAL)
@frappe.whitelist()
def make_payment_plan_payment(
    payment_plan_id, installment_number, payment_amount, payment_reference=None
) -> OperationResult[Dict[str, Any]]:
    """
    Record a payment for a payment plan installment
    """
    try:
        # Get payment plan
        payment_plan = frappe.get_doc("Payment Plan", payment_plan_id)

        # Validate access
        if frappe.session.user != "Administrator":
            member_email = frappe.db.get_value("Member", payment_plan.member, "email")
            if member_email != frappe.session.user:
                frappe.throw(_("Access denied"))

        # Process payment
        payment_plan.process_payment(
            installment_number=int(installment_number),
            payment_amount=flt(payment_amount),
            payment_reference=payment_reference,
            payment_date=today(),
        )

        data = {
            "remaining_balance": payment_plan.remaining_balance,
            "next_payment_date": payment_plan.next_payment_date,
        }

        return OperationResult.ok(data, message=_("Payment recorded successfully"))

    except Exception as e:
        frappe.log_error(
            title=_("Error recording payment plan payment"), message=f"{str(e)}\n\n{traceback.format_exc()}"
        )
        return OperationResult.fail(message=_("Failed to record payment"), error=str(e))


@standard_api(operation_type=OperationType.READ)
@frappe.whitelist()
def get_payment_plan_summary(payment_plan_id) -> OperationResult[Dict[str, Any]]:
    """
    Get detailed summary of a payment plan
    """
    try:
        payment_plan = frappe.get_doc("Payment Plan", payment_plan_id)

        # Validate access
        if frappe.session.user != "Administrator":
            member_email = frappe.db.get_value("Member", payment_plan.member, "email")
            if member_email != frappe.session.user:
                frappe.throw(_("Access denied"))

        # Get member details
        member = frappe.get_doc("Member", payment_plan.member)

        # Calculate progress
        progress_percentage = 0
        if payment_plan.total_amount > 0:
            progress_percentage = (payment_plan.total_paid / payment_plan.total_amount) * 100

        # Get payment history
        paid_installments = [inst for inst in payment_plan.installments if inst.status == "Paid"]

        data = {
            "payment_plan": {
                "name": payment_plan.name,
                "member_name": member.full_name,
                "total_amount": payment_plan.total_amount,
                "total_paid": payment_plan.total_paid,
                "remaining_balance": payment_plan.remaining_balance,
                "progress_percentage": progress_percentage,
                "status": payment_plan.status,
                "start_date": payment_plan.start_date,
                "end_date": payment_plan.end_date,
                "next_payment_date": payment_plan.next_payment_date,
                "installment_amount": payment_plan.installment_amount,
                "frequency": payment_plan.frequency,
                "consecutive_missed_payments": payment_plan.consecutive_missed_payments,
                "installments": payment_plan.installments,
                "payment_history": paid_installments,
            },
        }

        return OperationResult.ok(data, message=_("Payment plan summary retrieved successfully"))

    except Exception as e:
        frappe.log_error(
            title=_("Error getting payment plan summary"), message=f"{str(e)}\n\n{traceback.format_exc()}"
        )
        return OperationResult.fail(message=_("Failed to retrieve payment plan summary"), error=str(e))


@critical_api(operation_type=OperationType.WRITE)
@frappe.whitelist()
def approve_payment_plan_request(payment_plan_id, approval_notes=None) -> OperationResult[Dict[str, Any]]:
    """
    Approve a payment plan request (admin only)
    """
    try:
        # Check admin permissions
        if not frappe.has_permission("Payment Plan", "write"):
            frappe.throw(_("Access denied"))

        payment_plan = frappe.get_doc("Payment Plan", payment_plan_id)

        if payment_plan.status != "Pending Approval":
            frappe.throw(_("Payment plan is not pending approval"))

        # Approve the plan
        payment_plan.approved_by = frappe.session.user
        payment_plan.approval_date = frappe.utils.now()
        payment_plan.status = "Submitted"  # Approved plans are submitted

        if approval_notes:
            payment_plan.add_comment(text=f"Approved: {approval_notes}")

        payment_plan.save()
        payment_plan.submit()

        # Send approval notification to member
        send_payment_plan_approval_notification(payment_plan, approved=True)

        return OperationResult.ok({}, message=_("Payment plan approved successfully"))

    except Exception as e:
        frappe.log_error(
            title=_("Error approving payment plan"), message=f"{str(e)}\n\n{traceback.format_exc()}"
        )
        return OperationResult.fail(message=_("Failed to approve payment plan"), error=str(e))


@critical_api(operation_type=OperationType.WRITE)
@frappe.whitelist()
def reject_payment_plan_request(payment_plan_id, rejection_reason=None) -> OperationResult[Dict[str, Any]]:
    """
    Reject a payment plan request (admin only)
    """
    try:
        # Check admin permissions
        if not frappe.has_permission("Payment Plan", "write"):
            frappe.throw(_("Access denied"))

        payment_plan = frappe.get_doc("Payment Plan", payment_plan_id)

        if payment_plan.status != "Pending Approval":
            frappe.throw(_("Payment plan is not pending approval"))

        # Reject the plan
        payment_plan.status = "Cancelled"

        if rejection_reason:
            payment_plan.add_comment(text=f"Rejected: {rejection_reason}")

        payment_plan.save()

        # Send rejection notification to member
        send_payment_plan_approval_notification(payment_plan, approved=False, reason=rejection_reason)

        return OperationResult.ok({}, message=_("Payment plan rejected"))

    except Exception as e:
        frappe.log_error(
            title=_("Error rejecting payment plan"), message=f"{str(e)}\n\n{traceback.format_exc()}"
        )
        return OperationResult.fail(message=_("Failed to reject payment plan"), error=str(e))


@standard_api(operation_type=OperationType.READ)
@frappe.whitelist()
def get_pending_payment_plan_requests() -> OperationResult[Dict[str, Any]]:
    """
    Get all pending payment plan requests (admin only)
    """
    try:
        # Check admin permissions
        if not frappe.has_permission("Payment Plan", "read"):
            frappe.throw(_("Access denied"))

        pending_plans = frappe.get_all(
            "Payment Plan",
            filters={"status": "Pending Approval"},
            fields=[
                "name",
                "member",
                "total_amount",
                "number_of_installments",
                "frequency",
                "start_date",
                "reason",
                "creation",
            ],
            order_by="creation",
        )

        # Get member names
        for plan in pending_plans:
            member = frappe.get_doc("Member", plan.member)
            plan["member_name"] = member.full_name
            plan["member_email"] = member.email

        return OperationResult.ok(
            {"pending_requests": pending_plans},
            message=_("Pending payment plan requests retrieved successfully"),
        )

    except Exception as e:
        frappe.log_error(
            title=_("Error getting pending payment plan requests"),
            message=f"{str(e)}\n\n{traceback.format_exc()}",
        )
        return OperationResult.fail(
            message=_("Failed to retrieve pending payment plan requests"), error=str(e)
        )


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
            filters={"role": ["in", ["System Manager", "Verenigingen Administrator"]]},
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
        )

    except Exception as e:
        frappe.log_error(f"Error sending payment plan request notification: {str(e)}")


def send_payment_plan_approval_notification(payment_plan, approved=True, reason=None):
    """Send approval/rejection notification to member"""
    try:
        member = frappe.get_doc("Member", payment_plan.member)

        # MIGRATED: Use unified EmailService with payment notification template
        from verenigingen.services.communication.email_service import get_email_service

        email_service = get_email_service()

        if approved:
            context = {
                "member_name": member.full_name,
                "notification_message": "Your payment plan request has been approved!",
                "payment_reference": payment_plan.name,
                "amount": f"€{payment_plan.total_amount:.2f}",
                "payment_date": str(payment_plan.start_date),
                "payment_method": f"Payment Plan - {payment_plan.frequency}",
                "next_steps": f"Installments: {payment_plan.number_of_installments} x €{payment_plan.installment_amount:.2f}. Your first payment is due on {payment_plan.next_payment_date}. Thank you for choosing a payment plan option.",
                "company": get_mollie_config().get_default_company(),
            }
            subject = f"Payment Plan Approved - {payment_plan.name}"
        else:
            context = {
                "member_name": member.full_name,
                "notification_message": "Unfortunately, your payment plan request could not be approved at this time.",
                "payment_reference": payment_plan.name,
                "amount": f"€{payment_plan.total_amount:.2f}",
                "payment_date": str(frappe.utils.today()),
                "payment_method": f"Payment Plan - {payment_plan.frequency}",
                "action_required": f"Reason: {reason}" if reason else "Request not approved",
                "next_steps": "Please contact us if you would like to discuss other payment options.",
                "company": get_mollie_config().get_default_company(),
            }
            subject = f"Payment Plan Request - {payment_plan.name}"

        email_service.send_templated_email(
            template_name="payment_notification",
            recipients=[member.email],
            context=context,
            subject_override=subject,
            reference_doctype="Payment Plan",
            reference_name=payment_plan.name,
        )

    except Exception as e:
        frappe.log_error(f"Error sending payment plan approval notification: {str(e)}")


@standard_api(operation_type=OperationType.READ)
@frappe.whitelist()
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
        return OperationResult.fail(message=_("Failed to calculate payment plan preview"), error=str(e))
