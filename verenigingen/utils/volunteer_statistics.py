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

from verenigingen.utils.security.api_security_framework import OperationType, standard_api


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


@frappe.whitelist()
@standard_api(operation_type=OperationType.MEMBER_DATA)
def get_volunteer_expense_statistics(volunteer_name, months_back=12):
    """
    Get comprehensive expense statistics for a volunteer

    Args:
        volunteer_name (str): Name of the volunteer record
        months_back (int): Number of months to look back (default: 12)

    Returns:
        dict: Dictionary containing expense statistics with keys:
            - total_submitted: Total amount submitted in period
            - total_approved: Total amount approved/reimbursed
            - pending_amount: Amount still pending approval
            - pending_count: Number of expenses pending
            - approved_count: Number of expenses approved/reimbursed
            - total_count: Total number of expenses
    """
    try:
        # Get expenses from specified months back
        from_date = add_months(today(), -months_back)

        total_submitted = 0
        total_approved = 0
        pending_count = 0
        approved_count = 0
        reimbursed_count = 0
        total_count = 0

        # Check if volunteer exists and user has permission to access it
        if not frappe.db.exists("Volunteer", volunteer_name):
            frappe.logger().warning(f"Volunteer {volunteer_name} not found")
            return _get_empty_statistics()

        # Validate permission to read volunteer data
        if not frappe.has_permission("Volunteer", "read", volunteer_name):
            frappe.logger().warning(
                f"Permission denied to access volunteer {volunteer_name} for user {frappe.session.user}"
            )
            return _get_empty_statistics()

        # Get volunteer document
        volunteer_doc = frappe.get_doc("Volunteer", volunteer_name)

        frappe.logger().debug(
            f"Getting expense statistics for volunteer {volunteer_name}, employee_id: {getattr(volunteer_doc, 'employee_id', 'None')}"
        )

        # Try ERPNext Expense Claims first if employee_id exists
        if hasattr(volunteer_doc, "employee_id") and volunteer_doc.employee_id:
            # Get ERPNext Expense Claims for this employee
            expense_claims = frappe.get_all(
                "Expense Claim",
                filters={
                    "employee": volunteer_doc.employee_id,
                    "posting_date": [">=", from_date],
                    "docstatus": ["!=", 2],  # Not cancelled
                },
                fields=[
                    "total_claimed_amount",
                    "total_sanctioned_amount",
                    "status",
                    "approval_status",
                ],
            )

            for claim in expense_claims:
                amount = flt(claim.total_claimed_amount)
                status = _map_erpnext_status_to_volunteer_status(claim.status, claim.approval_status)

                total_count += 1
                # All expenses count toward total_submitted
                total_submitted += amount

                if status == "Approved":
                    sanctioned_amount = flt(claim.total_sanctioned_amount or amount)
                    total_approved += sanctioned_amount
                    approved_count += 1
                elif status == "Awaiting Approval":  # Draft status = pending approval
                    pending_count += 1
                elif status == "Submitted":  # Submitted but not yet approved/rejected
                    pending_count += 1
                elif status == "Rejected":  # Rejected expenses
                    pass  # Already counted in total_submitted
                elif status == "Reimbursed":
                    total_approved += flt(claim.total_sanctioned_amount or amount)
                    reimbursed_count += 1

        # Also check Volunteer Expense records as fallback
        # This covers volunteers who haven't had ERPNext expense claims created yet
        volunteer_expenses = frappe.get_all(
            "Volunteer Expense",
            filters={
                "volunteer": volunteer_name,
                "expense_date": [">=", from_date],
                "docstatus": ["!=", 2],  # Not cancelled
            },
            fields=["amount", "status"],
        )

        for expense in volunteer_expenses:
            amount = flt(expense.amount)
            status = expense.status

            total_count += 1
            total_submitted += amount

            if status == "Approved":
                total_approved += amount
                approved_count += 1
            elif status in ["Submitted", "Awaiting Approval"]:
                pending_count += 1

        stats = {
            "total_submitted": total_submitted,
            "total_approved": total_approved,
            "pending_amount": total_submitted - total_approved,
            "pending_count": pending_count,
            "approved_count": approved_count + reimbursed_count,
            "total_count": total_count,
        }

        frappe.logger().debug(f"Expense statistics for volunteer {volunteer_name}: {stats}")
        return stats

    except Exception as e:
        frappe.log_error(f"Error getting expense statistics: {str(e)}", "Volunteer Expense Statistics Error")
        # Return empty statistics if error occurs
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

        # Count recent ERPNext expenses if employee exists
        if hasattr(volunteer_doc, "employee_id") and volunteer_doc.employee_id:
            recent_erpnext = frappe.db.count(
                "Expense Claim",
                filters={
                    "employee": volunteer_doc.employee_id,
                    "posting_date": [">=", recent_date],
                    "docstatus": ["!=", 2],
                },
            )
            recent_count += recent_erpnext

        # Count recent Volunteer Expenses
        recent_volunteer = frappe.db.count(
            "Volunteer Expense",
            filters={
                "volunteer": volunteer_name,
                "expense_date": [">=", recent_date],
                "docstatus": ["!=", 2],
            },
        )
        recent_count += recent_volunteer

        # Add recent count to stats
        stats["recent_count"] = recent_count

    except Exception as e:
        frappe.log_error(f"Error calculating recent expense count: {str(e)}", "Recent Expense Count Error")
        stats["recent_count"] = 0

    return stats


def _map_erpnext_status_to_volunteer_status(erpnext_status, approval_status):
    """Map ERPNext Expense Claim status to Volunteer Expense status"""
    if erpnext_status == "Draft":
        return "Awaiting Approval"
    elif erpnext_status == "Submitted":
        if approval_status == "Approved":
            return "Approved"
        elif approval_status == "Rejected":
            return "Rejected"
        else:
            return "Submitted"
    elif erpnext_status == "Unpaid":
        # Unpaid means it's been processed (approved/rejected)
        if approval_status == "Approved":
            return "Approved"
        elif approval_status == "Rejected":
            return "Rejected"
        else:
            return "Submitted"
    elif erpnext_status == "Paid":
        return "Reimbursed"
    elif erpnext_status == "Cancelled":
        return "Rejected"
    else:
        return "Submitted"  # Default fallback
