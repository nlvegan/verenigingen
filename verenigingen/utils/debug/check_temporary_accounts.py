#!/usr/bin/env python3
"""
Check existing temporary accounts in the system for opening balance fixes
"""

import frappe


@frappe.whitelist()
def check_existing_temporary_accounts():
    """Check what temporary accounts already exist in the system"""

    try:
        # Get company name
        company = frappe.get_single("E-Boekhouden Settings").default_company
        result = {
            "company": company,
            "temporary_accounts": [],
            "target_account_exists": False,
            "retained_earnings_exists": False,
            "equity_accounts": [],
        }

        # Check for existing temporary accounts
        temp_accounts = frappe.db.sql(
            """
            SELECT name, account_name, account_type, root_type, parent_account
            FROM `tabAccount`
            WHERE account_type = 'Temporary'
            AND company = %s
            ORDER BY name
        """,
            company,
            as_dict=True,
        )

        result["temporary_accounts"] = temp_accounts

        # Check if the problematic account already exists
        target_account = f"Temporary Differences - {company}"
        result["target_account"] = target_account
        result["target_account_exists"] = bool(frappe.db.exists("Account", target_account))

        # Check for Retained Earnings account
        retained_earnings = f"Retained Earnings - {company}"
        result["retained_earnings"] = retained_earnings
        result["retained_earnings_exists"] = bool(frappe.db.exists("Account", retained_earnings))

        # Check equity parent accounts
        equity_accounts = frappe.db.sql(
            """
            SELECT name, account_name, is_group
            FROM `tabAccount`
            WHERE company = %s
            AND root_type = 'Equity'
            AND is_group = 1
            ORDER BY name
        """,
            company,
            as_dict=True,
        )

        result["equity_accounts"] = equity_accounts

        return result

    except Exception as e:
        import traceback

        return {"error": str(e), "traceback": traceback.format_exc()}
