#!/usr/bin/env python3
"""
Check and fix account 9999 to ensure it's properly configured as Equity
"""

import frappe


@frappe.whitelist()
def check_9999_account():
    """Check current account 9999 details"""

    account = frappe.db.get_value(
        "Account",
        {"account_name": "9999", "company": "Ned Ver Vegan"},
        ["name", "account_type", "root_type", "parent_account"],
        as_dict=True,
    )

    if account:
        print(f"Found account 9999: {account.name}")
        print(f"Account Type: {account.account_type}")
        print(f"Root Type: {account.root_type}")
        print(f"Parent Account: {account.parent_account}")

        if account.account_type == "Bank" or account.root_type != "Equity":
            print("❌ Account 9999 has wrong type!")
            return {"needs_fix": True, "account": account}
        else:
            print("✅ Account 9999 is correctly configured")
            return {"needs_fix": False, "account": account}
    else:
        print("Account 9999 not found")
        return {"needs_fix": False, "account": None}


@frappe.whitelist()
def fix_9999_account():
    """Fix account 9999 to be properly configured as Equity"""

    # Check if account exists
    account_name = frappe.db.get_value(
        "Account", {"account_name": "9999", "company": "Ned Ver Vegan"}, "name"
    )

    if account_name:
        print(f"Updating existing account: {account_name}")

        # Get the equity parent account
        equity_parent = frappe.db.get_value(
            "Account", {"account_name": "Equity", "company": "Ned Ver Vegan"}, "name"
        )

        if not equity_parent:
            equity_parent = frappe.db.get_value(
                "Account", {"root_type": "Equity", "company": "Ned Ver Vegan", "is_group": 1}, "name"
            )

        if equity_parent:
            # Update the account
            account = frappe.get_doc("Account", account_name)
            account.account_type = "Equity"
            account.root_type = "Equity"
            account.parent_account = equity_parent
            account.save(ignore_permissions=True)

            print("✅ Updated account 9999:")
            print(f"   Account Type: {account.account_type}")
            print(f"   Root Type: {account.root_type}")
            print(f"   Parent Account: {account.parent_account}")

            return {"success": True, "account": account.name}
        else:
            print("❌ Could not find Equity parent account")
            return {"success": False, "error": "No Equity parent found"}
    else:
        print("Account 9999 not found - will be created properly on next import")
        return {"success": True, "account": None}


@frappe.whitelist()
def delete_and_recreate_9999():
    """Delete account 9999 and let it be recreated properly"""

    account_name = frappe.db.get_value(
        "Account", {"account_name": "9999", "company": "Ned Ver Vegan"}, "name"
    )

    if account_name:
        try:
            frappe.delete_doc("Account", account_name, force=True)
            print(f"✅ Deleted account {account_name}")
            print("It will be recreated properly as Equity on next import")
            return {"success": True}
        except Exception as e:
            print(f"❌ Could not delete account: {str(e)}")
            return {"success": False, "error": str(e)}
    else:
        print("Account 9999 not found")
        return {"success": True}


if __name__ == "__main__":
    print("Check and fix account 9999")
