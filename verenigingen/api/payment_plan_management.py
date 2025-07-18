"""
Payment Plan Management API
Handles payment plan creation, management, and processing
"""

import json

import frappe
from frappe import _
from frappe.utils import add_months, flt, getdate, today


@frappe.whitelist()
def request_payment_plan(
    member, total_amount, preferred_installments=None, preferred_frequency=None, reason=None
):
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
        payment_plan.status = "Pending Approval"
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

        return {
            "success": True,
            "payment_plan_id": payment_plan.name,
            "message": _("Payment plan request submitted successfully. You will be notified once reviewed."),
            "installment_amount": payment_plan.installment_amount,
            "start_date": payment_plan.start_date,
            "end_date": payment_plan.end_date,
        }

    except Exception as e:
        frappe.log_error(f"Error requesting payment plan: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def get_member_payment_plans(member=None):
    """
    Get payment plans for a member
    """
    try:
        # Determine member
        if not member:
            # Get member from current user
            member = frappe.db.get_value("Member", {"email": frappe.session.user}, "name")
            if not member:
                return {"success": False, "error": "No member record found for current user"}

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

        return {"success": True, "payment_plans": payment_plans}

    except Exception as e:
        frappe.log_error(f"Error getting member payment plans: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def make_payment_plan_payment(payment_plan_id, installment_number, payment_amount, payment_reference=None):
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

        return {
            "success": True,
            "message": _("Payment recorded successfully"),
            "remaining_balance": payment_plan.remaining_balance,
            "next_payment_date": payment_plan.next_payment_date,
        }

    except Exception as e:
        frappe.log_error(f"Error recording payment plan payment: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def get_payment_plan_summary(payment_plan_id):
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

        return {
            "success": True,
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

    except Exception as e:
        frappe.log_error(f"Error getting payment plan summary: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def approve_payment_plan_request(payment_plan_id, approval_notes=None):
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
        payment_plan.status = "Active"

        if approval_notes:
            payment_plan.add_comment(text=f"Approved: {approval_notes}")

        payment_plan.save()
        payment_plan.submit()

        # Send approval notification to member
        send_payment_plan_approval_notification(payment_plan, approved=True)

        return {"success": True, "message": _("Payment plan approved successfully")}

    except Exception as e:
        frappe.log_error(f"Error approving payment plan: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def reject_payment_plan_request(payment_plan_id, rejection_reason=None):
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

        return {"success": True, "message": _("Payment plan rejected")}

    except Exception as e:
        frappe.log_error(f"Error rejecting payment plan: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def get_pending_payment_plan_requests():
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

        return {"success": True, "pending_requests": pending_plans}

    except Exception as e:
        frappe.log_error(f"Error getting pending payment plan requests: {str(e)}")
        return {"success": False, "error": str(e)}


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

        subject = f"Payment Plan Request - {member.full_name}"
        message = f"""
        A new payment plan request has been submitted:

        Member: {member.full_name} ({member.email})
        Total Amount: €{payment_plan.total_amount:.2f}
        Installments: {payment_plan.number_of_installments} x €{payment_plan.installment_amount:.2f}
        Frequency: {payment_plan.frequency}
        Reason: {payment_plan.reason}

        Please review and approve/reject this request in the system.
        """

        frappe.sendmail(
            recipients=admin_emails,
            subject=subject,
            message=message,
            reference_doctype="Payment Plan",
            reference_name=payment_plan.name,
        )

    except Exception as e:
        frappe.log_error(f"Error sending payment plan request notification: {str(e)}")


def send_payment_plan_approval_notification(payment_plan, approved=True, reason=None):
    """Send approval/rejection notification to member"""
    try:
        member = frappe.get_doc("Member", payment_plan.member)

        if approved:
            subject = f"Payment Plan Approved - {payment_plan.name}"
            message = f"""
            Dear {member.full_name},

            Your payment plan request has been approved!

            Payment Plan: {payment_plan.name}
            Total Amount: €{payment_plan.total_amount:.2f}
            Installments: {payment_plan.number_of_installments} x €{payment_plan.installment_amount:.2f}
            Frequency: {payment_plan.frequency}
            Start Date: {payment_plan.start_date}

            Your first payment is due on {payment_plan.next_payment_date}.

            Thank you for choosing a payment plan option.
            """
        else:
            subject = f"Payment Plan Request - {payment_plan.name}"
            message = f"""
            Dear {member.full_name},

            Unfortunately, your payment plan request could not be approved at this time.

            """
            if reason:
                message += f"Reason: {reason}\n\n"

            message += """
            Please contact us if you would like to discuss other payment options.

            Best regards,
            The Membership Team
            """

        frappe.sendmail(
            recipients=[member.email],
            subject=subject,
            message=message,
            reference_doctype="Payment Plan",
            reference_name=payment_plan.name,
        )

    except Exception as e:
        frappe.log_error(f"Error sending payment plan approval notification: {str(e)}")


@frappe.whitelist()
def calculate_payment_plan_preview(total_amount, installments, frequency):
    """
    Calculate payment plan preview for display
    """
    try:
        total_amount = flt(total_amount)
        installments = int(installments)

        if total_amount <= 0 or installments <= 0:
            return {"success": False, "error": "Invalid amount or installments"}

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

        return {
            "success": True,
            "preview": {
                "total_amount": total_amount,
                "installment_amount": installment_amount,
                "number_of_installments": installments,
                "frequency": frequency,
                "start_date": start_date,
                "end_date": end_date,
            },
        }

    except Exception as e:
        frappe.log_error(f"Error calculating payment plan preview: {str(e)}")
        return {"success": False, "error": str(e)}
