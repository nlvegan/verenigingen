"""
Check and Fix Account Types for E-Boekhouden Migration
"""

import frappe
from frappe.utils import flt


@frappe.whitelist()
def review_account_types(company):
    """Review account types for E-Boekhouden imported accounts and suggest fixes"""
    try:
        # Get all accounts with E-Boekhouden numbers
        accounts = frappe.db.sql(
            """
            SELECT name, account_name, account_type, root_type, account_number,
                   eboekhouden_grootboek_nummer, parent_account
            FROM `tabAccount`
            WHERE company = %s
            AND eboekhouden_grootboek_nummer IS NOT NULL
            AND eboekhouden_grootboek_nummer != ''
            ORDER BY account_number
        """,
            company,
            as_dict=True,
        )

        issues = []

        for account in accounts:
            account_code = account.get("eboekhouden_grootboek_nummer") or account.get("account_number", "")

            # Analyze account based on code patterns
            suggested_type, suggested_root = _analyze_account_code(account_code, account.account_name)

            if suggested_type and suggested_type != account.account_type:
                issues.append(
                    {
                        "account": account.name,
                        "account_name": account.account_name,
                        "account_code": account_code,
                        "current_type": account.account_type or "Not Set",
                        "suggested_type": suggested_type,
                        "current_root": account.root_type,
                        "suggested_root": suggested_root,
                        "reason": _get_suggestion_reason(account_code, suggested_type),
                    }
                )

        return {
            "success": True,
            "issues": issues,
            "total_accounts": len(accounts),
            "issues_found": len(issues),
        }

    except Exception as e:
        frappe.log_error(f"Error reviewing account types: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def fix_account_type_issues(issues):
    """Fix multiple account type issues"""
    try:
        if not issues:
            return {"success": True, "fixed_count": 0}

        # Parse issues if it's a string
        if isinstance(issues, str):
            import json

            issues = json.loads(issues)

        fixed_count = 0
        errors = []

        for issue in issues:
            try:
                # Update account type
                account = frappe.get_doc("Account", issue["account"])
                account.account_type = issue["suggested_type"]
                account.root_type = issue["suggested_root"]
                account.save(ignore_permissions=True)

                fixed_count += 1

            except Exception as e:
                errors.append(f"Failed to update {issue['account_name']}: {str(e)}")

        frappe.db.commit()

        return {"success": True, "fixed_count": fixed_count, "errors": errors}

    except Exception as e:
        frappe.log_error(f"Error fixing account type issues: {str(e)}")
        return {"success": False, "error": str(e)}


def _analyze_account_code(account_code, account_name):
    """Analyze account code and suggest appropriate type"""
    if not account_code:
        return None, None

    account_name_lower = (account_name or "").lower()

    # Bank accounts
    if account_code.startswith("10"):
        if account_code == "10000" or "kas" in account_name_lower:
            return "Cash", "Asset"
        else:
            return "Bank", "Asset"

    # Receivables
    elif account_code.startswith("13"):
        if (
            "te ontvangen" in account_name_lower
            or "debiteuren" in account_name_lower
            or "vordering" in account_name_lower
        ):
            return "Receivable", "Asset"
        else:
            return "Current Asset", "Asset"

    # Fixed assets
    elif account_code.startswith("02"):
        return "Fixed Asset", "Asset"

    # Current assets
    elif account_code.startswith("14"):
        return "Current Asset", "Asset"

    # Payables
    elif account_code.startswith("44"):
        if "te betalen" in account_name_lower or "crediteuren" in account_name_lower:
            return "Payable", "Liability"
        else:
            return "Current Liability", "Liability"

    # Other liabilities
    elif account_code.startswith(("17", "18")):
        return "Current Liability", "Liability"

    # Equity
    elif account_code.startswith("5"):
        return "", "Equity"

    # Income
    elif account_code.startswith("8"):
        return "", "Income"

    # Expenses
    elif account_code.startswith(("6", "7")):
        return "", "Expense"

    # Tax accounts
    elif any(tax_prefix in account_code for tax_prefix in ["1540", "1570", "1571", "1572"]):
        return "Tax", "Liability"

    # Default for other assets
    elif account_code.startswith(("0", "1")):
        return "Current Asset", "Asset"

    # Default for other liabilities
    elif account_code.startswith(("2", "3", "4")):
        return "Current Liability", "Liability"

    return None, None


def _get_suggestion_reason(account_code, suggested_type):
    """Get reason for the suggestion"""
    if account_code.startswith("10"):
        if account_code == "10000":
            return "Cash account (account code 10000)"
        return "Bank account (account code starts with 10)"

    elif account_code.startswith("13"):
        return "Receivable/Current Asset (account code starts with 13)"

    elif account_code.startswith("02"):
        return "Fixed Asset (account code starts with 02)"

    elif account_code.startswith("14"):
        return "Current Asset (account code starts with 14)"

    elif account_code.startswith("44"):
        return "Payable/Current Liability (account code starts with 44)"

    elif account_code.startswith(("17", "18")):
        return "Current Liability (account code starts with 17/18)"

    elif account_code.startswith("5"):
        return "Equity (account code starts with 5)"

    elif account_code.startswith("8"):
        return "Income (account code starts with 8)"

    elif account_code.startswith(("6", "7")):
        return "Expense (account code starts with 6/7)"

    elif any(tax_prefix in account_code for tax_prefix in ["1540", "1570", "1571", "1572"]):
        return "Tax account (BTW-related account code)"

    return f"Based on account code pattern ({account_code})"
