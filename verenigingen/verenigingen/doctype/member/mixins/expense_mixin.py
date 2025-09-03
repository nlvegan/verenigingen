import frappe
from frappe import _
from frappe.utils import date_diff, today


class ExpenseMixin:
    """Mixin for volunteer expense-related functionality"""

    def add_expense_to_history(self, expense_claim_name):
        """Add a volunteer expense claim to member history using batched processing"""
        if not hasattr(self, "volunteer_expenses"):
            return

        # IMPROVED: Use 10s batching to eliminate lock contention
        from verenigingen.utils.financial_history_batch_processor import queue_expense_update

        queue_expense_update(self.name, expense_claim_name)
        return True  # Queued successfully

    def remove_expense_from_history(self, expense_claim_name):
        """Remove a cancelled expense claim from member history using batched processing"""
        if not hasattr(self, "volunteer_expenses"):
            return

        from verenigingen.utils.financial_history_batch_processor import queue_expense_removal

        queue_expense_removal(self.name, expense_claim_name)
        return True  # Queued successfully

    def update_expense_payment_status(self, expense_claim_name, payment_entry_name):
        """Update payment status for an expense claim in member history using batched processing"""
        if not hasattr(self, "volunteer_expenses"):
            return

        from verenigingen.utils.financial_history_batch_processor import queue_expense_payment_update

        try:
            # Get payment entry details
            payment_doc = frappe.get_doc("Payment Entry", payment_entry_name)

            # Prepare payment field updates
            payment_updates = {
                "payment_entry": payment_entry_name,
                "payment_date": payment_doc.posting_date,
                "paid_amount": payment_doc.paid_amount,
                "payment_method": payment_doc.mode_of_payment,
                "payment_status": "Paid",
            }

            queue_expense_payment_update(self.name, expense_claim_name, payment_updates)
            return True  # Queued successfully

        except Exception as e:
            frappe.log_error(
                f"Error queuing expense payment status update for {expense_claim_name}: {str(e)}",
                "Expense Payment Status Update Error",
            )
            return False

    def _build_expense_history_entry(self, expense_doc):
        """Build an expense history entry from an expense claim document"""
        try:
            # Get volunteer information
            volunteer_name = None
            if expense_doc.employee:
                # First try to find volunteer by employee_id field and member link
                volunteer_name = frappe.db.get_value(
                    "Volunteer",
                    {"employee_id": expense_doc.employee, "member": self.name},
                    "name",
                )

                # Fallback: if not found, try without member filter (for backward compatibility)
                if not volunteer_name:
                    volunteer_name = frappe.db.get_value(
                        "Volunteer", {"employee_id": expense_doc.employee}, "name"
                    )

            # Check for existing payment
            payment_entry = None
            payment_date = None
            paid_amount = 0
            payment_method = None
            payment_status = "Pending"

            # Look for payment entries referencing this expense claim
            payment_refs = frappe.get_all(
                "Payment Entry Reference",
                filters={"reference_doctype": "Expense Claim", "reference_name": expense_doc.name},
                fields=["parent", "allocated_amount"],
            )

            if payment_refs:
                # Get the most recent payment
                payment_entries = frappe.get_all(
                    "Payment Entry",
                    filters={"name": ["in", [ref.parent for ref in payment_refs]], "docstatus": 1},
                    fields=["name", "posting_date", "paid_amount", "mode_of_payment"],
                    order_by="posting_date desc",
                )

                if payment_entries:
                    payment_entry = payment_entries[0].name
                    payment_date = payment_entries[0].posting_date
                    paid_amount = payment_entries[0].paid_amount
                    payment_method = payment_entries[0].mode_of_payment
                    payment_status = "Paid"

            # Determine the appropriate status based on docstatus and approval_status
            expense_status = expense_doc.status
            if expense_doc.docstatus == 0:
                expense_status = "Draft"
            elif expense_doc.docstatus == 1:
                if hasattr(expense_doc, "approval_status"):
                    if expense_doc.approval_status == "Rejected":
                        expense_status = "Rejected"
                    elif expense_doc.approval_status == "Approved":
                        expense_status = expense_doc.status  # Use original status (Paid/Unpaid)

            return {
                "expense_claim": expense_doc.name,
                "volunteer": volunteer_name,
                "posting_date": expense_doc.posting_date,
                "total_claimed_amount": expense_doc.total_claimed_amount,
                "total_sanctioned_amount": expense_doc.total_sanctioned_amount,
                "status": expense_status,
                "payment_entry": payment_entry,
                "payment_date": payment_date,
                "paid_amount": paid_amount,
                "payment_method": payment_method,
                "payment_status": payment_status,
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
                "payment_status": "Draft",  # FIXED: Use valid payment status instead of "Unknown"
            }
