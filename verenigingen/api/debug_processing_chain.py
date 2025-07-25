"""
Debug the processing chain to see where amount gets zeroed
"""

import frappe


@frappe.whitelist()
def debug_mutation_processing_chain():
    """Debug the mutation processing chain step by step"""
    try:
        # Test with mutation 5545 which shows the pattern
        mutation_id = 5545

        result = []
        result.append(f"=== Tracing Mutation {mutation_id} Processing Chain ===")

        # Step 1: Fetch from API
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()
        api_data = iterator.fetch_mutation_by_id(mutation_id)

        result.append(f"Step 1 - API Data: {api_data}")
        if api_data:
            result.append(f"API Amount: {api_data.get('amount')} (type: {type(api_data.get('amount'))})")

        # Step 2: Test the fetch_mutation_detail function
        try:
            detailed_data = iterator.fetch_mutation_detail(mutation_id)
            result.append(f"Step 2 - Detailed Data: {detailed_data}")
            if detailed_data:
                result.append(
                    f"Detailed Amount: {detailed_data.get('amount')} (type: {type(detailed_data.get('amount'))})"
                )
                result.append(f"Detailed Rows: {len(detailed_data.get('rows', []))} rows")
                result.append(f"Detailed Line Items: {len(detailed_data.get('Regels', []))} regels")

            # Step 2b: Test the corrected version (simulate the fix)
            if detailed_data and api_data:
                corrected_data = detailed_data.copy()
                if "amount" not in corrected_data or corrected_data.get("amount") is None:
                    if "amount" in api_data:
                        corrected_data["amount"] = api_data["amount"]
                result.append(
                    f"Step 2b - Corrected Data Amount: {corrected_data.get('amount')} (type: {type(corrected_data.get('amount'))})"
                )

        except Exception as e:
            result.append(f"Step 2 - Error fetching detailed data: {str(e)}")

        # Step 3: Test should_skip_mutation with both versions
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import should_skip_mutation

        if api_data:
            debug_info1 = []
            skip1 = should_skip_mutation(api_data, debug_info1)
            result.append(f"Step 3a - should_skip_mutation(API data): {skip1}")
            result.append(f"Debug info: {debug_info1}")

        if "detailed_data" in locals() and detailed_data:
            debug_info2 = []
            skip2 = should_skip_mutation(detailed_data, debug_info2)
            result.append(f"Step 3b - should_skip_mutation(Detailed data): {skip2}")
            result.append(f"Debug info: {debug_info2}")

            # Step 3c: Test with corrected data
            if "corrected_data" in locals():
                debug_info3 = []
                skip3 = should_skip_mutation(corrected_data, debug_info3)
                result.append(f"Step 3c - should_skip_mutation(Corrected data): {skip3}")
                result.append(f"Debug info: {debug_info3}")

        # Step 4: Look for _process_single_mutation call pattern
        result.append(f"\\n=== Key Question: Which data gets passed to should_skip_mutation? ===")
        result.append(f"The log shows 'Processing single mutation 5545: type=1, amount=0.0'")
        result.append(f"But API data shows amount={api_data.get('amount') if api_data else 'N/A'}")
        result.append(f"This suggests the detailed_data fetch is returning amount=0.0")

        return {"success": True, "analysis": result}

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}
