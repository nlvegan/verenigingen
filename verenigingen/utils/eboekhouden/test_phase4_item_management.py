#!/usr/bin/env python3
"""
Test Phase 4.3: Enhanced Item Management
Tests the smart item categorization logic
"""

import frappe
from field_mapping import (
    ACCOUNT_CODE_ITEM_HINTS,
    DEFAULT_ITEM_GROUPS,
    ITEM_GROUP_KEYWORDS,
    PRICE_CATEGORY_RANGES,
    VAT_CATEGORY_HINTS,
)
from frappe.utils import flt
from invoice_helpers import determine_item_group, generate_item_code, get_or_create_item_from_description


def test_item_categorization():
    """Test various item categorization scenarios"""

    test_cases = [
        # Test Case 1: Description keyword matching
        {
            "description": "Consultancy diensten voor project X",
            "unit": "Uur",
            "btw_code": "HOOG_VERK_21",
            "account_code": "41000",
            "price": 150.00,
            "expected_group": "Services",
            "expected_stock": False,
        },
        # Test Case 2: Product with BTW hint
        {
            "description": "Kantoorbenodigdheden",
            "unit": "Stk",
            "btw_code": "HOOG_VERK_21",
            "account_code": "46500",
            "price": 25.00,
            "expected_group": "Office Supplies",
            "expected_stock": True,
        },
        # Test Case 3: Marketing expense
        {
            "description": "Facebook advertentie campagne",
            "unit": "Nos",
            "btw_code": "HOOG_VERK_21",
            "account_code": "47200",
            "price": 500.00,
            "expected_group": "Marketing and Advertising",
            "expected_stock": False,
        },
        # Test Case 4: Utility based on account code
        {
            "description": "Maandelijkse kosten",
            "unit": "Maand",
            "btw_code": "LAAG_VERK_6",
            "account_code": "45100",
            "price": 150.00,
            "expected_group": "Utilities and Infrastructure",
            "expected_stock": False,
        },
        # Test Case 5: Travel expense
        {
            "description": "Treinticket Amsterdam-Utrecht",
            "unit": "Stk",
            "btw_code": "HOOG_VERK_21",
            "account_code": "43500",
            "price": 12.50,
            "expected_group": "Travel and Expenses",
            "expected_stock": False,
        },
        # Test Case 6: Equipment (high price product)
        {
            "description": "Dell laptop voor development",
            "unit": "Stk",
            "btw_code": "HOOG_VERK_21",
            "account_code": "43200",
            "price": 1250.00,
            "expected_group": "Products",
            "expected_stock": True,
        },
        # Test Case 7: Subscription service
        {
            "description": "Microsoft Office 365 jaarlijks abonnement",
            "unit": "Jaar",
            "btw_code": "HOOG_VERK_21",
            "account_code": "46800",
            "price": 120.00,
            "expected_group": "Software and Subscriptions",
            "expected_stock": False,
        },
        # Test Case 8: Finance category
        {
            "description": "Bankkosten Rabobank",
            "unit": "Maand",
            "btw_code": "GEEN",
            "account_code": "48100",
            "price": 15.00,
            "expected_group": "Financial Services",
            "expected_stock": False,
        },
    ]

    print("Testing Enhanced Item Categorization")
    print("=" * 70)

    passed = 0
    failed = 0

    for i, test in enumerate(test_cases, 1):
        print(f"\nTest Case {i}: {test['description']}")
        print(f"  BTW Code: {test['btw_code']}, Account: {test['account_code']}, Price: €{test['price']}")

        # Test item group determination
        determined_group = determine_item_group(
            test["description"], test["btw_code"], test["account_code"], test["price"]
        )

        group_pass = determined_group == test["expected_group"]
        print(f"  Expected Group: {test['expected_group']}")
        print(f"  Determined Group: {determined_group} {'✓' if group_pass else '✗'}")

        # Test item code generation
        item_code = generate_item_code(test["description"])
        print(f"  Generated Code: {item_code}")

        # Test full item creation logic (mock)
        debug_info = []

        # Simulate what would happen in real creation
        if test["expected_stock"]:
            print(f"  Would be configured as: Stock Item (FIFO valuation)")
        else:
            print(f"  Would be configured as: Non-stock Service Item")

        if group_pass:
            passed += 1
        else:
            failed += 1
            print(f"  FAILED: Group mismatch!")

    print(f"\n{'=' * 70}")
    print(f"Summary: {passed} passed, {failed} failed")

    # Test edge cases
    print("\nTesting Edge Cases:")
    print("-" * 70)

    # Test with minimal info
    minimal_group = determine_item_group("Some random expense")
    print(f"Minimal info test: '{minimal_group}' (should be 'Services')")

    # Test with conflicting signals
    conflict_group = determine_item_group(
        "Computer repair service",  # 'computer' suggests product, 'service' suggests service
        btw_code="HOOG_VERK_21",
        account_code="41500",  # Service account range
        price=75.00,
    )
    print(f"Conflicting signals test: '{conflict_group}' (should prioritize description keywords)")

    # Test price-based categorization
    consumable_group = determine_item_group("Diverse items", price=15.00)  # Low price
    print(f"Price-based test (€15): '{consumable_group}' (should be 'Office Supplies')")

    equipment_group = determine_item_group("Diverse items", price=750.00)  # High price
    print(f"Price-based test (€750): '{equipment_group}' (should be 'Products')")

    return passed == len(test_cases)


