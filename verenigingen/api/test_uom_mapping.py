"""Test enhanced UOM mapping functionality"""

import frappe


@frappe.whitelist()
def test_uom_mapping():
    """Test the enhanced UOM mapping system"""

    from verenigingen.e_boekhouden.utils.uom_manager import UOMManager, map_unit_of_measure

    results = {
        "dutch_to_erpnext": [],
        "category_suggestions": [],
        "edge_cases": [],
        "summary": {"passed": 0, "failed": 0},
    }

    # Test Dutch to ERPNext mappings
    test_mappings = [
        ("stuks", "Nos"),
        ("uur", "Hour"),
        ("maand", "Month"),
        ("kg", "Kg"),
        ("m2", "Sq Meter"),
        ("procent", "Percent"),
        ("doos", "Box"),
        ("abonnement", "Subscription"),
        ("licentie", "License"),
        ("dienst", "Service"),
        ("factuur", "Invoice"),
        ("kwartaal", "Quarter"),
    ]

    for dutch, expected in test_mappings:
        actual = map_unit_of_measure(dutch)
        test_result = {"dutch": dutch, "expected": expected, "actual": actual, "passed": actual == expected}
        results["dutch_to_erpnext"].append(test_result)

        if test_result["passed"]:
            results["summary"]["passed"] += 1
        else:
            results["summary"]["failed"] += 1

    # Test category-based UOM suggestions
    category_tests = [
        ("Services", "Hour"),
        ("Products", "Unit"),
        ("Office Supplies", "Unit"),
        ("Software and Subscriptions", "License"),
        ("Travel and Expenses", "Trip"),
        ("Marketing and Advertising", "Service"),
        ("Utilities and Infrastructure", "Month"),
        ("Financial Services", "Service"),
    ]

    for category, expected_uom in category_tests:
        suggested = UOMManager.get_uom_for_category(category)
        results["category_suggestions"].append(
            {
                "category": category,
                "suggested_uom": suggested,
                "expected": expected_uom,
                "correct": suggested == expected_uom,
            }
        )

    # Test edge cases
    edge_tests = [
        ("", "Nos"),  # Empty string
        (None, "Nos"),  # None
        ("unknown_unit", "Nos"),  # Unknown unit
        ("STUKS", "Nos"),  # Uppercase
        ("  uur  ", "Hour"),  # With spaces
        ("st.", "Nos"),  # With period
    ]

    for test_input, expected in edge_tests:
        actual = map_unit_of_measure(test_input)
        results["edge_cases"].append(
            {"input": test_input, "expected": expected, "actual": actual, "passed": actual == expected}
        )

    results["summary"]["total"] = len(test_mappings)

    # Test UOM existence check
    results["uom_check"] = {
        "subscription_exists": frappe.db.exists("UOM", "Subscription"),
        "license_exists": frappe.db.exists("UOM", "License"),
        "quarter_exists": frappe.db.exists("UOM", "Quarter"),
    }

    return results


@frappe.whitelist()
def setup_dutch_uoms():
    """Setup all Dutch UOMs and conversions"""
    from verenigingen.e_boekhouden.utils.uom_manager import setup_dutch_uoms as setup

    return setup()
