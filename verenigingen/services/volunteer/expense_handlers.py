"""
Expense Claim Event Handlers

Handles Expense Claim document events like submission to update
Member financial history with proper permissions and error handling.
Also handles expense approval notifications via Verenigingen Email Configuration.
"""

import frappe
from frappe import _


def update_member_expense_history(doc, method=None):
    """
    Event handler for Expense Claim on_submit to update Member financial history.

    Uses exponential backoff and runs with system permissions via event hooks.
    This replaces the direct call during form submission to fix permission issues.

    Args:
        doc: Expense Claim document
        method: Event method name (on_submit)
    """
    try:
        # Only process expense claims that have employee linked to volunteer/member
        if not doc.employee:
            frappe.logger().debug(f"Skipping expense history update for {doc.name} - no employee linked")
            return

        # Find volunteer record by employee
        volunteer_name = frappe.db.get_value("Volunteer", {"employee_id": doc.employee}, "name")
        if not volunteer_name:
            frappe.logger().debug(
                f"Skipping expense history update for {doc.name} - employee {doc.employee} not linked to volunteer"
            )
            return

        # Find member record from volunteer
        member_name = frappe.db.get_value("Volunteer", volunteer_name, "member")
        if not member_name:
            frappe.logger().debug(
                f"Skipping expense history update for {doc.name} - volunteer {volunteer_name} not linked to member"
            )
            return

        # Defer the batch-processor drain to a worker job so it runs outside
        # the submit transaction (see design/financial-history-hook-transaction-safety).
        frappe.enqueue(
            "verenigingen.services.volunteer.expense_handlers.drain_member_expense_history",
            queue="short",
            job_id=f"fin_history_expense_{member_name}_{doc.name}_add",
            deduplicate=True,
            enqueue_after_commit=True,
            timeout=300,
            member=member_name,
            expense=doc.name,
            operation="add",
        )

        frappe.logger().info(
            f"Queued expense history update for member {member_name} from expense claim {doc.name}"
        )

    except Exception as e:
        # Log error but don't fail the expense claim submission
        # The scheduled job will retry the financial history update
        frappe.log_error(
            f"Failed to queue expense history update for {doc.name}: {str(e)}", "Expense History Queue Error"
        )
        frappe.logger().warning(
            f"Expense history update failed for {doc.name}: {str(e)}, will be retried by scheduled job"
        )


def drain_member_expense_history(member, expense, operation):
    """Worker job: queue an expense add/remove for `member` and drain."""
    from verenigingen.utils.financial_history_batch_processor import (
        FinancialHistoryBatchProcessor,
        queue_expense_removal,
        queue_expense_update,
    )

    if operation == "remove":
        queue_expense_removal(member, expense)
    else:
        queue_expense_update(member, expense)
    FinancialHistoryBatchProcessor.force_process_all()


def on_expense_claim_cancel(doc, method=None):
    """
    Event handler for Expense Claim on_cancel to remove from Member financial history.

    Args:
        doc: Expense Claim document
        method: Event method name (on_cancel)
    """
    try:
        # Find volunteer and member like above
        if not doc.employee:
            return

        volunteer_name = frappe.db.get_value("Volunteer", {"employee_id": doc.employee}, "name")
        if not volunteer_name:
            return

        member_name = frappe.db.get_value("Volunteer", volunteer_name, "member")
        if not member_name:
            return

        # Defer the batch-processor drain to a worker job so it runs outside
        # the cancel transaction (see design/financial-history-hook-transaction-safety).
        # Same job_id shape as the add-path enqueue; deduplicate collapses any
        # duplicate enqueue from delayed_expense_hooks.schedule_member_expense_history_removal.
        frappe.enqueue(
            "verenigingen.services.volunteer.expense_handlers.drain_member_expense_history",
            queue="short",
            job_id=f"fin_history_expense_{member_name}_{doc.name}_remove",
            deduplicate=True,
            enqueue_after_commit=True,
            timeout=300,
            member=member_name,
            expense=doc.name,
            operation="remove",
        )

        frappe.logger().info(
            f"Queued expense history removal for member {member_name} from cancelled expense claim {doc.name}"
        )

    except Exception as e:
        # Log error but don't fail the cancellation
        frappe.log_error(
            f"Failed to queue expense history removal for {doc.name}: {str(e)}",
            "Expense History Removal Error",
        )


