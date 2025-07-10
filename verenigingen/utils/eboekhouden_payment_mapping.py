"""
Payment account mapping utilities for eBoekhouden migration

Provides flexible account mapping configuration for different organizations
"""

import frappe
from frappe import _


def get_payment_account_mappings(company):
    """Get all payment account mappings for a company"""
    mappings = {}

    # Check if DocType exists first
    if not frappe.db.exists("DocType", "E-Boekhouden Payment Mapping"):
        # Return default mappings if DocType doesn't exist
        return get_default_payment_mappings(company)

    try:
        # Get all active mappings for the company
        mapping_docs = frappe.get_all(
            "E-Boekhouden Payment Mapping",
            filters={"company": company},
            fields=["*"],
            order_by="priority desc",
        )

        # Process mappings by type
        for mapping in mapping_docs:
            if mapping.mapping_type == "Account Type":
                key = "{mapping.account_type.lower()}_account"
                mappings[key] = mapping.erpnext_account
            elif mapping.mapping_type == "Specific Account":
                key = "eboekhouden_{mapping.eboekhouden_account}"
                mappings[key] = mapping.erpnext_account
            elif mapping.mapping_type == "Account Number Pattern":
                key = "pattern_{mapping.account_pattern}"
                mappings[key] = mapping.erpnext_account

        # If no mappings found, use defaults
        if not mappings:
            return get_default_payment_mappings(company)

    except Exception as e:
        frappe.log_error(f"Error getting payment mappings: {str(e)}", "Payment Mapping Error")
        return get_default_payment_mappings(company)

    return mappings


def get_default_payment_mappings(company):
    """Get default payment account mappings based on account types"""
    defaults = {}

    # Get default accounts by type
    account_types = {
        "receivable_account": "Receivable",
        "payable_account": "Payable",
        "bank_account": "Bank",
        "cash_account": "Cash",
    }

    for key, account_type in account_types.items():
        account = frappe.db.get_value(
            "Account", {"company": company, "account_type": account_type, "is_group": 0}, "name"
        )
        if account:
            defaults[key] = account

    # Get default expense account
    expense_account = frappe.db.get_value(
        "Account", {"company": company, "root_type": "Expense", "is_group": 0}, "name"
    )
    if expense_account:
        defaults["expense_account"] = expense_account

    # Get default income account
    income_account = frappe.db.get_value(
        "Account", {"company": company, "root_type": "Income", "is_group": 0}, "name"
    )
    if income_account:
        defaults["income_account"] = income_account

    return defaults


def get_mapped_account(company, eboekhouden_account_code=None, account_type=None):
    """
    Get the mapped ERPNext account for an eBoekhouden account

    Args:
        company: Company name
        eboekhouden_account_code: E-Boekhouden account code
        account_type: Type of account (Bank, Cash, etc.)

    Returns:
        ERPNext account name or None
    """
    mappings = get_payment_account_mappings(company)

    # Try specific account mapping first
    if eboekhouden_account_code:
        specific_key = f"eboekhouden_{eboekhouden_account_code}"
        if specific_key in mappings:
            return mappings[specific_key]

        # Try pattern matching
        for key, account in mappings.items():
            if key.startswith("pattern_"):
                pattern = key.replace("pattern_", "").replace("%", "")
                if eboekhouden_account_code.startswith(pattern):
                    return account

    # Try account type mapping
    if account_type:
        type_key = "{account_type.lower()}_account"
        if type_key in mappings:
            return mappings[type_key]

    return None


@frappe.whitelist()
def setup_default_payment_mappings(company):
    """Setup default payment mappings for a company"""

    # Check if DocType exists
    if not frappe.db.exists("DocType", "E-Boekhouden Payment Mapping"):
        return {
            "success": False,
            "error": "E-Boekhouden Payment Mapping DocType not found. Please run bench migrate.",
        }

    try:
        # Get default accounts
        defaults = get_default_payment_mappings(company)
        created_mappings = []

        # Create mappings for each default account type
        mapping_configs = [
            ("Receivable", "receivable_account"),
            ("Payable", "payable_account"),
            ("Bank", "bank_account"),
            ("Cash", "cash_account"),
        ]

        for account_type, key in mapping_configs:
            if key in defaults:
                # Check if mapping already exists
                existing = frappe.db.exists(
                    "E-Boekhouden Payment Mapping",
                    {"company": company, "mapping_type": "Account Type", "account_type": account_type},
                )

                if not existing:
                    doc = frappe.get_doc(
                        {
                            "doctype": "E-Boekhouden Payment Mapping",
                            "company": company,
                            "mapping_type": "Account Type",
                            "account_type": account_type,
                            "erpnext_account": defaults[key],
                            "is_default": 1,
                            "priority": 100,
                        }
                    )
                    doc.insert()
                    created_mappings.append("{account_type} → {defaults[key]}")

        frappe.db.commit()

        return {
            "success": True,
            "message": "Created {len(created_mappings)} default mappings",
            "mappings": created_mappings,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
