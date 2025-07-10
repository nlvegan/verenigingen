"""
Account Group Validation Hooks
Integrates the account group project framework with ERPNext transactions.
"""

import frappe
from frappe import _

from verenigingen.utils.account_group_project_framework import account_group_framework


def validate_journal_entry(doc, method):
    """Validate journal entry accounts against account group mappings"""
    for account in doc.accounts:
        if account.account:
            account_group = get_account_group_for_account(account.account)
            if account_group:
                result = account_group_framework.validate_transaction(
                    account_group, account.project, account.cost_center
                )

                if not result["valid"]:
                    frappe.throw("<br>".join(result["errors"]))

                # Apply defaults if not set
                apply_defaults_to_account_row(account, account_group)


def validate_expense_claim(doc, method):
    """Validate expense claim against account group mappings"""
    for expense in doc.expenses:
        if expense.default_account:
            account_group = get_account_group_for_account(expense.default_account)
            if account_group:
                result = account_group_framework.validate_transaction(
                    account_group, expense.project, expense.cost_center
                )

                if not result["valid"]:
                    frappe.throw("<br>".join(result["errors"]))

                # Apply defaults if not set
                apply_defaults_to_expense_row(expense, account_group)


def validate_purchase_invoice(doc, method):
    """Validate purchase invoice against account group mappings"""
    for item in doc.items:
        if item.expense_account:
            account_group = get_account_group_for_account(item.expense_account)
            if account_group:
                result = account_group_framework.validate_transaction(
                    account_group, item.project, item.cost_center
                )

                if not result["valid"]:
                    frappe.throw("<br>".join(result["errors"]))

                # Apply defaults if not set
                apply_defaults_to_item_row(item, account_group)


def apply_defaults_to_account_row(account_row, account_group):
    """Apply default project and cost center to journal entry account row"""
    defaults = account_group_framework.get_defaults_for_transaction(account_group)

    if not account_row.project and defaults.get("project"):
        account_row.project = defaults["project"]

    if not account_row.cost_center and defaults.get("cost_center"):
        account_row.cost_center = defaults["cost_center"]


def apply_defaults_to_expense_row(expense_row, account_group):
    """Apply default project and cost center to expense claim row"""
    defaults = account_group_framework.get_defaults_for_transaction(account_group)

    if not expense_row.project and defaults.get("project"):
        expense_row.project = defaults["project"]

    if not expense_row.cost_center and defaults.get("cost_center"):
        expense_row.cost_center = defaults["cost_center"]


def apply_defaults_to_item_row(item_row, account_group):
    """Apply default project and cost center to purchase invoice item row"""
    defaults = account_group_framework.get_defaults_for_transaction(account_group)

    if not item_row.project and defaults.get("project"):
        item_row.project = defaults["project"]

    if not item_row.cost_center and defaults.get("cost_center"):
        item_row.cost_center = defaults["cost_center"]


def get_account_group_for_account(account):
    """Get the account group for a given account"""
    if not account:
        return None

    # Check if account is a group itself
    account_doc = frappe.get_cached_doc("Account", account)
    if account_doc.is_group:
        return account

    # Walk up the parent chain to find the group
    current_account = account_doc
    while current_account.parent_account:
        parent = frappe.get_cached_doc("Account", current_account.parent_account)
        if parent.is_group and parent.root_type in ["Income", "Expense"]:
            # Check if this parent has a mapping
            if frappe.db.exists("Account Group Project Mapping", parent.name):
                return parent.name
        current_account = parent

    return None


@frappe.whitelist()
def get_account_group_info_for_account(account):
    """Get account group info for frontend use"""
    account_group = get_account_group_for_account(account)
    if not account_group:
        return {}

    mapping = account_group_framework.get_mapping(account_group)
    if not mapping:
        return {}

    return {
        "account_group": account_group,
        "account_group_type": mapping.get("account_group_type"),
        "tracking_mode": mapping.get("tracking_mode"),
        "requires_project": mapping.get("requires_project"),
        "requires_cost_center": mapping.get("requires_cost_center"),
        "default_project": mapping.get("default_project"),
        "default_cost_center": mapping.get("default_cost_center"),
        "description": mapping.get("description"),
    }


@frappe.whitelist()
def get_filtered_projects_for_account(account):
    """Get filtered projects for an account based on account group mapping"""
    account_group = get_account_group_for_account(account)
    if not account_group:
        return frappe.get_all("Project", filters={"status": "Open"}, fields=["name", "project_name"])

    return account_group_framework.get_valid_projects(account_group)


@frappe.whitelist()
def get_filtered_cost_centers_for_account(account):
    """Get filtered cost centers for an account based on account group mapping"""
    account_group = get_account_group_for_account(account)
    if not account_group:
        return frappe.get_all("Cost Center", filters={"disabled": 0}, fields=["name", "cost_center_name"])

    return account_group_framework.get_valid_cost_centers(account_group)


def setup_validation_hooks():
    """Setup validation hooks in the system"""

    # This would typically be called from hooks.py
    hooks = {
        "Journal Entry": {
            "validate": "verenigingen.utils.account_group_validation_hooks.validate_journal_entry"
        },
        "Expense Claim": {
            "validate": "verenigingen.utils.account_group_validation_hooks.validate_expense_claim"
        },
        "Purchase Invoice": {
            "validate": "verenigingen.utils.account_group_validation_hooks.validate_purchase_invoice"
        },
    }

    return hooks


# Client-side integration functions
@frappe.whitelist()
def get_account_defaults_for_form(account):
    """Get account defaults for form auto-population"""
    info = get_account_group_info_for_account(account)
    if not info:
        return {}

    return {
        "project": info.get("default_project"),
        "cost_center": info.get("default_cost_center"),
        "requires_project": info.get("requires_project"),
        "requires_cost_center": info.get("requires_cost_center"),
        "tracking_mode": info.get("tracking_mode"),
        "description": info.get("description"),
    }


@frappe.whitelist()
def validate_form_selection(account, project=None, cost_center=None):
    """Validate form selection before save"""
    account_group = get_account_group_for_account(account)
    if not account_group:
        return {"valid": True}

    return account_group_framework.validate_transaction(account_group, project, cost_center)
