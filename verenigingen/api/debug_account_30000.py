"""
Debug account 30000 issue
"""

import frappe


@frappe.whitelist()
def check_account_30000():
    """Check what account 30000 is and why it's causing issues"""
    try:
        # Check account details
        account = frappe.db.get_value(
            "Account",
            {"account_number": "30000"},
            ["name", "account_type", "account_name", "is_group"],
            as_dict=True,
        )

        if not account:
            # Maybe it's stored differently
            account = frappe.db.get_value(
                "Account",
                {"name": ["like", "%30000%"]},
                ["name", "account_type", "account_name", "is_group", "eboekhouden_grootboek_nummer"],
                as_dict=True,
            )

        # Also check the exact account name from the error
        exact_account = frappe.db.get_value(
            "Account",
            {"name": "30000 - Voorraden - NVV"},
            ["name", "account_type", "account_name", "is_group"],
            as_dict=True,
        )

        return {
            "success": True,
            "account_30000": account,
            "exact_account": exact_account,
            "is_stock_account": exact_account.get("account_type") == "Stock" if exact_account else None,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def check_ledger_mapping():
    """Check how ledger 13201963 is mapped"""
    try:
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import get_account_for_ledger

        # The failing mutation uses ledgerId 13201963
        ledger_id = 13201963
        settings = frappe.get_single("E-Boekhouden Settings")
        company = settings.default_company

        debug_info = []
        account = get_account_for_ledger(ledger_id, company, debug_info)

        return {"success": True, "ledger_id": ledger_id, "mapped_account": account, "debug_info": debug_info}

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def suggest_stock_transaction_handling():
    """Suggest how to handle stock account mutations"""
    try:
        # Check if there are any stock accounts being used in type 5/6 mutations
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()

        # Get a few type 5 mutations to analyze
        mutations = iterator.fetch_mutations_by_type(mutation_type=5, limit=10)

        stock_related_mutations = []
        for mutation in mutations:
            for row in mutation.get("rows", []):
                ledger_id = row.get("ledgerId")
                if ledger_id:
                    # Check if this ledger maps to a stock account
                    from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
                        get_account_for_ledger,
                    )

                    settings = frappe.get_single("E-Boekhouden Settings")
                    company = settings.default_company
                    debug_info = []
                    account = get_account_for_ledger(ledger_id, company, debug_info)

                    if account:
                        account_type = frappe.db.get_value("Account", account, "account_type")
                        if account_type == "Stock":
                            stock_related_mutations.append(
                                {
                                    "mutation_id": mutation.get("id"),
                                    "ledger_id": ledger_id,
                                    "account": account,
                                    "amount": row.get("amount"),
                                    "description": row.get("description", "")[:50],
                                }
                            )

        return {
            "success": True,
            "total_mutations_checked": len(mutations),
            "stock_related_count": len(stock_related_mutations),
            "stock_mutations": stock_related_mutations,
            "recommendation": "These mutations should either be skipped or handled via Stock Entry instead of Journal Entry",
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}
