"""
API endpoint to test enhanced item management
"""

import frappe


@frappe.whitelist()
def test_enhanced_item_categorization():
    """Test the enhanced item categorization logic"""

    from verenigingen.e_boekhouden.utils.invoice_helpers import determine_item_group, generate_item_code

    results = {"tests": [], "summary": {"passed": 0, "failed": 0}}

    test_cases = [
        {
            "name": "Consultancy Service",
            "description": "Consultancy diensten voor project X",
            "btw_code": "HOOG_VERK_21",
            "account_code": "41000",
            "price": 150.00,
            "expected_group": "Services",
        },
        {
            "name": "Office Supplies",
            "description": "Kantoorartikelen en paperclips",
            "btw_code": "HOOG_VERK_21",
            "account_code": "46500",
            "price": 25.00,
            "expected_group": "Office Supplies",
        },
        {
            "name": "Marketing Campaign",
            "description": "Facebook advertentie campagne",
            "btw_code": "HOOG_VERK_21",
            "account_code": "47200",
            "price": 500.00,
            "expected_group": "Marketing and Advertising",
        },
        {
            "name": "Travel Expense",
            "description": "Treinticket Amsterdam-Utrecht",
            "btw_code": "HOOG_VERK_21",
            "account_code": "43500",
            "price": 12.50,
            "expected_group": "Travel and Expenses",
        },
        {
            "name": "Equipment Purchase",
            "description": "Dell laptop voor development",
            "btw_code": "HOOG_VERK_21",
            "account_code": "43200",
            "price": 1250.00,
            "expected_group": "Products",
        },
        {
            "name": "Software Subscription",
            "description": "Microsoft Office 365 jaarlijks abonnement",
            "btw_code": "HOOG_VERK_21",
            "account_code": "46800",
            "price": 120.00,
            "expected_group": "Software and Subscriptions",
        },
    ]

    for test in test_cases:
        # Test categorization
        actual_group = determine_item_group(
            test["description"], test["btw_code"], test["account_code"], test["price"]
        )

        # Generate item code
        item_code = generate_item_code(test["description"])

        test_result = {
            "name": test["name"],
            "description": test["description"],
            "item_code": item_code,
            "expected_group": test["expected_group"],
            "actual_group": actual_group,
            "passed": actual_group == test["expected_group"],
        }

        results["tests"].append(test_result)

        if test_result["passed"]:
            results["summary"]["passed"] += 1
        else:
            results["summary"]["failed"] += 1

    # Add edge case tests
    edge_cases = {
        "minimal_info": determine_item_group("Random expense"),
        "conflicting_signals": determine_item_group(
            "Computer repair service", btw_code="HOOG_VERK_21", account_code="41500", price=75.00
        ),
        "low_price_only": determine_item_group("Miscellaneous", price=15.00),
        "high_price_only": determine_item_group("Miscellaneous", price=750.00),
    }

    results["edge_cases"] = edge_cases
    results["summary"]["total"] = len(test_cases)

    return results
