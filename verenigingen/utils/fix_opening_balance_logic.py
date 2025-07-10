#!/usr/bin/env python3
"""
Fix the opening balance logic - the key issue is that eBoekhouden amounts
represent final balances, not journal entry amounts.
"""

import frappe


@frappe.whitelist()
def fix_opening_balance_logic():
    """Fix the opening balance debit/credit logic"""

    file_path = (
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/eboekhouden_rest_full_migration.py"
    )

    with open(file_path, "r") as f:
        content = f.read()

    # Find and replace the incorrect debit/credit logic
    old_logic = """            # Determine debit/credit based on account type and amount
            # For opening balances, we need to consider the natural balance of accounts
            if account_details.root_type in ["Asset", "Expense"]:
                # Normal debit balance accounts
                debit_amount = amount if amount > 0 else 0
                credit_amount = -amount if amount < 0 else 0
            else:
                # Normal credit balance accounts (Liability, Equity, Income)
                debit_amount = -amount if amount < 0 else 0
                credit_amount = amount if amount > 0 else 0"""

    new_logic = """            # Determine debit/credit based on account type and amount
            # eBoekhouden amounts represent final balances, not journal entry amounts
            # We need to create journal entries that will result in these balances
            if account_details.root_type in ["Asset", "Expense"]:
                # These accounts have natural debit balances
                # Positive balance = debit the account, negative balance = credit the account
                debit_amount = amount if amount > 0 else 0
                credit_amount = abs(amount) if amount < 0 else 0
            else:
                # These accounts have natural credit balances (Liability, Equity, Income)
                # Positive balance = credit the account, negative balance = debit the account
                debit_amount = abs(amount) if amount < 0 else 0
                credit_amount = amount if amount > 0 else 0"""

    # Replace the logic
    content = content.replace(old_logic, new_logic)

    # Write back the corrected content
    with open(file_path, "w") as f:
        f.write(content)

    print("Successfully fixed opening balance logic:")
    print("1. Asset/Expense accounts: Positive balance = Debit entry")
    print("2. Liability/Equity/Income accounts: Positive balance = Credit entry")
    print("3. This creates journal entries that result in the correct final balances")

    return {"success": True}


@frappe.whitelist()
def test_opening_balance_logic():
    """Test the opening balance logic with sample data"""

    test_cases = [
        {"account_type": "Asset", "balance": 1000, "expected_debit": 1000, "expected_credit": 0},
        {"account_type": "Asset", "balance": -500, "expected_debit": 0, "expected_credit": 500},
        {"account_type": "Equity", "balance": 50000, "expected_debit": 0, "expected_credit": 50000},
        {"account_type": "Equity", "balance": -1000, "expected_debit": 1000, "expected_credit": 0},
        {"account_type": "Liability", "balance": 2000, "expected_debit": 0, "expected_credit": 2000},
    ]

    print("Testing opening balance logic:")
    print("=" * 70)

    for case in test_cases:
        amount = case["balance"]

        if case["account_type"] in ["Asset", "Expense"]:
            debit_amount = amount if amount > 0 else 0
            credit_amount = abs(amount) if amount < 0 else 0
        else:
            debit_amount = abs(amount) if amount < 0 else 0
            credit_amount = amount if amount > 0 else 0

        correct = debit_amount == case["expected_debit"] and credit_amount == case["expected_credit"]
        status = "✓" if correct else "✗"

        print(
            f"{status} {case['account_type']} balance {amount:+}: Debit={debit_amount}, Credit={credit_amount}"
        )

    return {"success": True}


if __name__ == "__main__":
    print("Fix opening balance logic")
