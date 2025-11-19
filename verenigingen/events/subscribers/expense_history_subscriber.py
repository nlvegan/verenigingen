"""
Expense History Event Subscriber

This subscriber handles expense claim events to update member expense history.
Specifically tracks volunteer expense reimbursements.
"""

import frappe
from frappe import _


def handle_expense_claim_updated(event_name=None, event_data=None):
    """
    Handle any expense claim status change - add/update in member expense history.

    This handles all expense claim statuses: draft, submitted, approved, rejected.
    """
    if not event_data:
        return

    member = event_data.get("member")
    volunteer = event_data.get("volunteer")
    expense_claim = event_data.get("expense_claim")
    action = event_data.get("action")

    # Only process volunteer expenses with member links
    if not member or not volunteer or not expense_claim:
        return

    try:
        # Get member document
        member_doc = frappe.get_doc("Member", member)

        # Always add/update expense in history for all statuses
        if hasattr(member_doc, "add_expense_to_history"):
            member_doc.add_expense_to_history(expense_claim)

        frappe.logger("expense_history").info(
            f"Updated expense claim {expense_claim} in history for member {member} (volunteer {volunteer}, action: {action})"
        )

    except Exception as e:
        frappe.log_error(
            f"Failed to handle expense claim update {expense_claim} for member {member}: {str(e)}",
            "Expense History Update Error",
        )


def handle_expense_claim_approved(event_name=None, event_data=None):
    """
    Handle expense claim approval - specialized handler for approval state changes.

    This handler focuses on approval-specific actions that the general
    update handler doesn't cover. It avoids duplicate history updates
    by only handling rejected claims (removal) since approved claims
    are already handled by handle_expense_claim_updated.
    """
    if not event_data:
        return

    member = event_data.get("member")
    volunteer = event_data.get("volunteer")
    expense_claim = event_data.get("expense_claim")
    action = event_data.get("action")

    # Only process volunteer expenses with member links
    if not member or not volunteer or not expense_claim:
        return

    try:
        # Get member document
        member_doc = frappe.get_doc("Member", member)

        if action == "rejected":
            # Only handle rejected claims here - approved claims are handled by general update handler
            # Remove expense from history if rejected (in case it was added before)
            if hasattr(member_doc, "remove_expense_from_history"):
                member_doc.remove_expense_from_history(expense_claim)

            frappe.logger("expense_history").info(
                f"Removed rejected expense claim {expense_claim} from history for member {member}"
            )
        else:
            # For approved claims, let handle_expense_claim_updated handle the history update
            # to avoid duplicate entries. Just log that we're deferring to the general handler.
            frappe.logger("expense_history").debug(
                f"Deferring approved expense claim {expense_claim} history update to general handler for member {member}"
            )

    except Exception as e:
        frappe.log_error(
            f"Failed to handle expense claim approval {expense_claim} for member {member}: {str(e)}",
            "Expense History Update Error",
        )


def handle_expense_claim_rejected(event_name=None, event_data=None):
    """
    Handle expense claim rejection - remove from member expense history.

    This is called when an expense claim approval_status changes to 'Rejected'.
    """
    # Same logic as approved handler, but specifically for rejected events
    return handle_expense_claim_approved(event_name, event_data)


def handle_expense_claim_cancelled(event_name=None, event_data=None):
    """
    Handle expense claim cancellation - remove from member expense history.
    """
    if not event_data:
        return

    member = event_data.get("member")
    volunteer = event_data.get("volunteer")
    expense_claim = event_data.get("expense_claim")

    if not member or not volunteer or not expense_claim:
        return

    try:
        # Get member document and remove expense from history
        member_doc = frappe.get_doc("Member", member)

        if hasattr(member_doc, "remove_expense_from_history"):
            member_doc.remove_expense_from_history(expense_claim)

        frappe.logger("expense_history").info(
            f"Removed cancelled expense claim {expense_claim} from history for member {member}"
        )

    except Exception as e:
        frappe.log_error(
            f"Failed to remove expense claim {expense_claim} from history for member {member}: {str(e)}",
            "Expense History Removal Error",
        )


def handle_expense_payment_made(event_name=None, event_data=None):
    """
    Handle expense payment - update member expense history with payment details.
    """
    if not event_data:
        return

    member = event_data.get("member")
    volunteer = event_data.get("volunteer")
    expense_claim = event_data.get("expense_claim")
    payment_entry = event_data.get("payment_entry")

    if not member or not volunteer or not expense_claim:
        return

    try:
        # Get member document and update expense payment status
        member_doc = frappe.get_doc("Member", member)

        if hasattr(member_doc, "update_expense_payment_status"):
            member_doc.update_expense_payment_status(expense_claim, payment_entry)

        frappe.logger("expense_history").info(
            f"Updated expense payment for claim {expense_claim} in history for member {member}"
        )

    except Exception as e:
        frappe.log_error(
            f"Failed to update expense payment for claim {expense_claim} in history for member {member}: {str(e)}",
            "Expense Payment Update Error",
        )
