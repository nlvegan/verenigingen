#!/usr/bin/env python3
"""
Check existing accounts to find the closing accounts used by E-Boekhouden
"""

import frappe


@frappe.whitelist()
def check_existing_accounts():
    """Find accounts that could be used for Period Closing Vouchers"""

    company = "Nederlandse Vereniging voor Veganisme"
    results = []

    # Look for all types of accounts that might be used for closing
    results.append("=== Searching for Potential Closing Accounts ===")

    # Check for various account types and names that might be used
    potential_accounts = frappe.db.sql(
        """
        SELECT
            name,
            account_name,
            account_type,
            is_group,
            eboekhouden_ledger_code
        FROM `tabAccount`
        WHERE company = %s
        AND (
            account_type IN ('Equity', 'Capital Stock', 'Retained Earnings')
            OR account_name LIKE '%%eigen%%vermogen%%'
            OR account_name LIKE '%%resultaat%%'
            OR account_name LIKE '%%winst%%'
            OR account_name LIKE '%%verlies%%'
            OR account_name LIKE '%%reserve%%'
            OR account_name LIKE '%%retained%%'
            OR account_name LIKE '%%surplus%%'
        )
        ORDER BY account_type, name
    """,
        (company,),
        as_dict=True,
    )

    results.append(f"\nFound {len(potential_accounts)} potential closing accounts:")
    for acc in potential_accounts:
        group_indicator = " (GROUP)" if acc.is_group else ""
        ebh_code = f" [EBH: {acc.eboekhouden_ledger_code}]" if acc.eboekhouden_ledger_code else ""
        results.append(f"  {acc.name} - {acc.account_name}{group_indicator}{ebh_code}")
        results.append(f"    Type: {acc.account_type}")

    # Also check Journal Entries for year-end closing patterns
    results.append("\n=== Checking for Year-End Closing Journal Entries ===")

    closing_entries = frappe.db.sql(
        """
        SELECT DISTINCT
            je.name,
            je.posting_date,
            je.user_remark,
            jea.account
        FROM `tabJournal Entry` je
        JOIN `tabJournal Entry Account` jea ON jea.parent = je.name
        WHERE je.company = %s
        AND je.posting_date LIKE '%%-12-31'
        AND (
            je.user_remark LIKE '%%closing%%'
            OR je.user_remark LIKE '%%afsluiting%%'
            OR je.user_remark LIKE '%%resultaat%%'
            OR je.user_remark LIKE '%%jaar%%'
        )
        ORDER BY je.posting_date DESC
        LIMIT 10
    """,
        (company,),
        as_dict=True,
    )

    if closing_entries:
        results.append(f"\nFound {len(closing_entries)} potential year-end closing entries:")
        for entry in closing_entries:
            results.append(f"  {entry.name} - {entry.posting_date}")
            results.append(f"    Remark: {entry.user_remark[:100] if entry.user_remark else 'No remark'}")
            results.append(f"    Account: {entry.account}")

    return "\n".join(results)
