"""
Check the actual type of opening balance mutations
"""

import frappe


@frappe.whitelist()
def check_opening_balance_type():
    """Check what type the opening balance mutations have"""

    try:
        from verenigingen.utils.eboekhouden.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()

        # Try to fetch mutation with ID 0
        mutation_0 = iterator.fetch_mutation_detail(0)

        # Also try to fetch by searching for opening balance
        all_mutations = []

        # Search through different types to find opening balance
        for mutation_type in range(0, 8):  # Check types 0-7
            try:
                mutations = iterator.fetch_mutations_by_type(mutation_type, limit=50)
                if mutations:
                    for m in mutations:
                        if m.get("id") == 0 or "opening" in str(m.get("description", "")).lower():
                            all_mutations.append(
                                {
                                    "id": m.get("id"),
                                    "type": m.get("type"),
                                    "date": m.get("date"),
                                    "description": m.get("description"),
                                    "rows_count": len(m.get("rows", [])),
                                }
                            )
            except Exception:
                pass

        # Check if mutation ID 0 is included in the normal fetch
        regular_mutations = iterator.fetch_mutations_by_type(7, limit=100)  # Try Journal Entries
        has_id_zero = False
        id_zero_mutations = []

        if regular_mutations:
            for m in regular_mutations:
                if m.get("id") == 0:
                    has_id_zero = True
                    id_zero_mutations.append(m)

        return {
            "success": True,
            "mutation_0_direct": mutation_0 is not None,
            "mutation_0_type": mutation_0.get("type") if mutation_0 else None,
            "mutation_0_details": mutation_0 if mutation_0 else None,
            "opening_mutations_found": all_mutations,
            "id_zero_in_type_7": has_id_zero,
            "id_zero_mutations": id_zero_mutations[:5],  # First 5
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}
