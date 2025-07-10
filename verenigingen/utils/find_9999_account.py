#!/usr/bin/env python3
"""
Find account 9999 wherever it might be
"""

import frappe


@frappe.whitelist()
def find_9999_account():
    """Find account 9999 in any form"""

    # Search for any account with 9999 in the name
    accounts = frappe.db.sql(
        """
        SELECT
            name,
            account_name,
            account_type,
            root_type,
            parent_account,
            is_group
        FROM `tabAccount`
        WHERE company = 'Ned Ver Vegan'
        AND (account_name LIKE '%9999%' OR name LIKE '%9999%')
    """,
        as_dict=True,
    )

    print(f"Found {len(accounts)} accounts with 9999:")

    for account in accounts:
        print(f"\n📋 Account: {account.name}")
        print(f"   Account Name: {account.account_name}")
        print(f"   Account Type: {account.account_type}")
        print(f"   Root Type: {account.root_type}")
        print(f"   Parent Account: {account.parent_account}")
        print(f"   Is Group: {account.is_group}")

        # Check if it's under Assets (Activa)
        if "Activa" in account.parent_account or "Asset" in account.root_type:
            print("   ❌ This account is under Assets - needs to be moved to Equity!")

    return {"accounts": accounts}


@frappe.whitelist()
def fix_9999_under_assets():
    """Fix account 9999 if it's under Assets"""

    # Find the account
    account = frappe.db.get_value(
        "Account",
        {"account_name": "9999", "company": "Ned Ver Vegan"},
        ["name", "account_type", "root_type", "parent_account"],
        as_dict=True,
    )

    if not account:
        print("Account 9999 not found")
        return {"success": False, "error": "Account not found"}

    print(f"Found account 9999: {account.name}")
    print(f"Current type: {account.account_type}, Root: {account.root_type}")
    print(f"Current parent: {account.parent_account}")

    # Check if it needs fixing
    if account.root_type != "Equity":
        print("❌ Account 9999 is not Equity - fixing...")

        # Find Equity parent
        equity_parent = frappe.db.get_value(
            "Account", {"account_name": "Equity", "company": "Ned Ver Vegan"}, "name"
        )

        if not equity_parent:
            # Look for any equity group account
            equity_parent = frappe.db.get_value(
                "Account", {"root_type": "Equity", "company": "Ned Ver Vegan", "is_group": 1}, "name"
            )

        if equity_parent:
            # Update the account
            account_doc = frappe.get_doc("Account", account.name)
            account_doc.account_type = "Equity"
            account_doc.root_type = "Equity"
            account_doc.parent_account = equity_parent
            account_doc.save(ignore_permissions=True)

            print("✅ Fixed account 9999:")
            print(f"   New type: {account_doc.account_type}")
            print(f"   New root: {account_doc.root_type}")
            print(f"   New parent: {account_doc.parent_account}")

            return {"success": True, "account": account_doc.name}
        else:
            print("❌ Could not find Equity parent account")
            return {"success": False, "error": "No Equity parent found"}
    else:
        print("✅ Account 9999 is already Equity")
        return {"success": True, "account": account.name}


if __name__ == "__main__":
    print("Find and fix account 9999")