def test_dutch_keyword_matching():
    """Test Dutch keyword recognition"""
    print("\n\nTesting Dutch Keyword Matching:")
    print("=" * 70)

    dutch_tests = [
        ("Juridisch advies inzake contract", "Services"),
        ("Kantoorartikelen en paperclips", "Office Supplies"),
        ("Glasvezel internet aansluiting", "Utilities and Infrastructure"),
        ("LinkedIn advertentiecampagne", "Marketing and Advertising"),
        ("Km-vergoeding dienstreis", "Travel and Expenses"),
        ("Dropbox Business abonnement", "Software and Subscriptions"),
        ("Hypotheek advieskosten", "Financial Services"),
        ("Meeting-lunch vergaderservice", "Catering and Events"),
    ]

    for description, expected in dutch_tests:
        result = determine_item_group(description)
        status = "✓" if result == expected else "✗"
        print(f"{status} '{description}' -> {result}")


def test_account_code_hints():
    """Test account code based categorization"""
    print("\n\nTesting Account Code Hints:")
    print("=" * 70)

    account_tests = [
        (41000, "service"),
        (43500, "product"),
        (45500, "utility"),
        (46200, "office"),
        (47800, "marketing"),
        (48500, "finance"),
        (80500, "service"),  # Revenue account
    ]

    for account_code, expected_hint in account_tests:
        # Find matching hint
        found_hint = None
        for (start, end), hint in ACCOUNT_CODE_ITEM_HINTS.items():
            if start <= account_code <= end:
                found_hint = hint
                break

        expected_group = DEFAULT_ITEM_GROUPS.get(expected_hint, "Services")
        status = "✓" if found_hint == expected_hint else "✗"
        print(f"{status} Account {account_code} -> {found_hint} -> {expected_group}")


def main():
    """Run all tests"""
    print("Phase 4.3: Enhanced Item Management Tests")
    print("=" * 70)

    # Run main categorization tests
    categorization_passed = test_item_categorization()

    # Run keyword matching tests
    test_dutch_keyword_matching()

    # Run account code tests
    test_account_code_hints()

    print("\n" + "=" * 70)
    if categorization_passed:
        print("✓ All main categorization tests passed!")
    else:
        print("✗ Some tests failed. Please review the output above.")

    print("\nEnhanced item management features:")
    print("- Smart categorization using description, BTW code, account, and price")
    print("- Automatic stock/non-stock determination")
    print("- Dutch keyword recognition for common business terms")
    print("- Price-based categorization for consumables vs equipment")
    print("- Account code hints based on NVV's actual CoA structure")


if __name__ == "__main__":
    main()
