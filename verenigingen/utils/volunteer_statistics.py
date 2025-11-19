"""
Volunteer Statistics Utilities

Centralized utilities for calculating volunteer-related statistics including
expense tracking, activity summaries, and performance metrics.

This module prevents code duplication between different volunteer-related pages
and ensures consistent data calculations across the application.
"""

import frappe
from frappe import _
from frappe.utils import add_months, flt, today


def _get_empty_statistics():
    """Return empty statistics dictionary for error cases or permission denied scenarios"""
    return {
        "total_submitted": 0,
        "total_approved": 0,
        "pending_amount": 0,
        "pending_count": 0,
        "approved_count": 0,
        "total_count": 0,
    }


def get_volunteer_expense_statistics(volunteer_name, months_back=12):
    """
    Get comprehensive expense statistics for a volunteer

    This function uses the EXACT same data source as get_volunteer_expenses()
    to ensure consistency between displayed recent expenses and statistics.
    """
    try:
        # Mirror the exact logic from get_volunteer_expenses function
        volunteer_doc = frappe.get_doc("Volunteer", volunteer_name)
        if not volunteer_doc.member:
            return _get_empty_statistics()

        # Get member document to access stored expense history
        member_doc = frappe.get_doc("Member", volunteer_doc.member)

        # Get expenses from Member's volunteer_expenses child table (same as recent expenses)
        if not (hasattr(member_doc, "volunteer_expenses") and member_doc.volunteer_expenses):
            return _get_empty_statistics()

        # Calculate date range for filtering
        from_date = add_months(today(), -months_back)

        total_submitted = 0
        total_approved = 0
        pending_count = 0
        approved_count = 0
        total_count = 0

        # DEBUG: Log what we're processing
        debug_info = f"STATS FUNCTION: volunteer_name='{volunteer_name}', member='{volunteer_doc.member}'"
        debug_info += f"\nProcessing {len(member_doc.volunteer_expenses)} expenses, from_date={from_date}"

        for stored_expense in member_doc.volunteer_expenses:
            expense_date_raw = stored_expense.get("expense_date")
            amount = flt(stored_expense.get("amount", 0))
            status = stored_expense.get("status", "Draft")

            # Convert expense_date to date object if it's a string
            if isinstance(expense_date_raw, str):
                from datetime import datetime

                try:
                    expense_date = datetime.strptime(expense_date_raw, "%Y-%m-%d").date()
                except:
                    expense_date = None
            else:
                expense_date = expense_date_raw

            debug_info += f"\nExpense: raw_date={expense_date_raw} ({type(expense_date_raw)}), converted_date={expense_date}, amount={amount}, status={status}"
            debug_info += f", from_date={from_date} ({type(from_date)}), comparison={expense_date >= from_date if expense_date else False}"

            # TEMPORARY: Skip date filtering to test if that's the issue
            # if not expense_date or expense_date < from_date:
            #     debug_info += " -> SKIPPED (date filter)"
            #     continue

            total_count += 1
            total_submitted += amount
            debug_info += f" -> COUNTED (total_submitted now {total_submitted})"

            if status == "Approved":
                total_approved += amount
                approved_count += 1
            elif status in ["Submitted", "Draft", "Awaiting Approval"]:
                pending_count += 1

        # Log the complete debug info AND store it for template display
        frappe.log_error(debug_info, "Expense Statistics Debug")

        # HACK: Store debug info in response for immediate visibility
        if hasattr(frappe.local, "response"):
            frappe.local.response.setdefault("debug_info", []).append(debug_info)

        return {
            "total_submitted": total_submitted,
            "total_approved": total_approved,
            "pending_amount": total_submitted - total_approved,
            "pending_count": pending_count,
            "approved_count": approved_count,
            "total_count": total_count,
        }

    except Exception as e:
        frappe.log_error(f"Error getting expense statistics: {str(e)}", "Volunteer Expense Statistics Error")
        return _get_empty_statistics()


def get_volunteer_expense_summary(volunteer_name):
    """
    Get expense summary for volunteer dashboard (wrapper for consistency)

    Args:
        volunteer_name (str): Name of the volunteer record

    Returns:
        dict: Summary with additional 'recent_count' for dashboard compatibility
    """
    # Get standard statistics
    stats = get_volunteer_expense_statistics(volunteer_name)

    # Add recent count (last month) for dashboard compatibility
    try:
        recent_date = add_months(today(), -1)
        volunteer_doc = frappe.get_doc("Volunteer", volunteer_name)

        recent_count = 0

        # Count recent expenses from Member's volunteer_expenses child table
        if volunteer_doc.member:
            member_doc = frappe.get_doc("Member", volunteer_doc.member)
            if hasattr(member_doc, "volunteer_expenses") and member_doc.volunteer_expenses:
                for expense in member_doc.volunteer_expenses:
                    expense_date = expense.get("expense_date")
                    if expense_date and expense_date >= recent_date:
                        recent_count += 1

        # Add recent count to stats
        stats["recent_count"] = recent_count

    except Exception as e:
        frappe.log_error(f"Error calculating recent expense count: {str(e)}", "Recent Expense Count Error")
        stats["recent_count"] = 0

    return stats
