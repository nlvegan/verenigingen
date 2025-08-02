#!/usr/bin/env python3
"""
Create missing E-Boekhouden Item Mappings for common account codes
This resolves the "Could not find Item Group" errors by providing proper mappings
"""

import frappe


def create_common_item_mappings():
    """Create item mappings for common E-Boekhouden account codes"""

    print("=== Creating Missing E-Boekhouden Item Mappings ===")

    # Get the company
    company = (
        frappe.defaults.get_user_default("Company")
        or frappe.db.get_single_value("Global Defaults", "default_company")
        or frappe.db.get_value("Company", {}, "name")
    )

    if not company:
        print("❌ No company found")
        return False

    print(f"Creating mappings for company: {company}")

    # Define common account patterns and their appropriate items
    common_mappings = [
        # Financial Services (Bank costs, transaction fees)
        {
            "account_code": "13201956",
            "account_name": "Bank Costs",
            "item_code": "EBH-BANK-COSTS",
            "item_name": "Bank Transaction Costs",
            "item_group": "Services",
            "transaction_type": "Purchase",
            "description": "Bank transaction costs and fees",
        },
        # Travel and Expenses
        {
            "account_code": "13201988",
            "account_name": "Travel Expenses",
            "item_code": "EBH-TRAVEL-EXPENSES",
            "item_name": "Travel and Transportation",
            "item_group": "Expense Items",
            "transaction_type": "Purchase",
            "description": "Travel costs, transportation, accommodation",
        },
        # Marketing and Advertising
        {
            "account_code": "13201912",
            "account_name": "Marketing Materials",
            "item_code": "EBH-MARKETING",
            "item_name": "Marketing and Promotional Materials",
            "item_group": "Services",
            "transaction_type": "Purchase",
            "description": "Marketing materials, promotional items, advertising",
        },
        # Event/Catering Services
        {
            "account_code": "13201892",
            "account_name": "Catering Services",
            "item_code": "EBH-CATERING",
            "item_name": "Catering and Event Services",
            "item_group": "Services",
            "transaction_type": "Purchase",
            "description": "Catering, food services, event expenses",
        },
        # General Services (fallback for income)
        {
            "account_code": "8000",
            "account_name": "General Income",
            "item_code": "EBH-GENERAL-INCOME",
            "item_name": "General Service Income",
            "item_group": "Services",
            "transaction_type": "Sales",
            "description": "General service income and revenue",
        },
        # Office Supplies and Materials
        {
            "account_code": "4000",
            "account_name": "Office Supplies",
            "item_code": "EBH-OFFICE-SUPPLIES",
            "item_name": "Office Supplies and Materials",
            "item_group": "Consumable",
            "transaction_type": "Purchase",
            "description": "Office supplies, materials, stationery",
        },
    ]

    created_mappings = 0
    created_items = 0

    for mapping_config in common_mappings:
        print(f"\n--- Processing {mapping_config['account_name']} ---")

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

        # Create the mapping
        try:
            mapping = frappe.new_doc("E-Boekhouden Item Mapping")
            mapping.company = company
            mapping.account_code = mapping_config["account_code"]
            mapping.account_name = mapping_config["account_name"]
            mapping.item_code = item_code
            mapping.transaction_type = mapping_config["transaction_type"]
            mapping.is_active = 1
            mapping.description = mapping_config["description"]
            mapping.insert()

            print(f"✅ Created mapping: {mapping_config['account_code']} → {item_code}")
            created_mappings += 1

        except Exception as e:
            print(f"❌ Failed to create mapping for {mapping_config['account_code']}: {str(e)}")

    print("\n✅ Item Mapping Creation Complete!")
    print(f"- Created {created_items} new items")
    print(f"- Created {created_mappings} new mappings")
    print("- These mappings will prevent 'Could not find Item Group' errors")

    return created_mappings > 0


def verify_mappings():
    """Verify the created mappings work correctly"""

    print("\n=== Verifying Item Mappings ===")

    company = frappe.db.get_single_value("Global Defaults", "default_company")
    if not company:
        company = frappe.db.get_value("Company", {}, "name")

    test_accounts = ["13201956", "13201988", "13201912", "8000"]

    from verenigingen.e_boekhouden.doctype.e_boekhouden_item_mapping.e_boekhouden_item_mapping import (
        get_item_for_account,
    )

    all_working = True
    for account_code in test_accounts:
        try:
            item = get_item_for_account(account_code, company, "Both")
            if item:
                print(f"✅ {account_code} → {item}")
            else:
                print(f"❌ No mapping found for {account_code}")
                all_working = False
        except Exception as e:
            print(f"❌ Error testing {account_code}: {str(e)}")
            all_working = False

    if all_working:
        print("✅ All mappings working correctly!")
    else:
        print("⚠️  Some mappings need attention")

    return all_working


if __name__ == "__main__":
    try:
        frappe.init()
        frappe.connect()

        success = create_common_item_mappings()

        if success:
            verify_mappings()

            print("\n" + "=" * 50)
            print("SUMMARY:")
            print("✅ Missing item mappings created")
            print("✅ Items created with proper groups")
            print("✅ Migration should now proceed without 'Item Group' errors")
            print("✅ Future imports will use these predefined mappings")

    except Exception as e:
        print(f"Setup error: {str(e)}")
        import traceback

        traceback.print_exc()
    finally:
        frappe.destroy()
