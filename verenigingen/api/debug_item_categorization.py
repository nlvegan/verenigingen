"""Debug item categorization"""

import frappe


@frappe.whitelist()
def debug_categorization():
    """Debug why kantoorartikelen is being categorized as Products"""

    from verenigingen.utils.eboekhouden.field_mapping import ITEM_GROUP_KEYWORDS
    from verenigingen.utils.eboekhouden.invoice_helpers import determine_item_group

    description = "Kantoorartikelen en paperclips"
    description_lower = description.lower()

    results = {"description": description, "description_lower": description_lower, "keyword_matches": {}}

    # Check which keywords match
    for group, keywords in ITEM_GROUP_KEYWORDS.items():
        matches = []
        for keyword in keywords:
            if keyword in description_lower:
                matches.append(keyword)
        if matches:
            results["keyword_matches"][group] = matches

    # Test the function
    result = determine_item_group(description, btw_code="HOOG_VERK_21", account_code="46500", price=25.00)

    results["final_result"] = result

    # Check if artikel is matching product
    results["artikel_in_desc"] = "artikel" in description_lower
    results["product_keywords"] = ITEM_GROUP_KEYWORDS.get("product", [])[:10]  # First 10
    results["office_keywords"] = ITEM_GROUP_KEYWORDS.get("office", [])[:10]  # First 10

    return results
