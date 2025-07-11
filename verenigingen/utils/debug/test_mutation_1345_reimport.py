#!/usr/bin/env python3
"""
Test re-import of mutation 1345 with fixed logic
"""

import json

import frappe


@frappe.whitelist()
def test_mutation_1345_reimport():
    """Test re-import of mutation 1345 to see if the fix works"""
    try:
        from verenigingen.utils.eboekhouden_api import EBoekhoudenAPI
        from verenigingen.utils.eboekhouden_rest_full_migration import process_mutation

        api = EBoekhoudenAPI()

        # Fetch the mutation data
        mutation_result = api.make_request("v1/mutation/1345")

        if not mutation_result or not mutation_result.get("success"):
            return {"success": False, "error": "Failed to fetch mutation 1345 from API"}

        mutation_data = json.loads(mutation_result.get("data", "{}"))

        # Process the mutation using the fixed code
        try:
            result = process_mutation(mutation_data, "Ned Ver Vegan")
            return {
                "success": True,
                "result": result,
                "message": "Mutation 1345 processed successfully with fixed logic",
            }
        except Exception as processing_error:
            return {
                "success": False,
                "processing_error": str(processing_error),
                "mutation_data": mutation_data,
                "message": "Processing failed - this exposes the real issue!",
            }

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
