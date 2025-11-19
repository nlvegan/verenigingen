#!/usr/bin/env python3
"""
Script to create Period Closing Vouchers for 2019-2024

Created: 2025-08-05
Purpose: Create Period Closing Vouchers to properly close P&L accounts and fix cumulative balance issue
"""

from datetime import datetime

import frappe


@frappe.whitelist()
def create_period_closing_vouchers():
    """Create Period Closing Vouchers for years 2019-2024"""

    company = "Ned Ver Vegan"
    results = []

    # Use the accounts specified by user:
    # P&L closing: 99998 - Eindresultaat - NVV
    # Balance sheet: 05000 - Vrij besteedbaar eigen vermogen - NVV
    closing_account = "05000 - Vrij besteedbaar eigen vermogen - NVV"

    results.append("=== Using Closing Accounts ===")
    results.append("P&L Account: 99998 - Eindresultaat - NVV")
    results.append(f"Equity Account: {closing_account}")

    # Create Period Closing Vouchers for each year
    years = [2018, 2019, 2020, 2021, 2022, 2023, 2024]

    for year in years:
        results.append(f"\n=== Creating Period Closing Voucher for {year} ===")

        # Check if one already exists
        existing = frappe.db.get_value(
            "Period Closing Voucher", {"company": company, "fiscal_year": str(year)}, "name"
        )

        if existing:
            results.append(f"Period Closing Voucher already exists for {year}: {existing}")
            continue

        try:
            # Create Period Closing Voucher
            pcv = frappe.new_doc("Period Closing Voucher")
            pcv.company = company
            pcv.fiscal_year = str(year)
            pcv.posting_date = f"{year}-12-31"
            pcv.period_start_date = f"{year}-01-01"
            pcv.period_end_date = f"{year}-12-31"
            pcv.closing_account_head = closing_account
            pcv.remarks = (
                f"Year-end closing for fiscal year {year} - Created to fix cumulative P&L presentation"
            )

            # Set cost center if available
            cost_centers = frappe.db.get_list(
                "Cost Center", filters={"company": company, "is_group": 0}, fields=["name"], limit=1
            )
            if cost_centers:
                pcv.cost_center = cost_centers[0].name

            results.append(f"Created Period Closing Voucher document for {year}")
            results.append(f"  Fiscal Year: {pcv.fiscal_year}")
            results.append(f"  Posting Date: {pcv.posting_date}")
            results.append(f"  Closing Account: {pcv.closing_account_head}")

            # Save the document
            pcv.save()
            results.append(f"Saved Period Closing Voucher: {pcv.name}")

            # Submit the document
            pcv.submit()
            results.append(f"Submitted Period Closing Voucher: {pcv.name}")

        except Exception as e:
            results.append(f"ERROR creating Period Closing Voucher for {year}: {str(e)}")
            import traceback

            results.append(traceback.format_exc())

    results.append("\n=== Period Closing Voucher Creation Complete ===")
    return "\n".join(results)


@frappe.whitelist()
def check_p_and_l_impact():
    """Check the impact on P&L accounts after creating Period Closing Vouchers"""

    company = "Ned Ver Vegan"
    results = []

    results.append("\n=== Checking P&L Account Balances ===")

    # Get Income and Expense account balances
    p_and_l_accounts = frappe.db.sql(
        """
        SELECT
            acc.name,
            acc.account_name,
            acc.account_type,
            COALESCE(SUM(gle.debit - gle.credit), 0) as balance
        FROM `tabAccount` acc
        LEFT JOIN `tabGL Entry` gle ON gle.account = acc.name
            AND gle.company = %s
            AND gle.is_cancelled = 0
        WHERE acc.company = %s
        AND acc.account_type IN ('Income', 'Expense', 'Cost of Goods Sold')
        AND acc.is_group = 0
        GROUP BY acc.name
        HAVING ABS(balance) > 0.01
        ORDER BY acc.account_type, acc.name
    """,
        (company, company),
        as_dict=True,
    )

    total_income = 0
    total_expense = 0

    for acc in p_and_l_accounts:
        balance = acc.balance
        if acc.account_type == "Income":
            total_income += balance
        else:
            total_expense += balance

        results.append(f"  {acc.name}: {balance:,.2f} ({acc.account_type})")

    net_profit_loss = total_income - total_expense
    results.append(f"\nNet Profit/Loss: {net_profit_loss:,.2f}")
    results.append(f"Total Income: {total_income:,.2f}")
    results.append(f"Total Expense: {total_expense:,.2f}")

    return "\n".join(results)
