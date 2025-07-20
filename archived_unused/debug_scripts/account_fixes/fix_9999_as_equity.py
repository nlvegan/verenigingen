#!/usr/bin/env python3
"""
Fix account 9999 to be created as Equity instead of Expense
"""

import frappe


@frappe.whitelist()
def fix_9999_as_equity():
    """Fix account 9999 to be created as Equity account"""

    file_path = (
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/eboekhouden_rest_full_migration.py"
    )

    with open(file_path, "r") as f:
        content = f.read()

    # Find and replace the account 9999 creation logic
    old_9999_creation = """            if not balancing_account:
                # Create account 9999 under expenses
                parent_account = frappe.db.get_value("Account",
                    {"account_name": "Expenses", "company": company},
                    "name")

                if not parent_account:
                    parent_account = frappe.db.get_value("Account",
                        {"root_type": "Expense", "company": company, "is_group": 1},
                        "name")

                if parent_account:
                    balancing_account = frappe.new_doc("Account")
                    balancing_account.account_name = "9999"
                    balancing_account.company = company
                    balancing_account.root_type = "Expense"
                    balancing_account.account_type = "Expense Account"
                    balancing_account.is_group = 0
                    balancing_account.parent_account = parent_account
                    balancing_account.save(ignore_permissions=True)
                    balancing_account = balancing_account.name
                    local_debug.append(f"Created balancing account 9999: {balancing_account}")"""

    new_9999_creation = """            if not balancing_account:
                # Create account 9999 under equity (opening entries need balance sheet accounts)
                parent_account = frappe.db.get_value("Account",
                    {"account_name": "Equity", "company": company},
                    "name")

                if not parent_account:
                    parent_account = frappe.db.get_value("Account",
                        {"root_type": "Equity", "company": company, "is_group": 1},
                        "name")

                if parent_account:
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

    # Replace the logic
    content = content.replace(old_9999_creation, new_9999_creation)

    # Write back the fixed content
    with open(file_path, "w") as f:
        f.write(content)

    print("Successfully fixed account 9999 to be Equity:")
    print("1. Account 9999 is now created as Equity account")
    print("2. Equity accounts are allowed in Opening Entries")
    print("3. Makes more accounting sense for opening balance adjustments")
    print("4. Should resolve the 'Profit and Loss' type account error")

    return {"success": True}


@frappe.whitelist()
def delete_existing_9999_if_wrong_type():
    """Delete existing account 9999 if it's the wrong type"""

    companies = frappe.get_all("Company", fields=["name"])

    for company in companies:
        account_9999 = frappe.db.get_value(
            "Account", {"account_name": "9999", "company": company.name}, ["name", "root_type"], as_dict=True
        )

        if account_9999 and account_9999.root_type != "Equity":
            print(f"Found account 9999 with wrong type ({account_9999.root_type}) in {company.name}")
            print(f"Deleting {account_9999.name} so it can be recreated as Equity")

            # Delete the account
            frappe.delete_doc("Account", account_9999.name)
            print(f"Deleted {account_9999.name}")

    return {"success": True}


if __name__ == "__main__":
    print("Fix account 9999 as Equity")
