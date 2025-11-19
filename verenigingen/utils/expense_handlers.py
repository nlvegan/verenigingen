"""
Expense Claim Event Handlers

Handles Expense Claim document events like submission to update
Member financial history with proper permissions and error handling.
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

        # Update member expense history using the batch processor
        # This will be processed by the scheduled job with proper permissions
        from verenigingen.utils.financial_history_batch_processor import queue_expense_update

        queue_expense_update(member_name, doc.name)

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

        # Queue removal from member expense history
        from verenigingen.utils.financial_history_batch_processor import queue_expense_removal

        queue_expense_removal(member_name, doc.name)

        frappe.logger().info(
            f"Queued expense history removal for member {member_name} from cancelled expense claim {doc.name}"
        )

    except Exception as e:
        # Log error but don't fail the cancellation
        frappe.log_error(
            f"Failed to queue expense history removal for {doc.name}: {str(e)}",
            "Expense History Removal Error",
        )
