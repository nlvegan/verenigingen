#!/usr/bin/env python3
"""
Investigate P&L account discrepancy between ERPNext and eBoekhouden
"""

import frappe
from frappe.utils import flt


@frappe.whitelist()
def investigate_pl_discrepancy():
    """Investigate why P&L totals are over a million vs eBoekhouden's 122k"""

    print("INVESTIGATING P&L ACCOUNT DISCREPANCY")
    print("=" * 60)

    # Get P&L accounts from Chart of Accounts
    pl_accounts = frappe.db.sql(
        """
        SELECT
            name,
            account_name,
            account_type,
            root_type,
            account_number,
            eboekhouden_grootboek_nummer
        FROM `tabAccount`
        WHERE company = 'Ned Ver Vegan'
        AND root_type IN ('Income', 'Expense')
        AND is_group = 0
        ORDER BY account_number
    """,
        as_dict=True,
    )

    print(f"Found {len(pl_accounts)} P&L accounts")

    # Calculate totals for each P&L account
    total_income = 0
    total_expense = 0

    print("\nP&L ACCOUNT BALANCES:")
    print("-" * 80)

    for account in pl_accounts:
        # Get account balance from GL entries
        balance = frappe.db.sql(
            """
            SELECT
                SUM(debit - credit) as balance,
                COUNT(*) as entry_count
            FROM `tabGL Entry`
            WHERE account = %s
            AND company = 'Ned Ver Vegan'
            AND is_cancelled = 0
        """,
            account.name,
            as_dict=True,
        )[0]

        account_balance = flt(balance.balance or 0)
        # entry_count = balance.entry_count or 0

        # For P&L accounts, reverse the sign (credit balance = positive for income/expense)
        if account.root_type == "Income":
            display_balance = -account_balance  # Income accounts have credit balances
            total_income += display_balance
        else:
            display_balance = account_balance  # Expense accounts have debit balances
            total_expense += display_balance

        if abs(display_balance) > 1000:  # Only show accounts with significant balances
            print(f"{account.account_number or 'N/A'} - {account.account_name}: " f"€{display_balance:,.2f}")

    print("-" * 80)
    print(f"TOTAL INCOME: €{total_income:,.2f}")
    print(f"TOTAL EXPENSE: €{total_expense:,.2f}")
    print(f"NET RESULT: €{total_income - total_expense:,.2f}")

    # Check for potential issues
    print("\n" + "=" * 60)
    print("POTENTIAL ISSUES ANALYSIS:")
    print("=" * 60)

    # 1. Check for duplicate entries
    print("\n1. CHECKING FOR DUPLICATE ENTRIES:")
    duplicates = frappe.db.sql(
        """
        SELECT
            voucher_type,
            voucher_no,
            account,
            COUNT(*) as count,
            SUM(debit - credit) as total_impact
        FROM `tabGL Entry`
        WHERE company = 'Ned Ver Vegan'
        AND is_cancelled = 0
        GROUP BY voucher_type, voucher_no, account
        HAVING COUNT(*) > 1
        ORDER BY COUNT(*) DESC
        LIMIT 10
    """,
        as_dict=True,
    )

    if duplicates:
        print("Found duplicate GL entries:")
        for dup in duplicates:
            print(
                "  {dup.voucher_type} {dup.voucher_no} - {dup.account}: {dup.count} entries, €{dup.total_impact:,.2f}"
            )
    else:
        print("No duplicate GL entries found")

    # 2. Check for massive single transactions
    print("\n2. CHECKING FOR UNUSUALLY LARGE TRANSACTIONS:")
    large_transactions = frappe.db.sql(
        """
        SELECT
            voucher_type,
            voucher_no,
            account,
            posting_date,
            debit,
            credit,
            ABS(debit - credit) as amount
        FROM `tabGL Entry`
        WHERE company = 'Ned Ver Vegan'
        AND is_cancelled = 0
        AND ABS(debit - credit) > 50000
        ORDER BY ABS(debit - credit) DESC
        LIMIT 10
    """,
        as_dict=True,
    )

    if large_transactions:
        print("Found large transactions:")
        for trans in large_transactions:
            print(
                "  {trans.posting_date} - {trans.voucher_type} {trans.voucher_no}: "
                "€{trans.amount:,.2f} ({trans.account})"
            )
    else:
        print("No unusually large transactions found")

    # 3. Check for eBoekhouden vs ERPNext transaction counts
    print("\n3. CHECKING TRANSACTION COUNTS:")

    # Count eBoekhouden transactions
    eb_count = frappe.db.sql(
        """
        SELECT COUNT(*) as count
        FROM `tabGL Entry`
        WHERE company = 'Ned Ver Vegan'
        AND is_cancelled = 0
        AND (
            voucher_no LIKE 'EBH-%' OR
            voucher_no LIKE 'ACC-JV-%' OR
            voucher_no LIKE 'ACC-SINV-%' OR
            voucher_no LIKE 'ACC-PINV-%'
        )
    """
    )[0][0]

    # Total GL entries
    total_count = frappe.db.sql(
        """
        SELECT COUNT(*) as count
        FROM `tabGL Entry`
        WHERE company = 'Ned Ver Vegan'
        AND is_cancelled = 0
    """
    )[0][0]

    print(f"eBoekhouden-related GL entries: {eb_count:,}")
    print(f"Total GL entries: {total_count:,}")
    print(f"Non-eBoekhouden entries: {total_count - eb_count:,}")

    # 4. Check for opening balance issues
    print("\n4. CHECKING OPENING BALANCE ENTRIES:")
    opening_entries = frappe.db.sql(
        """
        SELECT
            account,
            SUM(debit - credit) as balance
        FROM `tabGL Entry`
        WHERE company = 'Ned Ver Vegan'
        AND is_cancelled = 0
        AND voucher_no LIKE 'OPB-%'
        GROUP BY account
        HAVING ABS(SUM(debit - credit)) > 10000
        ORDER BY ABS(SUM(debit - credit)) DESC
        LIMIT 10
    """,
        as_dict=True,
    )

    if opening_entries:
        print("Large opening balance entries:")
        for entry in opening_entries:
            print(f"  {entry.account}: €{entry.balance:,.2f}")
    else:
        print("No significant opening balance entries found")

    return {
        "total_income": total_income,
        "total_expense": total_expense,
        "net_result": total_income - total_expense,
        "eboekhouden_entries": eb_count,
        "total_entries": total_count,
    }


if __name__ == "__main__":
    investigate_pl_discrepancy()
