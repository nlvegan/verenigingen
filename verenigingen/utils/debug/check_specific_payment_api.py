#!/usr/bin/env python3
"""
Check specific payment from API to see available fields
"""

import frappe


@frappe.whitelist()
def check_payment_6724():
    """Check the specific payment mutation 6724 that caused issues"""

    try:
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()

        # Get the specific mutation that was problematic
        mutation = iterator.fetch_mutation_detail(6724)

        if mutation:
            return {
                "success": True,
                "mutation_id": 6724,
                "mutation_data": mutation,
                "available_fields": list(mutation.keys()),
                "has_ledger_id": "ledgerId" in mutation,
                "has_relation_id": "relationId" in mutation,
                "has_rows": "rows" in mutation or "Regels" in mutation,
                "ledger_id": mutation.get("ledgerId"),
                "relation_id": mutation.get("relationId"),
                "rows_count": len(mutation.get("rows", mutation.get("Regels", []))),
            }
        else:
            return {"success": False, "error": "Could not fetch mutation 6724"}

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
