#!/usr/bin/env python3
"""
Fix the "Verrekeningen" account (9999) to be Equity instead of Bank/Asset
"""

import frappe


@frappe.whitelist()
def fix_verrekeningen_account():
    """Fix the Verrekeningen account to be Equity"""

    # Find the account by its full name
    account_name = "9999 - Verrekeningen - NVV"

    account = frappe.db.get_value(
        "Account", account_name, ["name", "account_type", "root_type", "parent_account"], as_dict=True
    )

    if not account:
        print(f"Account {account_name} not found")
        return {"success": False, "error": "Account not found"}

    print(f"Found account: {account.name}")
    print(f"Current type: {account.account_type}")
    print(f"Current root: {account.root_type}")
    print(f"Current parent: {account.parent_account}")

    # Find Equity parent
    equity_parent = frappe.db.get_value(
        "Account", {"account_name": "Equity", "company": "Ned Ver Vegan"}, "name"
    )

    if not equity_parent:
        # Look for any equity group account
        equity_parent = frappe.db.get_value(
            "Account", {"root_type": "Equity", "company": "Ned Ver Vegan", "is_group": 1}, "name"
        )

    if not equity_parent:
        print("❌ Could not find Equity parent account")
        return {"success": False, "error": "No Equity parent found"}

    print(f"Found Equity parent: {equity_parent}")

    # Update the account
    account_doc = frappe.get_doc("Account", account.name)
    account_doc.account_type = "Equity"
    account_doc.root_type = "Equity"
    account_doc.parent_account = equity_parent
    account_doc.save(ignore_permissions=True)

    print(f"✅ Fixed account {account.name}:")
    print(f"   New type: {account_doc.account_type}")
    print(f"   New root: {account_doc.root_type}")
    print(f"   New parent: {account_doc.parent_account}")

    return {"success": True, "account": account_doc.name}


@frappe.whitelist()
def update_opening_balance_to_use_verrekeningen():
    """Update the opening balance logic to use the correct account name"""

    file_path = (
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/eboekhouden_rest_full_migration.py"
    )

    with open(file_path, "r") as f:
        content = f.read()

    # Find and replace the account lookup
    old_lookup = """            # Find or create account 9999 for balancing
            balancing_account = frappe.db.get_value("Account",
                {"account_name": "9999", "company": company, "is_group": 0},
                "name")"""

    new_lookup = """            # Find or create account 9999 for balancing
            balancing_account = frappe.db.get_value("Account",
                {"account_name": "Verrekeningen", "company": company, "is_group": 0},
                "name")"""

    content = content.replace(old_lookup, new_lookup)

    # Also update the account creation to use "Verrekeningen" name
    old_creation = """                if parent_account:
                    balancing_account = frappe.new_doc("Account")
                    balancing_account.account_name = "9999"
                    balancing_account.company = company
                    balancing_account.root_type = "Equity"
                    balancing_account.account_type = "Equity"
                    balancing_account.is_group = 0
                    balancing_account.parent_account = parent_account
                    balancing_account.save(ignore_permissions=True)
                    balancing_account = balancing_account.name
                    local_debug.append(f"Created balancing account 9999 (Equity): {balancing_account}")"""

    new_creation = """                if parent_account:
                    balancing_account = frappe.new_doc("Account")
                    balancing_account.account_name = "Verrekeningen"
                    balancing_account.company = company
                    balancing_account.root_type = "Equity"
                    balancing_account.account_type = "Equity"
                    balancing_account.is_group = 0
                    balancing_account.parent_account = parent_account
                    balancing_account.save(ignore_permissions=True)
                    balancing_account = balancing_account.name
                    local_debug.append(f"Created balancing account Verrekeningen (Equity): {balancing_account}")"""

    content = content.replace(old_creation, new_creation)

    # Write back the updated content
    with open(file_path, "w") as f:
        f.write(content)

    print("✅ Updated opening balance logic to use Verrekeningen account")
    return {"success": True}


if __name__ == "__main__":
    print("Fix Verrekeningen account")
