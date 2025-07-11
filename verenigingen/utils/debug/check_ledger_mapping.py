#!/usr/bin/env python3
"""
Check specific ledger mapping for debugging
"""

import frappe


@frappe.whitelist()
def check_ledger_mapping_16167827():
    """Check if mapping exists for main ledger 16167827"""
    try:
        mapping = frappe.db.sql(
            """SELECT ledger_id, erpnext_account, ledger_name
               FROM `tabE-Boekhouden Ledger Mapping`
               WHERE ledger_id = %s LIMIT 1""",
            "16167827",
            as_dict=True,
        )

        if mapping:
            return {"success": True, "mapping_found": True, "mapping": mapping[0]}
        else:
            return {
                "success": True,
                "mapping_found": False,
                "message": "No mapping found for ledger 16167827",
            }

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def trace_balancing_logic_issue():
    """Trace why balancing logic didn't use the main ledger for mutation 1345"""
    try:
        results = {}

        # Step 1: Check main ledger mapping
        main_ledger = "16167827"
        mapping = frappe.db.sql(
            """SELECT erpnext_account, ledger_name
               FROM `tabE-Boekhouden Ledger Mapping`
               WHERE ledger_id = %s
               LIMIT 1""",
            main_ledger,
        )

        if mapping:
            results["main_ledger_mapping"] = {"found": True, "account": mapping[0][0], "name": mapping[0][1]}
        else:
            results["main_ledger_mapping"] = {
                "found": False,
                "message": "No mapping found for main ledger {main_ledger}",
            }

        # Step 2: Check processed ledgers for mutation 1345
        results["row_ledgers"] = [
            {"ledger_id": "13201866", "amount": -117.24},
            {"ledger_id": "13201866", "amount": 54.71},
            {"ledger_id": "13201865", "amount": 19525.95},
        ]

        processed_ledgers = {"13201866", "13201865"}
        results["processed_ledgers"] = list(processed_ledgers)

        # Step 3: Check which ledgers would be considered unprocessed
        # unprocessed_ledgers = []
        # The main ledger 16167827 is NOT in processed_ledgers, so it should NOT be used in fallback

        # Step 4: Check if 83280 fallback exists
        income_account_83280 = frappe.db.sql(
            """SELECT erpnext_account
               FROM `tabE-Boekhouden Ledger Mapping`
               WHERE erpnext_account LIKE %s
               LIMIT 1""",
            "83280%",
        )

        if income_account_83280:
            results["fallback_83280"] = {"found": True, "account": income_account_83280[0][0]}
        else:
            results["fallback_83280"] = {"found": False}

        # Step 5: Check default income account
        default_income = frappe.db.get_value(
            "Account",
            {"company": "Ned Ver Vegan", "account_type": "Income Account", "is_group": 0},
            "name",
        )

        results["default_income_account"] = default_income

        return results

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
