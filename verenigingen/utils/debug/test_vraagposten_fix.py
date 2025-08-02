#!/usr/bin/env python3
"""
Test the Vraagposten fix to see what accounts will be used
"""

import frappe


@frappe.whitelist()
def test_party_account_fix():
    """Test the new get_party_account function"""

    try:
        # Import the function
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import get_party_account

        # Get company name
        company = frappe.get_single("E-Boekhouden Settings").default_company

        # Test with a customer that uses Vraagposten fallback
        test_customer = "Belastingdienst"  # From the problematic payment

        result_account = get_party_account(test_customer, "Customer", company)

        # Get all receivable accounts to understand what's available
        receivable_accounts = frappe.db.sql(
            """
            SELECT name, account_name, account_type, root_type
            FROM `tabAccount`
            WHERE account_type = 'Receivable'
            AND company = %s
            AND is_group = 0
            ORDER BY account_name
        """,
            company,
            as_dict=True,
        )

        # Check company defaults
        company_defaults = frappe.db.get_value(
            "Company", company, ["default_receivable_account", "default_payable_account"], as_dict=True
        )

        return {
            "success": True,
            "company": company,
            "test_customer": test_customer,
            "result_account": result_account,
            "receivable_accounts": receivable_accounts,
            "company_defaults": company_defaults,
        }

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
