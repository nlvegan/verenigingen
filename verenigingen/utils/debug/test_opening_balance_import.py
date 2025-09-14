#!/usr/bin/env python3
"""
Test opening balance import after the temporary account fix
"""

import frappe

from verenigingen.utils.security.api_security_framework import OperationType, development_only_api


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def test_opening_balance_import():
    """Test opening balance import with the fixed temporary account function"""

    try:
        # Import the function
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import _import_opening_balances

        # Get company details
        company = frappe.get_single("E-Boekhouden Settings").default_company
        cost_center = frappe.db.get_value("Company", company, "cost_center")
        debug_info = []

        # Run opening balance import in dry run mode first
        result = _import_opening_balances(company, cost_center, debug_info, dry_run=True)

        return {
            "success": True,
            "company": company,
            "cost_center": cost_center,
            "import_result": result,
            "debug_info": debug_info,
        }

    except Exception as e:
        import traceback

        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
            "debug_info": debug_info if "debug_info" in locals() else [],
        }
