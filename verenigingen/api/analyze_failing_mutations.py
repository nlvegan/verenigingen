"""
Analyze the specific failing mutations to see what they are in eBoekhouden
"""

import frappe


@frappe.whitelist()
def analyze_failing_stock_mutations():
    """Analyze the specific mutations that failed due to stock accounts"""
    try:
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        # These are the mutations that failed
        failing_mutations = [1256, 4549, 5570, 5577, 6338]

        iterator = EBoekhoudenRESTIterator()
        results = []

        for mutation_id in failing_mutations:
            # Get the full mutation data
            mutation = iterator.fetch_mutation_detail(mutation_id)

            if mutation:
                # Analyze each row to understand the mapping
                row_analysis = []
                for i, row in enumerate(mutation.get("rows", [])):
                    ledger_id = row.get("ledgerId")

                    # Look up the ledger mapping
                    mapping = frappe.db.get_value(
                        "E-Boekhouden Ledger Mapping",
                        {"ledger_id": str(ledger_id)},
                        ["erpnext_account", "ledger_name", "ledger_code"],
                        as_dict=True,
                    )

                    account_type = None
                    if mapping and mapping.erpnext_account:
                        account_type = frappe.db.get_value("Account", mapping.erpnext_account, "account_type")

                    row_analysis.append(
                        {
                            "row_index": i,
                            "ebh_ledger_id": ledger_id,
                            "ebh_ledger_code": mapping.ledger_code if mapping else None,
                            "ebh_ledger_name": mapping.ledger_name if mapping else None,
                            "erpnext_account": mapping.erpnext_account if mapping else None,
                            "account_type": account_type,
                            "amount": row.get("amount"),
                            "description": row.get("description", "")[:100],
                            "is_problematic": account_type == "Stock",
                        }
                    )

                mutation_analysis = {
                    "mutation_id": mutation_id,
                    "type": mutation.get("type"),
                    "date": mutation.get("date"),
                    "description": mutation.get("description", "")[:150],
                    "total_amount": mutation.get("amount"),
                    "main_ledger_id": mutation.get("ledgerId"),
                    "rows": row_analysis,
                    "has_stock_accounts": any(row["is_problematic"] for row in row_analysis),
                }

                results.append(mutation_analysis)
            else:
                results.append({"mutation_id": mutation_id, "error": "Could not fetch mutation data"})

        return {
            "success": True,
            "failing_mutations": results,
            "summary": f"Analyzed {len(failing_mutations)} failing mutations",
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def check_stock_ledger_usage():
    """Check how the stock ledger (30000) is being used across all mutation types"""
    try:
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()

        # Check different mutation types for stock account usage
        results = {}
        stock_ledger_id = 13201884  # This maps to the stock account

        for mutation_type in [1, 2, 3, 4, 5, 6, 7]:
            mutations = iterator.fetch_mutations_by_type(mutation_type=mutation_type, limit=100)

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
                    "type_name": {
                        1: "Sales Invoice",
                        2: "Purchase Invoice",
                        3: "Customer Payment",
                        4: "Supplier Payment",
                        5: "Money Received",
                        6: "Money Paid",
                        7: "Memorial",
                    }[mutation_type],
                    "stock_mutations_found": len(stock_usage),
                    "examples": stock_usage[:5],  # First 5 examples
                }

        return {
            "success": True,
            "stock_ledger_id": stock_ledger_id,
            "usage_by_type": results,
            "business_question": "Which mutation types legitimately use stock accounts and which are mapping errors?",
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def suggest_stock_account_solution():
    """Suggest solutions for handling stock account mutations"""
    try:
        # First, understand the mapping situation
        stock_account = "30000 - Voorraden - NVV"

        # Find all ledgers mapped to this stock account
        stock_mappings = frappe.get_all(
            "E-Boekhouden Ledger Mapping",
            filters={"erpnext_account": stock_account},
            fields=["ledger_id", "ledger_name", "ledger_code"],
            limit=20,
        )

        return {
            "success": True,
            "analysis": {
                "stock_account": stock_account,
                "ledgers_mapped_to_stock": stock_mappings,
                "problem": "Some eBoekhouden ledgers are mapped to stock accounts but appear in Journal Entry mutations",
                "solutions": [
                    {
                        "option": "Remap ledgers",
                        "description": "Change the mapping of problematic ledgers from stock accounts to appropriate expense/income accounts",
                        "pros": "Clean solution, fixes root cause",
                        "cons": "May affect other transactions",
                    },
                    {
                        "option": "Skip stock mutations",
                        "description": "Continue skipping mutations that involve stock accounts with clear logging",
                        "pros": "Safe, no data corruption",
                        "cons": "Some transactions not imported",
                    },
                    {
                        "option": "Create Stock Entries",
                        "description": "Convert stock-related mutations to Stock Entry documents instead of Journal Entries",
                        "pros": "All transactions imported",
                        "cons": "Complex logic, may not be appropriate for all cases",
                    },
                ],
            },
            "recommendation": "Option 1 (Remap ledgers) is likely best if these are mapping errors",
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
