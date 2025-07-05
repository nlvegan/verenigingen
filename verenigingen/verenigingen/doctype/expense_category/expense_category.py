import frappe
from frappe.model.document import Document


class ExpenseCategory(Document):
    def validate(self):
        """Validate expense category"""
        self.validate_expense_account()

    def validate_expense_account(self):
        """Ensure the linked account is an expense account"""
        if self.expense_account:
            account = frappe.get_doc("Account", self.expense_account)
            if account.account_type != "Expense Account":
                frappe.throw(
                    f"Account {self.expense_account} is not an Expense Account. "
                    "Please select a valid expense account."
                )
