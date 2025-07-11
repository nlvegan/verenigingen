#!/usr/bin/env python3
"""
Fix opening balance to use account 9999 for temporary balancing
"""

import frappe


@frappe.whitelist()
def fix_balancing_to_9999():
    """Fix the opening balance to use account 9999 for balancing"""

    file_path = (
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/eboekhouden_rest_full_migration.py"
    )

    with open(file_path, "r") as f:
        content = f.read()

    # Find and replace the complex equity account logic with simple 9999 account
    old_balancing_logic = """        if abs(balance_diff) > 0.01:  # If difference is significant
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

    new_balancing_logic = """        if abs(balance_diff) > 0.01:  # If difference is significant
            # Use account 9999 for temporary balancing
            balancing_account = frappe.db.get_value("Account",
                {"account_name": "9999", "company": company, "is_group": 0},
                "name")

            if not balancing_account:
                # Find a parent account for 9999 (use any expense account parent)
                parent_account = frappe.db.get_value("Account",
                    {"account_name": "Expenses", "company": company},
                    "name")

                if not parent_account:
                    parent_account = frappe.db.get_value("Account",
                        {"root_type": "Expense", "company": company, "is_group": 1},
                        "name")

                if parent_account:
                    # Create account 9999
                    balancing_account = frappe.new_doc("Account")
                    balancing_account.account_name = "9999"
                    balancing_account.company = company
                    balancing_account.root_type = "Expense"
                    balancing_account.account_type = "Expense Account"
                    balancing_account.is_group = 0
                    balancing_account.parent_account = parent_account
                    balancing_account.save(ignore_permissions=True)
                    balancing_account = balancing_account.name
                    debug_info.append(f"Created balancing account 9999: {balancing_account}")

            if balancing_account:
                # Add balancing entry
                balancing_entry = {
                    "account": balancing_account,
                    "debit_in_account_currency": flt(abs(balance_diff), 2) if balance_diff < 0 else 0,
                    "credit_in_account_currency": flt(abs(balance_diff), 2) if balance_diff > 0 else 0,
                    "cost_center": cost_center,
                    "user_remark": "Opening balance temporary balancing entry - review manually"
                }
                je.append("accounts", balancing_entry)
                debug_info.append(f"Added balancing entry: {abs(balance_diff):.2f} to account 9999")
                debug_info.append(f"⚠️  MANUAL REVIEW NEEDED: Account 9999 has {abs(balance_diff):.2f} balance from opening entries")
            else:
                debug_info.append("ERROR: Could not create account 9999 for balancing")"""

    # Replace the logic
    content = content.replace(old_balancing_logic, new_balancing_logic)

    # Write back the corrected content
    with open(file_path, "w") as f:
        f.write(content)

    print("Successfully changed balancing to use account 9999:")
    print("1. Uses account 9999 for temporary balancing")
    print("2. Creates account 9999 if it doesn't exist")
    print("3. Clearly marks entries as needing manual review")
    print("4. Much simpler than complex equity account logic")

    return {"success": True}


@frappe.whitelist()
def analyze_opening_balance_totals():
    """Analyze why opening balances don't net to zero"""

    print("Analyzing opening balance totals...")

    # Get opening balance entries from eBoekhouden
    import requests

    from verenigingen.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

    iterator = EBoekhoudenRESTIterator()
    url = "{iterator.base_url}/v1/mutation"
    params = {"type": 0}
    response = requests.get(url, headers=iterator._get_headers(), params=params, timeout=30)

    if response.status_code == 200:
        data = response.json()
        entries = data.get("items", [])

        total_amount = 0
        receivable_total = 0
        payable_total = 0
        other_total = 0

        print(f"\nFound {len(entries)} opening balance entries:")
        print("=" * 70)

        for entry in entries:
            amount = frappe.utils.flt(entry.get("amount", 0), 2)
            ledger_id = entry.get("ledgerId")

            if amount == 0:
                continue

            total_amount += amount

            # Get account mapping
            mapping = frappe.db.get_value(
                "E-Boekhouden Ledger Mapping", {"ledger_id": ledger_id}, "erpnext_account"
            )

            if mapping:
                account_type = frappe.db.get_value("Account", mapping, "account_type")

                if account_type == "Receivable":
                    receivable_total += amount
                    category = "RECEIVABLE"
                elif account_type == "Payable":
                    payable_total += amount
                    category = "PAYABLE"
                else:
                    other_total += amount
                    category = "OTHER"
            else:
                other_total += amount
                category = "UNMAPPED"

            print(f"{category:>10} | Ledger {ledger_id:>5} | {amount:>10.2f} | {mapping or 'Not mapped'}")

        print("=" * 70)
        print(f"{'TOTALS':>10} | {'':>5} | {total_amount:>10.2f} |")
        print(f"Receivable: {receivable_total:>10.2f}")
        print(f"Payable:    {payable_total:>10.2f}")
        print(f"Other:      {other_total:>10.2f}")
        print(f"Grand Total: {total_amount:>9.2f}")

        if abs(total_amount) > 0.01:
            print(f"\n⚠️  IMBALANCE DETECTED: Total is {total_amount:.2f}, not zero!")
            print("This explains why the journal entry needs balancing.")
        else:
            print(f"\n✅ BALANCED: Total is {total_amount:.2f} (essentially zero)")

    return {"success": True}


if __name__ == "__main__":
    print("Fix balancing to use account 9999")
