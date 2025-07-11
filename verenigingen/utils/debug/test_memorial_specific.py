#!/usr/bin/env python3
"""
Test specific memorial bookings to see detailed error information
"""

import json

import frappe


@frappe.whitelist()
def test_memorial_specific():
    """Test specific memorial bookings with detailed error reporting"""
    try:
        from verenigingen.utils.eboekhouden_api import EBoekhoudenAPI
        from verenigingen.utils.eboekhouden_rest_full_migration import _import_rest_mutations_batch

        api = EBoekhoudenAPI()

        # Test mutations 506, 507, and 1345 specifically
        test_mutation_ids = [506, 507, 1345]
        results = {}

        for mutation_id in test_mutation_ids:
            try:
                # Fetch the mutation
                mutation_result = api.make_request("v1/mutation/{mutation_id}")

                if not mutation_result or not mutation_result.get("success"):
                    results[str(mutation_id)] = {"success": False, "error": "Failed to fetch from API"}
                    continue

                mutation_data = json.loads(mutation_result.get("data", "{}"))

                # Try to process this single mutation
                settings = frappe.get_single("E-Boekhouden Settings")

                batch_result = _import_rest_mutations_batch(
                    "Test Memorial {mutation_id}", [mutation_data], settings
                )

                results[str(mutation_id)] = {
                    "success": True,
                    "mutation_data": mutation_data,
                    "batch_result": batch_result,
                }

            except Exception as e:
                results[str(mutation_id)] = {
                    "success": False,
                    "error": str(e),
                    "mutation_data": mutation_data if "mutation_data" in locals() else None,
                }

        return {
            "success": True,
            "test_results": results,
            "message": "Detailed memorial booking test completed",
        }

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
