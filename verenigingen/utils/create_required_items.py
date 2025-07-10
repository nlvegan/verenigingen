#!/usr/bin/env python3
"""
Create required items for eBoekhouden import
"""

import frappe


@frappe.whitelist()
def create_eboekhouden_import_item():
    """Create the required eBoekhouden Import Item"""

    item_name = "E-Boekhouden Import Item"

    # Check if item already exists
    if frappe.db.exists("Item", {"item_name": item_name}):
        print(f"Item '{item_name}' already exists")
        return {"exists": True}

    # Get default item group
    item_group = frappe.db.get_single_value("Stock Settings", "item_group") or "Products"
    if not frappe.db.exists("Item Group", item_group):
        item_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups"

    # Get default UOM
    stock_uom = frappe.db.get_single_value("Stock Settings", "stock_uom") or "Unit"
    if not frappe.db.exists("UOM", stock_uom):
        stock_uom = "Unit"

    # Create the item
    try:
        item = frappe.new_doc("Item")
        item.item_code = item_name
        item.item_name = item_name
        item.item_group = item_group
        item.stock_uom = stock_uom
        item.is_stock_item = 0  # Non-stock item
        item.is_sales_item = 1
        item.is_purchase_item = 1
        item.description = "Generic item for E-Boekhouden imports"

        # Set item defaults
        company = frappe.db.get_single_value("E-Boekhouden Settings", "default_company")
        if company:
            # Get default accounts
            income_account = frappe.db.get_value(
                "Account", {"company": company, "root_type": "Income", "is_group": 0}, "name"
            )
            expense_account = frappe.db.get_value(
                "Account", {"company": company, "root_type": "Expense", "is_group": 0}, "name"
            )

            if income_account or expense_account:
                item.append(
                    "item_defaults",
                    {
                        "company": company,
                        "income_account": income_account,
                        "expense_account": expense_account,
                    },
                )

        item.save(ignore_permissions=True)

        print(f"Successfully created item: {item_name}")
        return {"success": True, "item_code": item.item_code, "item_name": item.item_name}

    except Exception as e:
        print(f"Error creating item: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def check_required_items():
    """Check if all required items exist"""

    required_items = ["E-Boekhouden Import Item", "eBoekhouden Import Item"]  # Check both variations

    results = {}
    for item_name in required_items:
        exists = frappe.db.exists("Item", {"item_name": item_name})
        results[item_name] = exists
        print(f"{item_name}: {'✓ Exists' if exists else '✗ Missing'}")

    return results


if __name__ == "__main__":
    print("Create required items for eBoekhouden import")
