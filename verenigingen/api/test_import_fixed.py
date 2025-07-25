"""
Test that the amount field fix works in the full import process
"""

import frappe


@frappe.whitelist()
def test_amount_field_fix():
    """Test that mutations are no longer incorrectly detected as zero-amount"""
    try:
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import should_skip_mutation
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()

        # Test specific problematic mutations that were reported
        test_mutations = [4160, 4143, 5545]
        results = []

        for mutation_id in test_mutations:
            # Fetch using the corrected iterator method (simulate what happens in real import)
            mutations_list = iterator.fetch_mutations_by_type(mutation_type=1, limit=10)

            # Find our specific mutation in the results
            target_mutation = None
            for mut in mutations_list:
                if mut.get("id") == mutation_id:
                    target_mutation = mut
                    break

            if target_mutation:
                debug_info = []
                is_skipped = should_skip_mutation(target_mutation, debug_info)

                results.append(
                    {
                        "mutation_id": mutation_id,
                        "amount": target_mutation.get("amount"),
                        "amount_type": str(type(target_mutation.get("amount"))),
                        "is_skipped": is_skipped,
                        "debug_info": debug_info,
                        "has_rows": len(target_mutation.get("rows", [])),
                        "status": "FIXED"
                        if not is_skipped and target_mutation.get("amount") not in [None, 0.0]
                        else "STILL_BROKEN",
                    }
                )
            else:
                results.append({"mutation_id": mutation_id, "status": "NOT_FOUND_IN_TYPE_1_BATCH"})

        return {
            "success": True,
            "test_results": results,
            "summary": f"Tested {len(test_mutations)} mutations",
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}
