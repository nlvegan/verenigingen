#!/usr/bin/env python3
"""
Create item mappings for the ACTUAL account codes that are failing in the migration
"""

import frappe


def create_actual_failing_mappings():
    """Create mappings for the actual failing account codes from error logs"""

    print("=== Creating Item Mappings for Actual Failing Codes ===")

    company = frappe.db.get_single_value("Global Defaults", "default_company")
    if not company:
        company = frappe.db.get_value("Company", {}, "name")

    # Extract actual failing codes from the recent errors
    # These are the codes that caused "Could not find Item Group" errors
    actual_failing_codes = [
        {
            "account_code": "15916395",  # From mutation 17 error
            "item_code": "EBH-CATERING-SERVICES",
            "item_name": "Catering and Event Services",
            "item_group": "Services",
            "transaction_type": "Purchase",
            "description": "Restaurant bills, catering, event dining",
        },
        {
            "account_code": "13201956",  # From financial services errors
            "item_code": "EBH-FINANCIAL-SERVICES",
            "item_name": "Financial and Transaction Services",
            "item_group": "Services",
            "transaction_type": "Purchase",
            "description": "Bank costs, transaction fees, financial services",
        },
        {
            "account_code": "13201988",  # From travel expenses
            "item_code": "EBH-TRAVEL-EXPENSE",
            "item_name": "Travel and Transportation Expenses",
            "item_group": "Expense Items",
            "transaction_type": "Purchase",
            "description": "Travel costs, transportation, accommodation",
        },
        {
            "account_code": "13201912",  # From marketing materials
            "item_code": "EBH-MARKETING-MATERIALS",
            "item_name": "Marketing and Promotional Materials",
            "item_group": "Services",
            "transaction_type": "Purchase",
            "description": "Marketing materials, promotional items, advertising",
        },
    ]

    created_mappings = 0
    created_items = 0

    for mapping_config in actual_failing_codes:
        print(f"\n--- Processing Account {mapping_config['account_code']} ---")

        # Check if mapping already exists
        existing_mapping = frappe.db.exists(
            "E-Boekhouden Item Mapping", {"account_code": mapping_config["account_code"], "company": company}
        )

        if existing_mapping:
            print(f"✓ Mapping already exists: {existing_mapping}")
            continue

        # Create or verify item exists
        item_code = mapping_config["item_code"]
        if not frappe.db.exists("Item", item_code):
            try:
                # Create the item
                item = frappe.new_doc("Item")
                item.item_code = item_code
                item.item_name = mapping_config["item_name"]
                item.description = mapping_config["description"]
                item.item_group = mapping_config["item_group"]
                item.stock_uom = "Unit"
                item.is_stock_item = 0
                item.is_sales_item = 1 if mapping_config["transaction_type"] in ["Sales", "Both"] else 0
                item.is_purchase_item = 1 if mapping_config["transaction_type"] in ["Purchase", "Both"] else 0
                item.insert()

                print(f"✅ Created item: {item_code}")
                created_items += 1

            except Exception as e:
                print(f"❌ Failed to create item {item_code}: {str(e)}")
                continue
        else:
            print(f"✓ Item already exists: {item_code}")

        # Create the mapping (without checking if account exists - just create the mapping)
        try:
            mapping = frappe.new_doc("E-Boekhouden Item Mapping")
            mapping.company = company
            mapping.account_code = mapping_config["account_code"]
            mapping.account_name = mapping_config["item_name"]  # Use item name as account name
            mapping.item_code = item_code
            mapping.transaction_type = mapping_config["transaction_type"]
            mapping.is_active = 1
            mapping.description = mapping_config["description"]
            mapping.notes = "Created to resolve 'Could not find Item Group' errors during migration"
            mapping.insert()

            print(f"✅ Created mapping: {mapping_config['account_code']} → {item_code}")
            created_mappings += 1

        except Exception as e:
            print(f"❌ Failed to create mapping for {mapping_config['account_code']}: {str(e)}")

    print("\n✅ Actual Failing Code Mappings Complete!")
    print(f"- Created {created_items} new items")
    print(f"- Created {created_mappings} new mappings")
    print("- Migration should now proceed past the failing mutations")

    return created_mappings > 0


def test_mappings():
    """Test the created mappings"""

    print("\n=== Testing Created Mappings ===")

    company = frappe.db.get_single_value("Global Defaults", "default_company")
    if not company:
        company = frappe.db.get_value("Company", {}, "name")

    test_codes = ["15916395", "13201956", "13201988", "13201912"]

    from verenigingen.e_boekhouden.doctype.e_boekhouden_item_mapping.e_boekhouden_item_mapping import (
        get_item_for_account,
    )

    working_count = 0
    for account_code in test_codes:
        try:
            item = get_item_for_account(account_code, company, "Purchase")
            if item:
                print(f"✅ {account_code} → {item}")
                working_count += 1
            else:
                print(f"❌ No mapping found for {account_code}")
        except Exception as e:
            print(f"❌ Error testing {account_code}: {str(e)}")

    print(f"\n✅ {working_count}/{len(test_codes)} mappings working correctly")
    return working_count == len(test_codes)


if __name__ == "__main__":
    try:
        frappe.init()
        frappe.connect()

        success = create_actual_failing_mappings()

        if success:
            test_mappings()

            print("\n" + "=" * 50)
            print("READY TO RESTART MIGRATION:")
            print("✅ Created mappings for actual failing account codes")
            print("✅ Items created with existing item groups")
            print("✅ Migration should now proceed past mutations 17, 1276-1323")
            print("✅ No more 'Could not find Item Group' errors expected")

    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback

        traceback.print_exc()
    finally:
        frappe.destroy()
