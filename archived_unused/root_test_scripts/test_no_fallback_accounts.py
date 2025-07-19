#!/usr/bin/env python3
"""
Test script to verify that account mapping errors properly
instead of using generic fallback accounts
"""

import frappe


@frappe.whitelist()
def test_account_mapping_errors():
    """Test that missing account mappings raise proper errors"""
    results = []

    try:
        # Test 1: Test grootboek mapping with non-existent account
        results.append("=== Test 1: Non-existent Grootboek Number ===")
        from verenigingen.utils.eboekhouden.invoice_helpers import map_grootboek_to_erpnext_account

        debug_info = []
        try:
            result = map_grootboek_to_erpnext_account("99999", "sales", debug_info)
            results.append(f"ERROR: Should have thrown error but returned: {result}")
        except Exception as e:
            results.append(f"✓ Correctly threw error: {str(e)}")
            results.append(f"  Debug info: {debug_info}")

        # Test 2: Test tegenrekening mapping with non-existent account
        results.append("\n=== Test 2: Non-existent Tegenrekening Code ===")
        from verenigingen.utils.smart_tegenrekening_mapper import SmartTegenrekeningMapper

        mapper = SmartTegenrekeningMapper()
        try:
            result = mapper.get_item_for_tegenrekening("NONEXISTENT", "Test description", "purchase", 100)
            results.append(f"ERROR: Should have thrown error but returned: {result}")
        except Exception as e:
            results.append(f"✓ Correctly threw error: {str(e)}")

        # Test 3: Test empty account code
        results.append("\n=== Test 3: Empty Account Code ===")
        try:
            result = mapper.get_item_for_tegenrekening("", "Test description", "sales", 50)
            results.append(f"ERROR: Should have thrown error but returned: {result}")
        except Exception as e:
            results.append(f"✓ Correctly threw error: {str(e)}")

        # Test 4: Test invoice line creation with missing mapping
        results.append("\n=== Test 4: Invoice Line Creation ===")
        from verenigingen.utils.smart_tegenrekening_mapper import create_invoice_line_for_tegenrekening

        try:
            result = create_invoice_line_for_tegenrekening("UNMAPPED", 100, "Test", "purchase")
            results.append(f"ERROR: Should have thrown error but returned: {result}")
        except Exception as e:
            results.append(f"✓ Correctly threw error: {str(e)}")

        # Test 5: Verify no generic fallback items exist
        results.append("\n=== Test 5: Check for Generic Fallback Items ===")
        generic_items = frappe.get_all(
            "Item",
            filters={
                "item_code": ["in", ["EB-GENERIC-INCOME", "EB-GENERIC-EXPENSE", "E-Boekhouden Import Item"]]
            },
            fields=["item_code", "item_name"],
        )

        if generic_items:
            results.append(f"WARNING: Found generic fallback items that should not exist: {generic_items}")
        else:
            results.append("✓ No generic fallback items found")

        # Test 6: Verify proper account exists in mapping
        results.append("\n=== Test 6: Valid Account Mapping ===")
        debug_info = []
        try:
            # Try with a known account that should exist
            result = map_grootboek_to_erpnext_account("80001", "sales", debug_info)
            results.append(f"✓ Valid account mapping works: {result}")
            results.append(f"  Debug info: {debug_info}")
        except Exception as e:
            results.append(f"Note: Account 80001 not mapped yet: {str(e)}")

    except Exception as e:
        results.append(f"\nUnexpected error: {str(e)}")
        import traceback

        results.append(traceback.format_exc())

    return "\n".join(results)


if __name__ == "__main__":
    # This won't work directly, needs to be called via bench
    print(
        "Run this via: bench --site dev.veganisme.net execute test_no_fallback_accounts.test_account_mapping_errors"
    )
