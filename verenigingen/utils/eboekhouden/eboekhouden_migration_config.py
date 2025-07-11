"""
E-Boekhouden Migration Configuration

This module provides configuration for proper payment migration
based on the actual chart of accounts structure.
"""

import json

import frappe

# Bank and cash account configurations for Nederlandse Vereniging voor Veganisme
PAYMENT_ACCOUNT_CONFIG = {
    "bank_accounts": {
        "10440": {
            "name": "Triodos - 19.83.96.716 - Algemeen",
            "type": "Bank",
            "mode_of_payment": "Bank Transfer",
        },
        "10470": {"name": "PayPal - info@veganisme.org", "type": "Bank", "mode_of_payment": "PayPal"},
        "10620": {"name": "ASN - 97.88.80.455", "type": "Bank", "mode_of_payment": "Bank Transfer"},
    },
    "cash_accounts": {"10000": {"name": "Kas", "type": "Cash", "mode_of_payment": "Cash"}},
}


def is_payment_account(account_code, company=None):
    """Check if an account code represents a payment account"""
    if not account_code:
        return False

    # First check database mappings if company is provided
    if company:
        mapping = frappe.db.exists(
            "EBoekhouden Payment Mapping",
            {"company": company, "eboekhouden_account_code": account_code, "active": 1},
        )
        if mapping:
            return True

    # Fallback to hardcoded config
    return (
        account_code in PAYMENT_ACCOUNT_CONFIG["bank_accounts"]
        or account_code in PAYMENT_ACCOUNT_CONFIG["cash_accounts"]
    )


def get_payment_account_info(account_code, company=None):
    """Get payment account configuration"""
    # First check database mappings if company is provided
    if company:
        from verenigingen.verenigingen.doctype.eboekhouden_payment_mapping.eboekhouden_payment_mapping import (
            get_payment_account_mapping,
        )

        mapping = get_payment_account_mapping(company, account_code)
        if mapping:
            return {
                "name": mapping.get("account_name"),
                "type": mapping.get("account_type"),
                "mode_of_payment": mapping.get("mode_of_payment"),
                "erpnext_account": mapping.get("erpnext_account"),
            }

    # Fallback to hardcoded config
    if account_code in PAYMENT_ACCOUNT_CONFIG["bank_accounts"]:
        return PAYMENT_ACCOUNT_CONFIG["bank_accounts"][account_code]
    elif account_code in PAYMENT_ACCOUNT_CONFIG["cash_accounts"]:
        return PAYMENT_ACCOUNT_CONFIG["cash_accounts"][account_code]
    return None


@frappe.whitelist()
def setup_payment_modes():
    """Setup required modes of payment for migration"""

    modes_to_create = [
        {"name": "Bank Transfer", "type": "Bank", "enabled": 1},
        {"name": "PayPal", "type": "Bank", "enabled": 1},
        {"name": "Cash", "type": "Cash", "enabled": 1},
        {"name": "SEPA Direct Debit", "type": "Bank", "enabled": 1},
    ]

    created = []
    for mode_config in modes_to_create:
        if not frappe.db.exists("Mode of Payment", mode_config["name"]):
            mode = frappe.new_doc("Mode of Payment")
            mode.mode_of_payment = mode_config["name"]
            mode.type = mode_config["type"]
            mode.enabled = mode_config["enabled"]
            mode.insert(ignore_permissions=True)
            created.append(mode_config["name"])

    frappe.db.commit()

    return {"success": True, "created": created, "message": "Created {len(created)} modes of payment"}


