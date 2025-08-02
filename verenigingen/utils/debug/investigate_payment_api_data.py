#!/usr/bin/env python3
"""
Investigate what data the REST API actually provides for payment types 3/4
"""

import frappe


@frappe.whitelist()
def investigate_payment_api_structure():
    """Get actual payment mutation data from eBoekhouden API to see what fields are available"""

    try:
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()

        # Get a few type 3 and type 4 mutations
        result = {
            "type_3_payments": [],
            "type_4_payments": [],
            "fields_analysis": {"type_3_fields": set(), "type_4_fields": set(), "common_fields": set()},
        }

        # Fetch some type 3 (customer payment) mutations
        type_3_mutations = iterator.fetch_mutations_by_type(3, limit=5)
        for mutation in type_3_mutations[:3]:  # Take first 3 for analysis
            result["type_3_payments"].append(mutation)
            result["fields_analysis"]["type_3_fields"].update(mutation.keys())

        # Fetch some type 4 (supplier payment) mutations
        type_4_mutations = iterator.fetch_mutations_by_type(4, limit=5)
        for mutation in type_4_mutations[:3]:  # Take first 3 for analysis
            result["type_4_payments"].append(mutation)
            result["fields_analysis"]["type_4_fields"].update(mutation.keys())

        # Find common fields
        if result["fields_analysis"]["type_3_fields"] and result["fields_analysis"]["type_4_fields"]:
            result["fields_analysis"]["common_fields"] = result["fields_analysis"][
                "type_3_fields"
            ].intersection(result["fields_analysis"]["type_4_fields"])

        # Convert sets to lists for JSON serialization
        for key in result["fields_analysis"]:
            result["fields_analysis"][key] = list(result["fields_analysis"][key])

        return {"success": True, "result": result}

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