def notify_expense_approvers(doc, method=None):
    """
    Send notification to expense approvers when an expense claim is submitted.

    Uses EmailService with notification_key to respect Verenigingen Email Configuration settings.
    This replaces the Frappe Notification "Expense Submitted for Approval" which
    bypassed Verenigingen Email Configuration.

    Args:
        doc: Expense Claim document
        method: Event method name (on_submit)
    """
    try:
        if not doc.employee:
            frappe.logger().debug(f"Skipping expense notification for {doc.name} - no employee linked")
            return

        # Get expense approver from employee record
        employee = frappe.get_doc("Employee", doc.employee)
        approver_email = None

        if employee.expense_approver:
            # expense_approver field stores the User ID
            approver_email = frappe.db.get_value("User", employee.expense_approver, "email")

        if not approver_email:
            # Fallback: try department approvers
            if employee.department:
                dept_approvers = frappe.get_all(
                    "Department Approver",
                    filters={"parent": employee.department, "parentfield": "expense_approvers"},
                    pluck="approver",
                )
                if dept_approvers:
                    approver_email = frappe.db.get_value("User", dept_approvers[0], "email")

        if not approver_email:
            # Final fallback: notify Verenigingen Administrator role
            admin_emails = frappe.get_all(
                "Has Role",
                filters={"role": "Verenigingen Administrator", "parenttype": "User"},
                pluck="parent",
            )
            if admin_emails:
                approver_email = frappe.db.get_value("User", admin_emails[0], "email")

        if not approver_email:
            frappe.logger().warning(
                f"No expense approver found for expense claim {doc.name} (employee: {doc.employee})"
            )
            return

        # Get volunteer/member info if available for context
        volunteer_name = frappe.db.get_value("Volunteer", {"employee_id": doc.employee}, "name")
        member_name = None
        if volunteer_name:
            member_name = frappe.db.get_value("Volunteer", volunteer_name, "member")

        # Build email context
        # Expense Claim uses company currency, get it from Company settings
        company_currency = "EUR"  # Default fallback
        if doc.company:
            company_currency = frappe.db.get_value("Company", doc.company, "default_currency") or "EUR"

        context = {
            "expense_id": doc.name,
            "employee_name": employee.employee_name,
            "volunteer_name": volunteer_name,
            "member_name": member_name,
            "amount": doc.total_claimed_amount,
            "currency": company_currency,
            "expense_date": doc.posting_date,
            "description": _get_expense_description(doc),
            "review_url": f"{frappe.utils.get_url()}/app/expense-claim/{doc.name}",
        }

        # Send via EmailService which respects Verenigingen Email Configuration
        from verenigingen.services.communication.email_service import get_email_service

        email_service = get_email_service()
        result = email_service.send_simple_email(
            recipients=[approver_email],
            subject=_("Expense Approval Required - {0}").format(doc.name),
            message=_build_expense_approval_message(context),
            reference_doctype="Expense Claim",
            reference_name=doc.name,
            notification_key="expense_approval_request",
        )

        if result.success:
            frappe.logger().info(f"Expense approval notification sent to {approver_email} for {doc.name}")
        else:
            frappe.logger().warning(
                f"Failed to send expense approval notification: {result.error_message or 'Unknown error'}"
            )

    except Exception as e:
        # Log error but don't fail the expense claim submission
        frappe.log_error(
            f"Failed to send expense approval notification for {doc.name}: {str(e)}",
            "Expense Approval Notification Error",
        )
        frappe.logger().warning(f"Expense approval notification failed for {doc.name}: {str(e)}")


def _get_expense_description(doc):
    """Extract a summary description from expense claim items."""
    if not doc.expenses:
        return _("No description provided")

    descriptions = []
    for item in doc.expenses[:3]:  # Limit to first 3 items
        if item.description:
            descriptions.append(item.description[:50])

    if len(doc.expenses) > 3:
        descriptions.append(_("... and {0} more items").format(len(doc.expenses) - 3))

    return "; ".join(descriptions) if descriptions else _("No description provided")


def _build_expense_approval_message(context):
    """Build HTML message for expense approval notification."""
    return f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background-color: #fff3cd; padding: 20px; border-radius: 8px; margin-bottom: 20px;">
            <h2 style="color: #856404; margin: 0;">{_("Expense Approval Required")}</h2>
        </div>

        <div style="background-color: white; padding: 20px; border: 1px solid #e9ecef; border-radius: 8px;">
            <p>{_("A new expense claim has been submitted and requires your approval.")}</p>

            <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 15px 0;">
                <h3 style="margin-top: 0; color: #2c3e50;">{_("Expense Details:")}</h3>
                <table style="width: 100%; border-collapse: collapse;">
                    <tr>
                        <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;"><strong>{_("Expense ID:")}</strong></td>
                        <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;">{context['expense_id']}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;"><strong>{_("Submitted By:")}</strong></td>
                        <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;">{context['employee_name']}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;"><strong>{_("Amount:")}</strong></td>
                        <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6; font-size: 18px; color: #e74c3c;">{context['currency']} {context['amount']}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;"><strong>{_("Date:")}</strong></td>
                        <td style="padding: 8px 0; border-bottom: 1px solid #dee2e6;">{context['expense_date']}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0;"><strong>{_("Description:")}</strong></td>
                        <td style="padding: 8px 0;">{context['description']}</td>
                    </tr>
                </table>
            </div>

            <div style="text-align: center; margin: 20px 0;">
                <a href="{context['review_url']}" style="background-color: #28a745; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold; display: inline-block;">{_("Review Expense")}</a>
            </div>

            <hr style="margin: 20px 0; border: none; border-top: 1px solid #e9ecef;">
            <p style="font-size: 12px; color: #6c757d;">
                {_("This is an automated notification from the expense management system.")}
            </p>
        </div>
    </div>
    """
