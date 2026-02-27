import frappe


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
        """Build an expense history entry. Delegates to ExpenseHistoryEntryBuilder."""
        from verenigingen.services.volunteer.expense_history_entry_builder import ExpenseHistoryEntryBuilder

        return ExpenseHistoryEntryBuilder.build_from_expense_doc(expense_doc, self.name)
