"""
Test if eBoekhouden REST API supports date filtering for mutations
"""

import frappe


@frappe.whitelist()
def test_api_date_filtering():
    """Test if the mutations API supports dateFrom/dateTo parameters"""
    try:
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()

        # Test 1: Get recent mutations without date filter (should return most recent ~500)
        mutations_no_filter = iterator.fetch_mutations_by_type(mutation_type=1, limit=10)

        # Test 2: Get mutations with very restrictive date filter (should return fewer or different results)
        mutations_with_filter = iterator.fetch_mutations_by_type(
            mutation_type=1, limit=10, date_from="2020-01-01", date_to="2020-12-31"
        )

        # Extract mutation IDs for comparison
        ids_no_filter = [m.get("id") for m in mutations_no_filter] if mutations_no_filter else []
        ids_with_filter = [m.get("id") for m in mutations_with_filter] if mutations_with_filter else []

        return {
            "success": True,
            "test_results": {
                "no_filter": {
                    "count": len(mutations_no_filter) if mutations_no_filter else 0,
                    "first_5_ids": ids_no_filter[:5],
                    "date_range": [
                        mutations_no_filter[0].get("date") if mutations_no_filter else None,
                        mutations_no_filter[-1].get("date") if mutations_no_filter else None,
                    ],
                },
                "with_2020_filter": {
                    "count": len(mutations_with_filter) if mutations_with_filter else 0,
                    "first_5_ids": ids_with_filter[:5],
                    "date_range": [
                        mutations_with_filter[0].get("date") if mutations_with_filter else None,
                        mutations_with_filter[-1].get("date") if mutations_with_filter else None,
                    ],
                },
            },
            "api_supports_date_filtering": len(ids_with_filter) != len(ids_no_filter)
            or set(ids_with_filter) != set(ids_no_filter),
            "analysis": "If the API supports date filtering, the results should be different between filtered and unfiltered requests",
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}
