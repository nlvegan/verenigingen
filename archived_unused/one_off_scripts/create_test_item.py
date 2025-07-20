#!/usr/bin/env python3
"""Create the missing MEMBERSHIP-MONTHLY item"""

import frappe


def create_membership_monthly_item():
    """Create the MEMBERSHIP-MONTHLY item for tests"""
    try:
        # Check if item already exists
        if frappe.db.exists("Item", "MEMBERSHIP-MONTHLY"):
            print("MEMBERSHIP-MONTHLY item already exists")
            return frappe.get_doc("Item", "MEMBERSHIP-MONTHLY")

        item = frappe.get_doc(
            {
                "doctype": "Item",
                "item_code": "MEMBERSHIP-MONTHLY",
                "item_name": "Monthly Membership",
                "item_group": "Services",
                "is_service_item": 1,
                "is_fixed_asset": 0,
                "is_stock_item": 0,
                "include_item_in_manufacturing": 0,
                "disabled": 0,
                "standard_rate": 10.00,
                "description": "Monthly membership dues - test item",
            }
        )
        item.insert(ignore_permissions=True)
        print("✅ Created MEMBERSHIP-MONTHLY item")
        return item
    except Exception as e:
        print(f"⚠️ Failed to create MEMBERSHIP-MONTHLY item: {e}")
        return None


if __name__ == "__main__":
    create_membership_monthly_item()
