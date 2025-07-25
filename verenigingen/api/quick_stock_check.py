"""
Quick check of stock account usage
"""

import frappe


@frappe.whitelist()
def find_stock_account_mutations():
    """Find mutations that actually use stock accounts"""
    try:
        # The actual stock ledger ID from our mapping
        stock_ledger_id = 13201884  # ledger_code "30000"

        from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()

        # Check type 5 and 6 mutations for stock usage
        results = {}

        for mutation_type in [5, 6]:  # Money Received, Money Paid
            mutations = iterator.fetch_mutations_by_type(mutation_type=mutation_type, limit=20)

            stock_usage = []
            for mutation in mutations:
                for row in mutation.get("rows", []):
                    if row.get("ledgerId") == stock_ledger_id:
                        stock_usage.append(
                            {
                                "mutation_id": mutation.get("id"),
                                "date": mutation.get("date"),
                                "description": mutation.get("description", "")[:100],
                                "amount": row.get("amount"),
                                "row_description": row.get("description", "")[:50],
                            }
                        )

            if stock_usage:
                results[f"type_{mutation_type}"] = {
                    "type_name": "Money Received" if mutation_type == 5 else "Money Paid",
                    "stock_mutations_found": len(stock_usage),
                    "examples": stock_usage,
                }

        return {
            "success": True,
            "stock_ledger_id": stock_ledger_id,
            "stock_account": "30000 - Voorraden - NVV",
            "usage_by_type": results,
            "explanation": "These are the actual mutations that use stock accounts and cause Journal Entry failures",
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def check_why_these_5_failed():
    """Check why the specific 5 mutations failed if they don't use stock accounts"""
    try:
        failing_mutations = [1256, 4549, 5570, 5577, 6338]

        # Let's see what error they would actually produce
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import _create_journal_entry

        settings = frappe.get_single("E-Boekhouden Settings")
        company = settings.default_company
        cost_center = settings.default_cost_center

        results = []
        for mutation_id in failing_mutations:
            try:
                # Try to process this mutation and see what happens
                from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

                iterator = EBoekhoudenRESTIterator()
                mutation = iterator.fetch_mutation_detail(mutation_id)

                if mutation:
                    # Try to create journal entry
                    debug_info = []
                    result = _create_journal_entry(mutation, company, cost_center, debug_info)
                    results.append(
                        {
                            "mutation_id": mutation_id,
                            "status": "success",
                            "result": result,
                            "debug": debug_info,
                        }
                    )
                else:
                    results.append(
                        {"mutation_id": mutation_id, "status": "error", "error": "Could not fetch mutation"}
                    )

            except Exception as e:
                results.append({"mutation_id": mutation_id, "status": "error", "error": str(e)})

        return {
            "success": True,
            "test_results": results,
            "explanation": "Testing what actually happens when we try to process these mutations",
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}
