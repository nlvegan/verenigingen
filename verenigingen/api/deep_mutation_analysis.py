"""
Deep analysis of mutation processing to find where stock account is being used
"""

import frappe


@frappe.whitelist()
def trace_journal_entry_creation():
    """Trace exactly where the stock account gets involved in journal entry creation"""
    try:
        # Take one of the failing mutations and trace every step
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()
        mutation = iterator.fetch_mutation_detail(1256)

        if not mutation:
            return {"success": False, "error": "Could not fetch mutation 1256"}

        # Let's analyze the mutation step by step
        analysis = {
            "mutation": {
                "id": mutation.get("id"),
                "type": mutation.get("type"),
                "date": mutation.get("date"),
                "description": mutation.get("description"),
                "amount": mutation.get("amount"),
                "main_ledger_id": mutation.get("ledgerId"),
            },
            "rows_analysis": [],
        }

        settings = frappe.get_single("E-Boekhouden Settings")
        company = settings.default_company

        # Analyze each row to see what accounts they map to
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import get_account_for_ledger

        for i, row in enumerate(mutation.get("rows", [])):
            ledger_id = row.get("ledgerId")
            debug_info = []
            account = get_account_for_ledger(ledger_id, company, debug_info)

            account_type = None
            if account:
                account_type = frappe.db.get_value("Account", account, "account_type")

            analysis["rows_analysis"].append(
                {
                    "row_index": i,
                    "ledger_id": ledger_id,
                    "amount": row.get("amount"),
                    "description": row.get("description"),
                    "mapped_account": account,
                    "account_type": account_type,
                    "debug_info": debug_info,
                    "is_problematic": account_type == "Stock",
                }
            )

        # Also check what the main ledger maps to
        main_debug_info = []
        main_account = get_account_for_ledger(mutation.get("ledgerId"), company, main_debug_info)
        main_account_type = None
        if main_account:
            main_account_type = frappe.db.get_value("Account", main_account, "account_type")

        analysis["main_ledger_analysis"] = {
            "ledger_id": mutation.get("ledgerId"),
            "mapped_account": main_account,
            "account_type": main_account_type,
            "debug_info": main_debug_info,
            "is_problematic": main_account_type == "Stock",
        }

        return {
            "success": True,
            "analysis": analysis,
            "finding": "This shows exactly which ledger is mapping to the stock account",
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def check_main_ledger_13201869():
    """Check what ledger 13201869 (main ledger for these mutations) maps to"""
    try:
        ledger_id = 13201869  # Main ledger from the failing mutations

        # Check the mapping
        mapping = frappe.db.get_value(
            "E-Boekhouden Ledger Mapping",
            {"ledger_id": str(ledger_id)},
            ["erpnext_account", "ledger_name", "ledger_code"],
            as_dict=True,
        )

        account_type = None
        if mapping and mapping.erpnext_account:
            account_type = frappe.db.get_value("Account", mapping.erpnext_account, "account_type")

        return {
            "success": True,
            "ledger_id": ledger_id,
            "mapping": mapping,
            "account_type": account_type,
            "is_this_the_problem": account_type == "Stock",
            "explanation": "This is the main ledger for type 5 (Money Received) mutations that are failing",
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
