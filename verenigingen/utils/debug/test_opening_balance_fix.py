#!/usr/bin/env python3
"""
Test the opening balance fix to verify it works correctly
"""

import frappe


@frappe.whitelist()
def test_temporary_account_fix():
    """Test the new _get_or_create_temporary_diff_account function"""

    try:
        # Import the function
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
            _get_or_create_temporary_diff_account,
        )

        # Get company name
        company = frappe.get_single("E-Boekhouden Settings").default_company
        debug_info = []

        # Test the function
        result_account = _get_or_create_temporary_diff_account(company, debug_info)

        # Check if the account exists and get details
        if frappe.db.exists("Account", result_account):
            account_details = frappe.db.get_value(
                "Account",
                result_account,
                ["name", "account_name", "account_type", "root_type", "parent_account"],
                as_dict=True,
            )
        else:
            account_details = None

        return {
            "success": True,
            "company": company,
            "result_account": result_account,
            "account_details": account_details,
            "debug_info": debug_info,
            "account_exists": bool(frappe.db.exists("Account", result_account)),
        }

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
