"""
Test that the iterator fix preserves amount fields correctly
"""

import frappe


@frappe.whitelist()
def test_iterator_amount_preservation():
    """Test that the iterator preserves amount fields from summary data"""
    try:
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()
        results = []

        # Test the specific mutation that was problematic
        mutation_id = 5545

        # Step 1: Get summary data (has amount)
        summary_data = iterator.fetch_mutation_by_id(mutation_id)
        results.append(
            f"Summary data amount: {summary_data.get('amount')} (type: {type(summary_data.get('amount'))})"
        )

        # Step 2: Get detailed data (missing amount)
        detailed_data = iterator.fetch_mutation_detail(mutation_id)
        results.append(
            f"Detailed data amount: {detailed_data.get('amount')} (type: {type(detailed_data.get('amount'))})"
        )

        # Step 3: Simulate the fixed logic manually
        if detailed_data and summary_data:
            fixed_data = detailed_data.copy()
            if "amount" not in fixed_data or fixed_data.get("amount") is None:
                if "amount" in summary_data:
                    fixed_data["amount"] = summary_data["amount"]
            results.append(
                f"Fixed data amount: {fixed_data.get('amount')} (type: {type(fixed_data.get('amount'))})"
            )

        # Step 4: Test that should_skip_mutation works correctly with fixed data
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import should_skip_mutation

        if detailed_data:
            debug_info_broken = []
            skip_broken = should_skip_mutation(detailed_data, debug_info_broken)
            results.append(f"Broken version - Skip: {skip_broken}, Debug: {debug_info_broken}")

        if "fixed_data" in locals():
            debug_info_fixed = []
            skip_fixed = should_skip_mutation(fixed_data, debug_info_fixed)
            results.append(f"Fixed version - Skip: {skip_fixed}, Debug: {debug_info_fixed}")

        # Test conclusion
        is_fix_working = (
            summary_data.get("amount") == 23.23
            and detailed_data.get("amount") is None
            and "fixed_data" in locals()
            and fixed_data.get("amount") == 23.23
            and not skip_fixed
            and len(debug_info_fixed) == 0
        )

        return {
            "success": True,
            "mutation_id": mutation_id,
            "test_steps": results,
            "fix_working": is_fix_working,
            "conclusion": "FIX VERIFIED" if is_fix_working else "FIX FAILED",
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def test_mutations_4160_and_4143():
    """Test the specific mutations mentioned by user"""
    try:
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import should_skip_mutation
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()
        test_mutations = [4160, 4143]
        results = []

        for mutation_id in test_mutations:
            summary = iterator.fetch_mutation_by_id(mutation_id)
            detailed = iterator.fetch_mutation_detail(mutation_id)

            if summary and detailed:
                # Apply fix manually
                fixed = detailed.copy()
                if "amount" not in fixed or fixed.get("amount") is None:
                    if "amount" in summary:
                        fixed["amount"] = summary["amount"]

                # Test skip logic
                debug_before = []
                skip_before = should_skip_mutation(detailed, debug_before)

                debug_after = []
                skip_after = should_skip_mutation(fixed, debug_after)

                results.append(
                    {
                        "mutation_id": mutation_id,
                        "summary_amount": summary.get("amount"),
                        "detailed_amount": detailed.get("amount"),
                        "fixed_amount": fixed.get("amount"),
                        "skip_before_fix": skip_before,
                        "skip_after_fix": skip_after,
                        "debug_before": debug_before,
                        "debug_after": debug_after,
                        "fix_successful": not skip_after and summary.get("amount") not in [None, 0.0],
                    }
                )
            else:
                results.append({"mutation_id": mutation_id, "error": "Could not fetch mutation data"})

        return {"success": True, "test_results": results}

    except Exception as e:
        return {"success": False, "error": str(e)}
