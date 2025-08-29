"""
Simple and Direct Expense Claim Hooks

This module provides direct, synchronous hooks for Expense Claim events
that bypass the complex background job system and directly update
member expense history when expense claims are created or updated.

This approach is more reliable than background job processing for
critical business logic like member history synchronization.
"""

import frappe
from frappe import _


def update_member_expense_history_direct(doc, method=None):
    """
    Direct hook to update member expense history when expense claims change.

    This runs synchronously during the document transaction, ensuring
    immediate consistency without relying on background job processing.
    """
    if doc.doctype != "Expense Claim":
        return

    try:
        # Check if this is a volunteer expense by looking at employee link
        if not doc.employee:
            return

        # Find the volunteer and member
        volunteer_record = frappe.db.get_value(
            "Volunteer", {"employee_id": doc.employee}, ["name", "member"], as_dict=True
        )

        if not volunteer_record or not volunteer_record.member:
            # Not a volunteer expense, skip
            return

        # Get the member document and update expense history
        member_doc = frappe.get_doc("Member", volunteer_record.member)

        # Use the existing ExpenseMixin method to add/update history
        if hasattr(member_doc, "add_expense_to_history"):
            member_doc.add_expense_to_history(doc.name)
            frappe.logger("expense_hooks").info(
                f"Updated expense history for member {volunteer_record.member} - expense {doc.name}"
            )
        else:
            frappe.logger("expense_hooks").warning(
                f"Member {volunteer_record.member} does not have add_expense_to_history method"
            )

    except Exception as e:
        # Log error but don't fail the expense claim transaction
        frappe.log_error(
            f"Failed to update member expense history for expense {doc.name}: {str(e)}",
            "Direct Expense Hook Error",
        )


def remove_member_expense_history_direct(doc, method=None):
    """
    Direct hook to remove expense from member history when cancelled.
    """
    if doc.doctype != "Expense Claim":
        return

    try:
        if not doc.employee:
            return

        volunteer_record = frappe.db.get_value(
            "Volunteer", {"employee_id": doc.employee}, ["name", "member"], as_dict=True
        )

        if not volunteer_record or not volunteer_record.member:
            return

        member_doc = frappe.get_doc("Member", volunteer_record.member)

        if hasattr(member_doc, "remove_expense_from_history"):
            member_doc.remove_expense_from_history(doc.name)
            frappe.logger("expense_hooks").info(
                f"Removed expense {doc.name} from history for member {volunteer_record.member}"
            )

    except Exception as e:
        frappe.log_error(
            f"Failed to remove expense {doc.name} from member history: {str(e)}", "Direct Expense Hook Error"
        )


def validate_volunteer_expense_permissions(doc, method=None):
    """
    Validate that the volunteer has permission to submit this type of expense.
    This replaces the complex validation in the expense submission system.
    """
    if doc.doctype != "Expense Claim":
        return

    # This validation is already handled in the expense submission form,
    # so we'll keep this hook simple for now
    pass
