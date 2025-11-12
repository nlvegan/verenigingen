"""
Account Type Validator

Validates and fixes account_type assignments after E-Boekhouden Chart of Accounts import.
Prevents ERPNext validation errors from invalid account types on leaf accounts.
"""

import frappe

# Account types that are ONLY valid for group accounts
GROUP_ONLY_ACCOUNT_TYPES = [
    "Current Asset",
    "Fixed Asset",
    "Current Liability",
    "Equity",
    "Income",
    "Expense",
]

# Account types valid for leaf (non-group) accounts
LEAF_VALID_ACCOUNT_TYPES = [
    "Bank",
    "Cash",
    "Receivable",
    "Payable",
    "Stock",
    "Tax",
    "Temporary",
    "Accumulated Depreciation",
    "Depreciation",
    "Fixed Asset",  # Can be leaf if it's a specific asset
    "Capital Work in Progress",
    "Asset Received But Not Billed",
    "Expenses Included In Asset Valuation",
    "Expenses Included In Valuation",
]


def validate_and_fix_account_types(company, dry_run=False):
    """
    Validate all accounts and fix invalid account_type assignments.

    Args:
        company: Company name to validate
        dry_run: If True, only report issues without fixing

    Returns:
        dict: Results including fixed accounts and errors
    """
    results = {
        "company": company,
        "dry_run": dry_run,
        "checked": 0,
        "invalid_found": 0,
        "fixed": [],
        "errors": [],
        "warnings": [],
    }

    try:
        # Get all leaf accounts (non-group) with account_type set
        leaf_accounts = frappe.db.get_all(
            "Account",
            filters={"company": company, "is_group": 0, "account_type": ["is", "set"]},
            fields=["name", "account_name", "account_number", "account_type", "root_type", "parent_account"],
        )

        results["checked"] = len(leaf_accounts)

        for account in leaf_accounts:
            # Check if account has a group-only type
            if account.account_type in GROUP_ONLY_ACCOUNT_TYPES:
                results["invalid_found"] += 1
                issue = {
                    "account": account.name,
                    "account_number": account.account_number,
                    "account_name": account.account_name,
                    "invalid_type": account.account_type,
                    "root_type": account.root_type,
                    "parent": account.parent_account,
                }

                if dry_run:
                    results["warnings"].append(
                        f"❌ {account.account_number} - {account.account_name}: "
                        f"has invalid account_type '{account.account_type}' (group-only type on leaf account)"
                    )
                else:
                    # Fix the account by clearing the invalid account_type
                    try:
                        acc_doc = frappe.get_doc("Account", account.name)
                        old_type = acc_doc.account_type
                        acc_doc.account_type = None
                        acc_doc.save()

                        issue["fixed"] = True
                        issue["old_type"] = old_type
                        issue["new_type"] = None

                        results["fixed"].append(issue)

                        frappe.logger().info(
                            f"Fixed account {account.name}: cleared invalid account_type '{old_type}'"
                        )

                    except Exception as e:
                        issue["error"] = str(e)
                        results["errors"].append(issue)
                        frappe.logger().error(
                            f"Failed to fix account {account.name}: {str(e)}\n{frappe.get_traceback()}"
                        )

        if not dry_run and results["fixed"]:
            frappe.db.commit()

    except Exception as e:
        results["errors"].append({"general_error": str(e), "traceback": frappe.get_traceback()})
        frappe.log_error(title="Account Type Validation Error", message=frappe.get_traceback())

    return results


def get_recommended_account_type(account_name, account_number, root_type):
    """
    Suggest an appropriate account_type for an account based on its characteristics.

    Args:
        account_name: Account name
        account_number: Account number
        root_type: Root type (Asset, Liability, etc.)

    Returns:
        str or None: Recommended account type, or None for no specific type
    """
    account_name_lower = account_name.lower()
    account_num_str = str(account_number) if account_number else ""

    # Bank accounts (10xx-11xx range or keywords)
    if any(keyword in account_name_lower for keyword in ["bank", "rekening courant", "betaalrekening"]):
        return "Bank"

    # Cash accounts (kas)
    if "kas" in account_name_lower:
        return "Cash"

    # Receivables (debiteuren, vorderingen - but not group accounts)
    if root_type == "Asset":
        if any(keyword in account_name_lower for keyword in ["debiteur", "te ontvangen"]):
            return "Receivable"

    # Payables (crediteuren, te betalen)
    if root_type == "Liability":
        if any(keyword in account_name_lower for keyword in ["crediteur", "te betalen", "schulden aan"]):
            return "Payable"

    # Tax accounts
    if any(keyword in account_name_lower for keyword in ["btw", "belasting", "vat"]):
        return "Tax"

    # For most accounts, no specific type is needed
    return None


def generate_account_type_report(company):
    """
    Generate a report of all accounts with their account_type status.

    Args:
        company: Company name

    Returns:
        dict: Report data
    """
    report = {
        "company": company,
        "total_accounts": 0,
        "leaf_accounts": 0,
        "group_accounts": 0,
        "invalid_leaf_types": [],
        "accounts_with_types": [],
        "accounts_without_types": [],
    }

    all_accounts = frappe.db.get_all(
        "Account",
        filters={"company": company},
        fields=[
            "name",
            "account_name",
            "account_number",
            "account_type",
            "root_type",
            "is_group",
            "parent_account",
        ],
        order_by="account_number",
    )

    report["total_accounts"] = len(all_accounts)

    for acc in all_accounts:
        if acc.is_group:
            report["group_accounts"] += 1
        else:
            report["leaf_accounts"] += 1

            # Check for invalid types on leaf accounts
            if acc.account_type in GROUP_ONLY_ACCOUNT_TYPES:
                report["invalid_leaf_types"].append(
                    {
                        "account": acc.name,
                        "account_number": acc.account_number,
                        "account_name": acc.account_name,
                        "invalid_type": acc.account_type,
                        "root_type": acc.root_type,
                    }
                )

            # Categorize by whether they have a type
            if acc.account_type:
                report["accounts_with_types"].append(
                    {
                        "account": acc.name,
                        "account_number": acc.account_number,
                        "type": acc.account_type,
                        "root_type": acc.root_type,
                    }
                )
            else:
                report["accounts_without_types"].append(
                    {
                        "account": acc.name,
                        "account_number": acc.account_number,
                        "root_type": acc.root_type,
                    }
                )

    return report
