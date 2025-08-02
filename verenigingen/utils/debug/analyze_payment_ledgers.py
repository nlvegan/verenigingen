#!/usr/bin/env python3
"""
Analyze the ledger IDs in payment mutations to understand account mapping
"""

import frappe


@frappe.whitelist()
def analyze_payment_ledgers():
    """Analyze the ledger mappings for payment mutation 6724"""

    try:
        # Get the mutation data
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()
        mutation = iterator.fetch_mutation_detail(6724)

        if not mutation:
            return {"success": False, "error": "Could not fetch mutation"}

        result = {
            "mutation_summary": {
                "id": mutation.get("id"),
                "type": mutation.get("type"),
                "description": mutation.get("description"),
                "main_ledger_id": mutation.get("ledgerId"),  # This is the "bank" side
                "relation_id": mutation.get("relationId"),
                "rows": mutation.get("rows", []),
            },
            "ledger_mappings": {},
        }

        # Check mapping for main ledger (should be bank account)
        main_ledger = mutation.get("ledgerId")
        if main_ledger:
            mapping = frappe.db.get_value(
                "E-Boekhouden Ledger Mapping",
                {"ledger_id": main_ledger},
                ["ledger_code", "ledger_name", "erpnext_account"],
                as_dict=True,
            )
            result["ledger_mappings"]["main_ledger"] = {"ledger_id": main_ledger, "mapping": mapping}

        # Check mappings for row ledgers (should be receivable/payable accounts)
        for i, row in enumerate(mutation.get("rows", [])):
            row_ledger = row.get("ledgerId")
            if row_ledger:
                mapping = frappe.db.get_value(
                    "E-Boekhouden Ledger Mapping",
                    {"ledger_id": row_ledger},
                    ["ledger_code", "ledger_name", "erpnext_account"],
                    as_dict=True,
                )
                result["ledger_mappings"][f"row_{i}_ledger"] = {
                    "ledger_id": row_ledger,
                    "row_data": row,
                    "mapping": mapping,
                }

        # Note relation ID for reference
        relation_id = mutation.get("relationId")
        if relation_id:
            result["customer_info"] = {
                "relation_id": relation_id,
                "note": "Customer lookup skipped due to field name uncertainty",
            }

        return {"success": True, "analysis": result}

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
