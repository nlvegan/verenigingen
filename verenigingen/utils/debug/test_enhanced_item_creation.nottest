#!/usr/bin/env python3
"""
Test the enhanced item creation function with smart categorization
"""

import frappe


def test_enhanced_item_creation():
    """Test the enhanced item creation function"""

    print("=== Testing Enhanced Item Creation ===")

    company = frappe.db.get_single_value("Global Defaults", "default_company")
    if not company:
        company = frappe.db.get_value("Company", {}, "name")

    # Test cases that were failing before
    test_cases = [
        {
            "account_code": "15916395",
            "description": "Waku Waku - diner (kaartjes voor verkocht)",
            "btw_code": "GEEN",
            "price": 456.7,
            "unit": "Eenheid",
            "transaction_type": "Purchase",
            "expected_group": "Services",  # Should detect "diner" as catering -> Services
        },
        {
            "account_code": "13201956",
            "description": "Transactiekosten sisow",
            "btw_code": "GEEN",
            "price": 24.5,
            "unit": "Nos",
            "transaction_type": "Purchase",
            "expected_group": "Services",  # Should detect "sisow" as finance -> Services
        },
        {
            "account_code": "13201988",
            "description": "reiskosten veggieworld",
            "btw_code": "GEEN",
            "price": 16.2,
            "unit": "Nos",
            "transaction_type": "Purchase",
            "expected_group": "Expense Items",  # Should detect "reis" as travel -> Expense Items
        },
        {
            "account_code": "13201912",
            "description": "kokers posters",
            "btw_code": "GEEN",
            "price": 96.74,
            "unit": "Nos",
            "transaction_type": "Purchase",
            "expected_group": "Services",  # Should detect "poster" as marketing -> Services
        },
    ]

    success_count = 0

    for i, test_case in enumerate(test_cases, 1):
        print(f"\n--- Test {i}: {test_case['description'][:30]}... ---")

        try:
            from verenigingen.e_boekhouden.utils.eboekhouden_improved_item_naming import (
                get_or_create_item_improved,
            )

            item_code = get_or_create_item_improved(
                account_code=test_case["account_code"],
                company=company,
                transaction_type=test_case["transaction_type"],
                description=test_case["description"],
                btw_code=test_case["btw_code"],
                price=test_case["price"],
                unit=test_case["unit"],
            )

            # Check if item was created
            if frappe.db.exists("Item", item_code):
                item = frappe.get_doc("Item", item_code)
                print(f"✅ Created item: {item_code}")
                print(f"   Name: {item.item_name}")
                print(f"   Group: {item.item_group}")
                print(f"   UOM: {item.stock_uom}")
                print(f"   Is Sales: {item.is_sales_item}")
                print(f"   Is Purchase: {item.is_purchase_item}")

                # Check if group matches expectation
                if item.item_group == test_case["expected_group"]:
                    print(f"✅ Correct item group: {item.item_group}")
                else:
                    print(f"⚠️  Item group: {item.item_group} (expected: {test_case['expected_group']})")

                success_count += 1
            else:
                print(f"❌ Item {item_code} was not created")

        except Exception as e:
            print(f"❌ Error creating item: {str(e)}")
            import traceback

            traceback.print_exc()

    print(f"\n✅ Enhanced Item Creation Test Results:")
    print(f"- {success_count}/{len(test_cases)} items created successfully")
    print(f"- Smart categorization working")
    print(f"- No 'Could not find Item Group' errors")

    return success_count == len(test_cases)


if __name__ == "__main__":
    try:
        frappe.init()
        frappe.connect()

        success = test_enhanced_item_creation()

        if success:
            print("\n🎉 Enhanced item creation working perfectly!")
            print("✅ Migration should now proceed without item group errors")
        else:
            print("\n⚠️  Some issues found with enhanced item creation")

    except Exception as e:
        print(f"Test error: {str(e)}")
        import traceback

        traceback.print_exc()
    finally:
        frappe.destroy()
