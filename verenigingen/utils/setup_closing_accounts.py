#!/usr/bin/env python3
"""
Setup accounts needed for Period Closing Vouchers
"""

import frappe


@frappe.whitelist()
def setup_closing_accounts():
    """Setup required closing accounts if they don't exist"""

    company = "Nederlandse Vereniging voor Veganisme"
    results = []

    # Check what accounts exist
    all_accounts = frappe.db.sql(
        """
        SELECT name, account_name, account_type, is_group
        FROM `tabAccount`
        WHERE company = %s
        ORDER BY account_type, name
    """,
        (company,),
        as_dict=True,
    )

    results.append("=== Existing Accounts ===")
    equity_accounts = []
    for acc in all_accounts:
        if "equity" in acc.account_type.lower():
            equity_accounts.append(acc)
            results.append(f"EQUITY: {acc.name} - {acc.account_name} (Group: {acc.is_group})")

    results.append(f"\nFound {len(equity_accounts)} equity accounts")

    # Look for a suitable parent equity account
    equity_parent = None
    for acc in equity_accounts:
        if acc.is_group == 1:
            equity_parent = acc.name
            results.append(f"Using equity parent: {equity_parent}")
            break

    if not equity_parent:
        results.append("ERROR: No equity parent account found. Cannot create retained earnings account.")
        return "\n".join(results)

    # Check if Retained Earnings account exists
    retained_earnings = frappe.db.get_value(
        "Account", {"company": company, "account_name": ["like", "%retained%"], "is_group": 0}, "name"
    )

    if not retained_earnings:
        # Create Retained Earnings account
        try:
            account = frappe.new_doc("Account")
            account.account_name = "Retained Earnings"
            account.parent_account = equity_parent
            account.company = company
            account.account_type = "Equity"
            account.is_group = 0
            account.save()

            retained_earnings = account.name
            results.append(f"Created Retained Earnings account: {retained_earnings}")

        except Exception as e:
            results.append(f"ERROR creating Retained Earnings account: {str(e)}")
            return "\n".join(results)
    else:
        results.append(f"Found existing Retained Earnings account: {retained_earnings}")

    return "\n".join(results)


@frappe.whitelist()
def create_period_closing_vouchers_with_account_setup():
    """Setup accounts and create Period Closing Vouchers"""

    # First setup accounts
    setup_result = setup_closing_accounts()

    # Then create Period Closing Vouchers
    from verenigingen.utils.create_period_closing_vouchers import create_period_closing_vouchers

    pcv_result = create_period_closing_vouchers()

    return setup_result + "\n\n" + pcv_result
