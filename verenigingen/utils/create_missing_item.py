#!/usr/bin/env python3
"""
Create the missing eBoekhouden Import Item
"""

import frappe


@frappe.whitelist()
def create_missing_item():
    """Create eBoekhouden Import Item (without hyphen)"""

    item_code = "eBoekhouden Import Item"

    # Check if already exists
    if frappe.db.exists("Item", item_code):
        print(f"Item '{item_code}' already exists")
        return {"exists": True}

    # Create the item
    try:
        item = frappe.new_doc("Item")
        item.item_code = item_code
        item.item_name = item_code
        item.item_group = "Products"
        item.stock_uom = "Unit"
        item.is_stock_item = 0
        item.is_sales_item = 1
        item.is_purchase_item = 1
        item.description = "Generic item for eBoekhouden imports"

        # Add company defaults
        company = frappe.db.get_single_value("E-Boekhouden Settings", "default_company")
        if company:
            # Get default income account
            income_account = frappe.db.get_value(
                "Account",
                {
                    "company": company,
                    "account_name": ["like", "%Donaties%"],
                    "root_type": "Income",
                    "is_group": 0,
                },
                "name",
            )
            if not income_account:
                income_account = frappe.db.get_value(
                    "Account", {"company": company, "root_type": "Income", "is_group": 0}, "name"
                )

            # Get default expense account
            expense_account = frappe.db.get_value(
                "Account",
                {
                    "company": company,
                    "account_name": ["like", "%Onvoorziene%"],
                    "root_type": "Expense",
                    "is_group": 0,
                },
                "name",
            )
            if not expense_account:
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
                print(f"Added defaults - Income: {income_account}, Expense: {expense_account}")

        item.save(ignore_permissions=True)
        print(f"Successfully created item: {item_code}")

        return {
            "success": True,
            "item_code": item.item_code,
            "item_name": item.item_name,
            "income_account": income_account if company else None,
            "expense_account": expense_account if company else None,
        }

    except Exception as e:
        print(f"Error creating item: {str(e)}")
        import traceback

        print(traceback.format_exc())
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    print("Create missing eBoekhouden Import Item")