@frappe.whitelist()
def validate_migration_setup():
    """Validate that everything is set up correctly for payment migration"""

    issues = []
    warnings = []

    # Check if E-Boekhouden Settings exists
    try:
        settings = frappe.get_single("E-Boekhouden Settings")
        if not settings.default_company:
            issues.append("No default company set in E-Boekhouden Settings")
    except Exception:
        issues.append("E-Boekhouden Settings not found")

    # Check if payment accounts exist in ERPNext
    for account_code, info in PAYMENT_ACCOUNT_CONFIG["bank_accounts"].items():
        if not frappe.db.exists("Account", {"account_number": account_code}):
            warnings.append(
                f"Bank account {account_code} ({info['name']}) not found in Chart of Accounts"  # noqa: E713
            )

    for account_code, info in PAYMENT_ACCOUNT_CONFIG["cash_accounts"].items():
        if not frappe.db.exists("Account", {"account_number": account_code}):
            warnings.append(
                f"Cash account {account_code} ({info['name']}) not found in Chart of Accounts"  # noqa: E713
            )

    # Check modes of payment
    required_modes = ["Bank Transfer", "PayPal", "Cash", "SEPA Direct Debit"]
    for mode in required_modes:
        if not frappe.db.exists("Mode of Payment", mode):
            warnings.append("Mode of Payment f'{mode}' not found")

    # Check if there are customers and suppliers
    customer_count = frappe.db.count("Customer")
    supplier_count = frappe.db.count("Supplier")

    if customer_count == 0:
        warnings.append("No customers found - customer payments won't be created")
    if supplier_count == 0:
        warnings.append("No suppliers found - supplier payments won't be created")

    return {
        "success": len(issues) == 0,
        "issues": issues,
        "warnings": warnings,
        "summary": {
            "customers": customer_count,
            "suppliers": supplier_count,
            "ready_for_migration": len(issues) == 0,
        },
    }


@frappe.whitelist()
def test_payment_identification(limit=10):
    """Test payment identification with actual account configuration"""

    try:
        from datetime import datetime, timedelta

        from verenigingen.utils.eboekhouden_api import EBoekhoudenAPI

        api = EBoekhoudenAPI()

        # Get recent transactions
        today = datetime.now()
        last_month = today - timedelta(days=30)

        params = {"dateFrom": last_month.strftime("%Y-%m-%d"), "dateTo": today.strftime("%Y-%m-%d")}

        # Get transactions
        trans_result = api.get_mutations(params)
        if not trans_result["success"]:
            return {"success": False, "error": "Failed to get transactions"}

        transactions = json.loads(trans_result["data"]).get("items", [])[:limit]

        # Get accounts
        accounts_result = api.get_chart_of_accounts()
        if not accounts_result["success"]:
            return {"success": False, "error": "Failed to get accounts"}

        accounts = json.loads(accounts_result["data"]).get("items", [])
        account_lookup = {str(acc["id"]): acc for acc in accounts}

        # Analyze transactions with our configuration
        payment_transactions = []
        other_transactions = []

        for trans in transactions:
            ledger_id = str(trans.get("ledgerId", ""))
            account = account_lookup.get(ledger_id, {})
            account_code = account.get("code", "")

            if is_payment_account(account_code):
                payment_info = get_payment_account_info(account_code)
                payment_transactions.append(
                    {
                        "date": trans.get("date"),
                        "description": trans.get("description"),
                        "amount": trans.get("amount"),
                        "account_code": account_code,
                        "account_name": payment_info["name"],
                        "payment_type": payment_info["type"],
                        "mode_of_payment": payment_info["mode_of_payment"],
                        "has_relation": bool(trans.get("relationId")),
                        "will_create": "Payment Entry"
                        if trans.get("relationId")
                        else "Bank/Cash Transfer (Journal Entry)",
                    }
                )
            else:
                other_transactions.append(
                    {
                        "date": trans.get("date"),
                        "description": trans.get("description"),
                        "amount": trans.get("amount"),
                        "account_code": account_code,
                        "account_name": account.get("description", ""),
                        "will_create": "Journal Entry",
                    }
                )

        return {
            "success": True,
            "analyzed": len(transactions),
            "payment_transactions": payment_transactions,
            "other_transactions": other_transactions[:5],  # First 5 as sample
            "summary": {
                "payment_related": len(payment_transactions),
                "journal_entries": len(other_transactions),
            },
        }

    except Exception as e:
        import traceback

        frappe.log_error(traceback.format_exc(), "Payment identification test error")
        return {"success": False, "error": str(e)}
