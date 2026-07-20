"""
Delayed Expense Hook System with Retry Logic

This module implements a delayed hook system that avoids race conditions
by waiting for the primary transaction to complete before updating member
expense history. Uses exponential backoff retry logic to handle conflicts.
"""

from datetime import datetime, timedelta

import frappe
from frappe import _


def schedule_member_expense_history_update(doc, method=None):
    """
    Schedule a member expense history update using the new batching system.

    UPDATED: Now uses the 10s batching system instead of custom delayed processing
    to avoid duplicate queueing and reduce total processing time.
    """
    if doc.doctype != "Expense Claim":
        return

    # Only process volunteer expenses
    if not doc.employee:
        return

    # Check if this is a volunteer expense
    volunteer_record = frappe.db.get_value(
        "Volunteer", {"employee_id": doc.employee}, ["name", "member"], as_dict=True
    )

    if not volunteer_record or not volunteer_record.member:
        return

    # FIXED: Use new batching system directly (eliminates 15s delay + 10s batch = 25s total)
    from verenigingen.utils.financial_history_batch_processor import queue_expense_update

    queue_expense_update(volunteer_record.member, doc.name)

    frappe.logger("delayed_expense_hooks").info(
        f"Queued expense history update for member {volunteer_record.member}, expense {doc.name} (batching system)"
    )

    frappe.logger("delayed_expense_hooks").info(
        f"Scheduled delayed expense history update for member {volunteer_record.member}, expense {doc.name}"
    )


def update_member_expense_history_with_retry(expense_claim_name, member_name, attempt=1, max_attempts=3):
    """
    Update member expense history with retry logic and conflict detection.

    Args:
        expense_claim_name: Name of the expense claim
        member_name: Name of the member to update
        attempt: Current attempt number (1-based)
        max_attempts: Maximum number of attempts
    """
    try:
        frappe.logger("delayed_expense_hooks").info(
            f"Attempting member expense history update (attempt {attempt}/{max_attempts}) - "
            f"member {member_name}, expense {expense_claim_name}"
        )

        # Check if expense claim still exists
        if not frappe.db.exists("Expense Claim", expense_claim_name):
            frappe.logger("delayed_expense_hooks").info(
                f"Expense claim {expense_claim_name} no longer exists, skipping update"
            )
            return

        # Get member document with conflict detection
        member_doc = frappe.get_doc("Member", member_name)

        # Check if member was recently modified (potential conflict indicator)
        member_modified = member_doc.modified
        now = datetime.now()

        # If member was modified in the last 30 seconds, there might be a conflict
        if member_modified and (now - member_modified).total_seconds() < 30:
            raise frappe.ValidationError("Member record recently modified, potential conflict detected")

        # Perform the update using the existing ExpenseMixin method
        if hasattr(member_doc, "add_expense_to_history"):
            member_doc.add_expense_to_history(expense_claim_name)

            frappe.logger("delayed_expense_hooks").info(
                f"Successfully updated expense history for member {member_name} - expense {expense_claim_name}"
            )
            return
        else:
            frappe.log_error(
                f"Member {member_name} does not have add_expense_to_history method",
                "Delayed Expense Hook Error",
            )
            return

    except Exception as e:
        frappe.logger("delayed_expense_hooks").warning(
            f"Attempt {attempt} failed for member {member_name}, expense {expense_claim_name}: {str(e)}"
        )

        # Retry logic with exponential backoff
        if attempt < max_attempts:
            next_attempt = attempt + 1

            # Calculate delay: 30s for attempt 2, 60s for attempt 3
            if next_attempt == 2:
                delay = 30
            elif next_attempt == 3:
                delay = 60
            else:
                delay = 120  # Fallback

            frappe.logger("delayed_expense_hooks").info(
                f"Scheduling retry {next_attempt}/{max_attempts} in {delay}s for member {member_name}, expense {expense_claim_name}"
            )

            # Schedule the retry
            frappe.enqueue(
                method="verenigingen.events.delayed_expense_hooks.update_member_expense_history_with_retry",
                queue="short",
                delay=delay,
                expense_claim_name=expense_claim_name,
                member_name=member_name,
                attempt=next_attempt,
                max_attempts=max_attempts,
                timeout=120,
            )
        else:
            # All attempts failed, log final error
            frappe.log_error(
                f"Failed to update member expense history after {max_attempts} attempts. "
                f"Member: {member_name}, Expense: {expense_claim_name}, Final error: {str(e)}",
                "Delayed Expense Hook Final Failure",
            )


def schedule_member_expense_history_removal(doc, method=None):
    """
    No-op: removal is now owned by expense_handlers.on_expense_claim_cancel,
    which enqueues the same drain job with the same job_id (so a duplicate
    enqueue from here would only collapse via deduplicate anyway). Kept
    defined so the on_cancel hook wiring in hooks/doc_events.py stays valid.
    """
    return


def remove_member_expense_history_with_retry(expense_claim_name, member_name):
    """
    Remove expense from member history with simple retry.
    """
    try:
        member_doc = frappe.get_doc("Member", member_name)

        if hasattr(member_doc, "remove_expense_from_history"):
            member_doc.remove_expense_from_history(expense_claim_name)

            frappe.logger("delayed_expense_hooks").info(
                f"Successfully removed expense {expense_claim_name} from member {member_name} history"
            )

    except Exception as e:
        frappe.log_error(
            f"Failed to remove expense {expense_claim_name} from member {member_name} history: {str(e)}",
            "Delayed Expense Hook Removal Error",
        )
