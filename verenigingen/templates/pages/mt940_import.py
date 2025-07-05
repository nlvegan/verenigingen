import frappe
from frappe import _


def get_context(context):
    """Get context for MT940 import page"""

    # Check permissions
    if not frappe.has_permission("Bank Transaction", "write"):
        frappe.throw(_("You don't have permission to import bank transactions"), frappe.PermissionError)

    context.title = _("Import MT940 Bank Statement")

    # Get available bank accounts for selection
    company = frappe.defaults.get_user_default("Company") or frappe.get_all("Company", limit=1)[0].name

    bank_accounts = frappe.get_all(
        "Bank Account",
        filters={"company": company},
        fields=["name", "account_name", "bank", "bank_account_no", "iban"],
        order_by="account_name",
    )

    context.bank_accounts = bank_accounts
    context.company = company

    return context
