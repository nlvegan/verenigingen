"""
Expense History Entry Builder

Provides a single source of truth for building Member Volunteer Expense entries.
Used by both individual updates (ExpenseMixin) and batch processing
(FinancialHistoryBatchProcessor) to ensure consistency.
"""

from typing import Any, Dict, Optional

import frappe


class ExpenseHistoryEntryBuilder:
    """
    Builds Member Volunteer Expense history entries with consistent structure.

    Extracted from ExpenseMixin._build_expense_history_entry() to allow
    direct use from batch processors without loading the full Member document.
    """

    VALID_PAYMENT_STATUSES = {"Pending", "Paid", "Draft"}

    @staticmethod
    def build_from_expense_doc(expense_doc, member_name: str) -> Dict[str, Any]:
        """
        Build an expense history entry from an Expense Claim document.

        Args:
            expense_doc: Expense Claim document
            member_name: Member name (used for volunteer lookup)

        Returns:
            Dictionary with expense history entry data
        """
        try:
            volunteer_name = ExpenseHistoryEntryBuilder._resolve_volunteer(expense_doc, member_name)
            payment_info = ExpenseHistoryEntryBuilder._resolve_payment_info(expense_doc)
            expense_status = ExpenseHistoryEntryBuilder._resolve_status(expense_doc)

            return {
                "expense_claim": expense_doc.name,
                "volunteer": volunteer_name,
                "posting_date": expense_doc.posting_date,
                "total_claimed_amount": expense_doc.total_claimed_amount,
                "total_sanctioned_amount": expense_doc.total_sanctioned_amount,
                "status": expense_status,
                "payment_entry": payment_info["payment_entry"],
                "payment_date": payment_info["payment_date"],
                "paid_amount": payment_info["paid_amount"],
                "payment_method": payment_info["payment_method"],
                "payment_status": payment_info["payment_status"],
            }

        except Exception as e:
            frappe.log_error(
                f"Error building expense history entry for {expense_doc.name}: {str(e)}",
                "Expense History Entry Build Error",
            )
            # Return minimal entry on error
            return {
                "expense_claim": expense_doc.name,
                "posting_date": expense_doc.posting_date,
                "total_sanctioned_amount": expense_doc.total_sanctioned_amount,
                "status": expense_doc.status,
                "payment_status": "Draft",
            }

    @staticmethod
    def _resolve_volunteer(expense_doc, member_name: str) -> Optional[str]:
        """Resolve volunteer name from expense claim's employee field."""
        if not expense_doc.employee:
            return None

        # Try to find volunteer by employee_id and member link
        volunteer_name = frappe.db.get_value(
            "Volunteer",
            {"employee_id": expense_doc.employee, "member": member_name},
            "name",
        )

        # Fallback: try without member filter (for backward compatibility)
        if not volunteer_name:
            volunteer_name = frappe.db.get_value("Volunteer", {"employee_id": expense_doc.employee}, "name")

        return volunteer_name

    @staticmethod
    def _resolve_payment_info(expense_doc) -> Dict[str, Any]:
        """Resolve payment entry information for an expense claim."""
        result = {
            "payment_entry": None,
            "payment_date": None,
            "paid_amount": 0,
            "payment_method": None,
            "payment_status": "Pending",
        }

        payment_refs = frappe.get_all(
            "Payment Entry Reference",
            filters={
                "reference_doctype": "Expense Claim",
                "reference_name": expense_doc.name,
            },
            fields=["parent", "allocated_amount"],
        )

        if not payment_refs:
            return result

        # Get the most recent submitted payment
        payment_entries = frappe.get_all(
            "Payment Entry",
            filters={
                "name": ["in", [ref.parent for ref in payment_refs]],
                "docstatus": 1,
            },
            fields=["name", "posting_date", "paid_amount", "mode_of_payment"],
            order_by="posting_date desc",
        )

        if payment_entries:
            result["payment_entry"] = payment_entries[0].name
            result["payment_date"] = payment_entries[0].posting_date
            result["paid_amount"] = payment_entries[0].paid_amount
            result["payment_method"] = payment_entries[0].mode_of_payment
            result["payment_status"] = "Paid"

        return result

    @staticmethod
    def _resolve_status(expense_doc) -> str:
        """Determine the appropriate status based on docstatus and approval_status."""
        if expense_doc.docstatus == 0:
            return "Draft"

        if expense_doc.docstatus == 1 and hasattr(expense_doc, "approval_status"):
            if expense_doc.approval_status == "Rejected":
                return "Rejected"
            if expense_doc.approval_status == "Approved":
                return expense_doc.status  # Use original status (Paid/Unpaid)

        return expense_doc.status
