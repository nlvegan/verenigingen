"""
Simple test to check mutation IDs returned by API
"""

import frappe

# Import security framework
from verenigingen.utils.security.api_security_framework import OperationType, standard_api


@standard_api(operation_type=OperationType.REPORTING)
@frappe.whitelist()
def test_mutation_1363_date():
    """Check what date mutation 1363 has"""
    try:
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()

        # Get type 1 mutations and find 1363
        mutations = iterator.fetch_mutations_by_type(mutation_type=1)

        mutation_1363 = None
        early_mutation_dates = []

        for mutation in mutations:
            if mutation.get("id") == 1363:
                mutation_1363 = mutation
            elif mutation.get("id", 0) < 100:  # Early mutations
                early_mutation_dates.append({"id": mutation.get("id"), "date": mutation.get("date")})

        return {
            "success": True,
            "mutation_1363": {
                "id": mutation_1363.get("id") if mutation_1363 else None,
                "date": mutation_1363.get("date") if mutation_1363 else None,
                "description": mutation_1363.get("description", "")[:50] if mutation_1363 else None,
            },
            "early_mutations_sample": early_mutation_dates[:10],
            "today_date": "2025-07-25",
            "analysis": "Compare mutation 1363 date with early mutation dates to find pattern",
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@standard_api(operation_type=OperationType.REPORTING)
@frappe.whitelist()
def test_early_mutations_in_api():
    """Test if early mutations (17-100) are returned by the API"""
    try:
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()

        # Get type 1 mutations - should include early ones
        mutations = iterator.fetch_mutations_by_type(mutation_type=1, limit=100)

        if mutations:
            # Check if we get early mutation IDs
            early_mutations = [m for m in mutations if m.get("id", 0) < 100]
            mid_mutations = [m for m in mutations if 1360 <= m.get("id", 0) <= 1370]

            return {
                "success": True,
                "total_fetched": len(mutations),
                "early_mutations_found": len(early_mutations),
                "early_mutation_ids": [m.get("id") for m in early_mutations],
                "mutations_around_1363": len(mid_mutations),
                "mid_mutation_ids": [m.get("id") for m in mid_mutations],
                "first_10_ids": [m.get("id") for m in mutations[:10]],
                "analysis": "Check if API returns early mutations vs only later ones",
            }
        else:
            return {"success": True, "message": "No mutations returned"}

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@standard_api(operation_type=OperationType.REPORTING)
@frappe.whitelist()
def test_opening_balances_exist():
    """Test if type 0 (opening balances) mutations exist in the API"""
    try:
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()

        # Test for type 0 (opening balances)
        mutations = iterator.fetch_mutations_by_type(mutation_type=0, limit=10)

        if mutations:
            return {
                "success": True,
                "opening_balances_found": len(mutations),
                "first_5_mutations": [
                    {
                        "id": m.get("id"),
                        "date": m.get("date"),
                        "description": m.get("description", "")[:50],
                        "amount": m.get("amount"),
                    }
                    for m in mutations[:5]
                ],
                "analysis": f"Found {len(mutations)} opening balance mutations",
            }
        else:
            return {
                "success": True,
                "opening_balances_found": 0,
                "message": "No opening balance mutations found - this explains why no summary log is created",
            }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@standard_api(operation_type=OperationType.REPORTING)
@frappe.whitelist()
def test_iterator_all_mutations():
    """Test how many mutations the iterator fetches by default"""
    try:
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()

        # Test with default parameters - should fetch ALL mutations
        mutations = iterator.fetch_mutations_by_type(mutation_type=1)

        if mutations:
            mutation_ids = [m.get("id") for m in mutations if m.get("id")]

            return {
                "success": True,
                "total_mutations_fetched": len(mutations),
                "id_range": {
                    "min_id": min(mutation_ids) if mutation_ids else None,
                    "max_id": max(mutation_ids) if mutation_ids else None,
                    "first_10_ids": sorted(mutation_ids)[:10],
                    "last_10_ids": sorted(mutation_ids)[-10:]
                    if len(mutation_ids) >= 10
                    else sorted(mutation_ids),
                },
                "analysis": f"Iterator fetched {len(mutations)} total mutations. If >500, it's working correctly.",
            }
        else:
            return {"success": True, "total_mutations_fetched": 0, "message": "No mutations returned"}

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@standard_api(operation_type=OperationType.REPORTING)
@frappe.whitelist()
def check_api_mutation_order():
    """Check what mutation IDs the API returns and in what order"""
    try:
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()

        # Get first 20 mutations of type 1 (Sales Invoice)
        mutations = iterator.fetch_mutations_by_type(mutation_type=1, limit=20)

        if mutations:
            mutation_info = []
            for mutation in mutations:
                mutation_info.append(
                    {
                        "id": mutation.get("id"),
                        "date": mutation.get("date"),
                        "description": mutation.get("description", "")[:50],
                    }
                )

            return {
                "success": True,
                "total_mutations_returned": len(mutations),
                "mutation_details": mutation_info,
                "id_range": {
                    "first_id": mutations[0].get("id"),
                    "last_id": mutations[-1].get("id"),
                    "are_sequential": all(
                        mutations[i].get("id", 0) <= mutations[i + 1].get("id", 0)
                        for i in range(len(mutations) - 1)
                    ),
                },
                "analysis": "Shows the order and IDs of mutations returned by the API",
            }
        else:
            return {"success": True, "total_mutations_returned": 0, "message": "No mutations returned"}

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}
