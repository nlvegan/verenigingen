#!/usr/bin/env python3
"""
Trigger re-import of mutation 1345 by clearing cache and running import
"""

import frappe


@frappe.whitelist()
def trigger_mutation_1345_reimport():
    """Clear cache for mutation 1345 and trigger re-import"""
    try:
        # Step 1: Delete cache entry for mutation 1345
        if frappe.db.exists("EBoekhouden REST Mutation Cache", "1345"):
            frappe.delete_doc("EBoekhouden REST Mutation Cache", "1345")
            frappe.db.commit()

        # Step 2: Import just this mutation using the test function
        from verenigingen.utils.eboekhouden_rest_full_migration import test_single_mutation

        result = test_single_mutation(mutation_id=1345)

        return {
            "success": True,
            "cache_cleared": True,
            "import_result": result,
            "message": "Mutation 1345 cache cleared and re-import triggered",
        }

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
