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

    Uses native Expense Claim data via Employee linkage.
    """
    try:
        volunteer_doc = frappe.get_doc("Volunteer", volunteer_name)

        # Check if volunteer has an employee_id linked
        if not volunteer_doc.employee_id:
            return _get_empty_statistics()

        # Calculate date range for filtering
        from_date = add_months(today(), -months_back)

        # Query native Expense Claims for this employee
        expense_claims = frappe.get_all(
            "Expense Claim",
            filters={
                "employee": volunteer_doc.employee_id,
                "posting_date": [">=", from_date],
            },
            fields=["total_claimed_amount", "total_sanctioned_amount", "status", "docstatus"],
        )

        total_submitted = 0
        total_approved = 0
        pending_count = 0
        approved_count = 0
        total_count = len(expense_claims)

        for claim in expense_claims:
            amount = flt(claim.total_claimed_amount)
            total_submitted += amount

            if claim.docstatus == 1 and claim.status in ["Approved", "Paid"]:
                total_approved += flt(claim.total_sanctioned_amount)
                approved_count += 1
            elif claim.docstatus == 0 or claim.status in ["Draft", "Unpaid"]:
                pending_count += 1

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

        # Count recent expenses from native Expense Claims
        if volunteer_doc.employee_id:
            recent_count = frappe.db.count(
                "Expense Claim",
                filters={
                    "employee": volunteer_doc.employee_id,
                    "posting_date": [">=", recent_date],
                },
            )

        # Add recent count to stats
        stats["recent_count"] = recent_count

    except Exception as e:
        frappe.log_error(f"Error calculating recent expense count: {str(e)}", "Recent Expense Count Error")
        stats["recent_count"] = 0

    return stats
