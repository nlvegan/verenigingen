#!/usr/bin/env python3
"""
Test Enhanced Item Management directly
Run with: cd /home/frappe/frappe-bench && bench --site dev.veganisme.net execute vereinigingen.test_enhanced_item_management.test_all
"""

import frappe


@frappe.whitelist()
def test_all():
    """Test enhanced item management features"""
    from verenigingen.utils.eboekhouden.invoice_helpers import determine_item_group, generate_item_code

    print("\n" + "=" * 70)
    print("PHASE 4.3: ENHANCED ITEM MANAGEMENT TEST")
    print("=" * 70)

    # Test cases with expected results
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
            "name": "Utility Service",
            "description": "Maandelijkse internetkosten",
            "btw_code": "LAAG_VERK_6",
            "account_code": "45100",
            "price": 150.00,
            "expected_group": "Utilities and Infrastructure",
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
        {
            "name": "Banking Fees",
            "description": "Bankkosten Rabobank",
            "btw_code": "GEEN",
            "account_code": "48100",
            "price": 15.00,
            "expected_group": "Financial Services",
        },
    ]

    passed = 0
    failed = 0

    for test in test_cases:
        print(f"\nTest: {test['name']}")
        print(f"  Description: {test['description']}")
        print(f"  BTW: {test['btw_code']}, Account: {test['account_code']}, Price: €{test['price']}")

        # Test categorization
        group = determine_item_group(
            test["description"], test["btw_code"], test["account_code"], test["price"]
        )

        # Generate item code
        item_code = generate_item_code(test["description"])

        print(f"  Generated Code: {item_code}")
        print(f"  Expected Group: {test['expected_group']}")
        print(f"  Actual Group: {group}")

        if group == test["expected_group"]:
            print(f"  Result: ✓ PASSED")
            passed += 1
        else:
            print(f"  Result: ✗ FAILED")
            failed += 1

    # Test edge cases
    print("\n" + "-" * 70)
    print("EDGE CASE TESTS")
    print("-" * 70)

    # Minimal info
    minimal = determine_item_group("Random expense item")
    print(f"Minimal info: '{minimal}' (should default to 'Services')")

    # Conflicting signals
    conflict = determine_item_group(
        "Computer repair service", btw_code="HOOG_VERK_21", account_code="41500", price=75.00
    )
    print(f"Conflicting signals: '{conflict}' (description should win)")

    # Price-based only
    low_price = determine_item_group("Miscellaneous", price=15.00)
    high_price = determine_item_group("Miscellaneous", price=750.00)
    print(f"Low price (€15): '{low_price}' (should be 'Office Supplies')")
    print(f"High price (€750): '{high_price}' (should be 'Products')")

    # Summary
    print("\n" + "=" * 70)
    print(f"SUMMARY: {passed}/{len(test_cases)} tests passed")
    print("=" * 70)

    if passed == len(test_cases):
        print("✓ All tests passed! Enhanced item management is working correctly.")
    else:
        print(f"✗ {failed} tests failed. Please review the implementation.")

    # Show features
    print("\nENHANCED FEATURES IMPLEMENTED:")
    print("- Multi-signal categorization (description, BTW, account, price)")
    print("- Dutch keyword recognition for common business terms")
    print("- Smart stock/non-stock determination by category")
    print("- Price-based hints for consumables vs equipment")
    print("- Account code mapping adapted to NVV's CoA structure")

    return {"passed": passed, "failed": failed, "total": len(test_cases)}


# Allow direct execution
if __name__ == "__main__":
    test_all()
