#!/usr/bin/env python3
"""
Direct fix for opening balance import issues:
1. Fix temporary opening account to be a ledger account
2. Fix debit/credit balancing
3. Handle account types properly
"""

import frappe
from frappe.utils import flt


@frappe.whitelist()
def fix_opening_balance_function():
    """Fix the opening balance function directly in the migration file"""

    file_path = (
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/eboekhouden_rest_full_migration.py"
    )

    with open(file_path, "r") as f:
        content = f.read()

    # Find the _create_opening_invoices function and fix the temporary account handling
    old_temp_account_code = """        # Get temporary opening account
        temp_account = frappe.db.get_value("Account",
            {"account_name": "Temporary Opening Ledger", "company": company},
            "name")

        if not temp_account:
            temp_account = frappe.db.get_value("Account",
                {"account_name": "Temporary Opening", "company": company, "is_group": 0},
                "name")

        if not temp_account:
            # Create temporary opening account as a group account
            temp_account = frappe.new_doc("Account")
            temp_account.account_name = "Temporary Opening"
            temp_account.company = company
            temp_account.root_type = "Asset"
            temp_account.account_type = "Temporary"
            temp_account.is_group = 1  # Make it a group account
            temp_account.parent_account = frappe.db.get_value("Account",
                {"account_name": "Application of Funds (Assets)", "company": company},
                "name")
            temp_account.save(ignore_permissions=True)
            temp_account = temp_account.name
            debug_info.append(f"Created temporary opening account: {temp_account}")

            # Create a ledger account under the group
            ledger_account = frappe.new_doc("Account")
            ledger_account.account_name = "Temporary Opening Ledger"
            ledger_account.company = company
            ledger_account.root_type = "Asset"
            ledger_account.account_type = "Temporary"
            ledger_account.is_group = 0  # This is the ledger account
            ledger_account.parent_account = temp_account
            ledger_account.save(ignore_permissions=True)
            # Use the ledger account for transactions
            temp_account = ledger_account.name
            debug_info.append(f"Created temporary opening ledger account: {temp_account}")"""

    new_temp_account_code = """        # Get or create temporary opening account (ledger account)
        temp_account = frappe.db.get_value("Account",
            {"account_name": "Temporary Opening", "company": company, "is_group": 0},
            "name")

        if not temp_account:
            # Create temporary opening account as a ledger account directly
            parent_account = frappe.db.get_value("Account",
                {"account_name": "Application of Funds (Assets)", "company": company},
                "name")

            temp_account = frappe.new_doc("Account")
            temp_account.account_name = "Temporary Opening"
            temp_account.company = company
            temp_account.root_type = "Asset"
            temp_account.account_type = "Temporary"
            temp_account.is_group = 0  # Make it a ledger account directly
            temp_account.parent_account = parent_account
            temp_account.save(ignore_permissions=True)
            temp_account = temp_account.name
            debug_info.append(f"Created temporary opening ledger account: {temp_account}")"""

    # Replace the temp account code
    content = content.replace(old_temp_account_code, new_temp_account_code)

    # Fix the journal entry balancing
    old_journal_code = """        # Add journal entry lines and calculate balancing entry
        total_debit = 0
        total_credit = 0

        for entry_data in entries:
            account_details = frappe.db.get_value(
                "Account", entry_data["account"],
                ["account_name", "account_type", "root_type"],
                as_dict=True
            )

            amount = entry_data["amount"]

            # Determine debit/credit based on account type and amount
            if account_details.root_type in ["Asset", "Expense"]:
                # Normal debit balance accounts
                debit_amount = abs(amount) if amount > 0 else 0
                credit_amount = abs(amount) if amount < 0 else 0
            else:
                # Normal credit balance accounts (Liability, Equity, Income)
                debit_amount = abs(amount) if amount < 0 else 0
                credit_amount = abs(amount) if amount > 0 else 0

            entry_line = {
                "account": entry_data["account"],
                "debit_in_account_currency": debit_amount,
                "credit_in_account_currency": credit_amount,
                "cost_center": cost_center,
                "user_remark": "Opening balance - Ledger {entry_data['ledger_id']} ({account_details.account_name})"
            }

            je.append("accounts", entry_line)
            total_debit += debit_amount
            total_credit += credit_amount

        # Add balancing entry if needed
        balance_diff = total_debit - total_credit
        if abs(balance_diff) > 0.01:  # If difference is significant
            # Get retained earnings account for balancing
            retained_earnings = frappe.db.get_value("Account",
                {"account_name": "Retained Earnings", "company": company},
                "name")

            if not retained_earnings:
                # Create retained earnings account if not exists
                retained_earnings = frappe.new_doc("Account")
                retained_earnings.account_name = "Retained Earnings"
                retained_earnings.company = company
                retained_earnings.root_type = "Equity"
                retained_earnings.account_type = "Accumulated Depreciation"
                retained_earnings.parent_account = frappe.db.get_value("Account",
                    {"account_name": "Equity", "company": company},
                    "name")
                retained_earnings.save(ignore_permissions=True)
                retained_earnings = retained_earnings.name
                debug_info.append(f"Created retained earnings account: {retained_earnings}")

            # Add balancing entry
            balancing_entry = {
                "account": retained_earnings,
                "debit_in_account_currency": abs(balance_diff) if balance_diff < 0 else 0,
                "credit_in_account_currency": abs(balance_diff) if balance_diff > 0 else 0,
                "cost_center": cost_center,
                "user_remark": "Opening balance balancing entry"
            }
            je.append("accounts", balancing_entry)
            debug_info.append(f"Added balancing entry: {abs(balance_diff):.2f} to {retained_earnings}")"""

    new_journal_code = """        # Add journal entry lines with proper balancing
        total_debit = 0
        total_credit = 0

        for entry_data in entries:
            account_details = frappe.db.get_value(
                "Account", entry_data["account"],
                ["account_name", "account_type", "root_type"],
                as_dict=True
            )

            amount = flt(entry_data["amount"], 2)

            # Determine debit/credit based on account type and amount
            # For opening balances, we need to consider the natural balance of accounts
            if account_details.root_type in ["Asset", "Expense"]:
                # Normal debit balance accounts
                debit_amount = amount if amount > 0 else 0
                credit_amount = -amount if amount < 0 else 0
            else:
                # Normal credit balance accounts (Liability, Equity, Income)
                debit_amount = -amount if amount < 0 else 0
                credit_amount = amount if amount > 0 else 0

            if debit_amount > 0 or credit_amount > 0:  # Only add if there's an amount
                entry_line = {
                    "account": entry_data["account"],
                    "debit_in_account_currency": flt(debit_amount, 2),
                    "credit_in_account_currency": flt(credit_amount, 2),
                    "cost_center": cost_center,
                    "user_remark": "Opening balance - Ledger {entry_data['ledger_id']} ({account_details.account_name})"
                }

                je.append("accounts", entry_line)
                total_debit += flt(debit_amount, 2)
                total_credit += flt(credit_amount, 2)

        # Calculate and add balancing entry
        balance_diff = flt(total_debit - total_credit, 2)
        debug_info.append(f"Before balancing: Total Debit={total_debit:.2f}, Total Credit={total_credit:.2f}, Difference={balance_diff:.2f}")

        if abs(balance_diff) > 0.01:  # If difference is significant
            # Find or create an equity account for balancing
            equity_account = frappe.db.get_value("Account",
                {"account_name": "Retained Earnings", "company": company, "is_group": 0},
                "name")

            if not equity_account:
                # Look for any equity account we can use
                equity_account = frappe.db.get_value("Account",
                    {"root_type": "Equity", "company": company, "is_group": 0},
                    "name")

            if not equity_account:
                # Find the Equity parent account
                equity_parent = frappe.db.get_value("Account",
                    {"account_name": "Equity", "company": company},
                    "name")

                if equity_parent:
                    # Create a balancing account
                    equity_account = frappe.new_doc("Account")
                    equity_account.account_name = "Opening Balance Adjustment"
                    equity_account.company = company
                    equity_account.root_type = "Equity"
                    equity_account.account_type = "Equity"
                    equity_account.is_group = 0
                    equity_account.parent_account = equity_parent
                    equity_account.save(ignore_permissions=True)
                    equity_account = equity_account.name
                    debug_info.append(f"Created opening balance adjustment account: {equity_account}")

            if equity_account:
                # Add balancing entry
                balancing_entry = {
                    "account": equity_account,
                    "debit_in_account_currency": flt(abs(balance_diff), 2) if balance_diff < 0 else 0,
                    "credit_in_account_currency": flt(abs(balance_diff), 2) if balance_diff > 0 else 0,
                    "cost_center": cost_center,
                    "user_remark": "Opening balance balancing entry"
                }
                je.append("accounts", balancing_entry)
                debug_info.append(f"Added balancing entry: {abs(balance_diff):.2f} to {equity_account}")
            else:
                debug_info.append("ERROR: Could not find or create equity account for balancing")"""

    # Replace the journal code
    content = content.replace(old_journal_code, new_journal_code)

    # Write back the fixed content
    with open(file_path, "w") as f:
        f.write(content)

    print("Successfully fixed opening balance function:")
    print("1. Fixed temporary opening account to be a ledger account")
    print("2. Improved debit/credit balancing logic")
    print("3. Added proper balancing account creation")

    return {"success": True}


if __name__ == "__main__":
    print("Fix opening balance function")
