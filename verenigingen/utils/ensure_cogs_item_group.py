"""
Ensure Cost of Goods Sold Items group exists
"""

import frappe


@frappe.whitelist()
def ensure_cogs_item_group():
    """Ensure the Cost of Goods Sold Items group exists"""

    try:
        # Check if the item group exists
        if not frappe.db.exists("Item Group", "Cost of Goods Sold Items"):
            # Create the item group
            item_group = frappe.new_doc("Item Group")
            item_group.item_group_name = "Cost of Goods Sold Items"
            item_group.parent_item_group = "All Item Groups"
            item_group.is_group = 0
            item_group.insert(ignore_permissions=True)

            return {"success": True, "message": "Created 'Cost of Goods Sold Items' item group"}
        else:
            return {"success": True, "message": "'Cost of Goods Sold Items' item group already exists"}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def update_existing_inkoop_items():
    """Update existing items that should be categorized as COGS"""

    try:
        # Find items that likely should be COGS based on their names
        items_to_update = frappe.db.sql(
            """
            SELECT name, item_name, item_group
            FROM `tabItem`
            WHERE (
                LOWER(item_name) LIKE '%inkoop%'
                OR LOWER(item_name) LIKE '%materiaal%'
                OR LOWER(item_name) LIKE '%grondstoffen%'
                OR LOWER(item_name) LIKE '%kostprijs%'
            )
            AND item_group != 'Cost of Goods Sold Items'
        """,
            as_dict=True,
        )

        updated_count = 0
        errors = []

        # First ensure the COGS item group exists
        ensure_cogs_item_group()

        for item in items_to_update:
            try:
                frappe.db.set_value("Item", item.name, "item_group", "Cost of Goods Sold Items")
                updated_count += 1
            except Exception as e:
                errors.append({"item": item.name, "error": str(e)})

        frappe.db.commit()

        return {
            "success": True,
            "updated": updated_count,
            "found": len(items_to_update),
            "errors": errors,
            "message": f"Updated {updated_count} items to 'Cost of Goods Sold Items' group",
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def check_inkoop_accounts():
    """Check accounts that contain inkoop/materiaal keywords"""

    try:
        accounts = frappe.db.sql(
            """
            SELECT name, account_name, account_type, account_number
            FROM `tabAccount`
            WHERE company = 'Ned Ver Vegan'
            AND (
                LOWER(account_name) LIKE '%inkoop%'
                OR LOWER(account_name) LIKE '%materiaal%'
                OR LOWER(account_name) LIKE '%grondstoffen%'
                OR LOWER(account_name) LIKE '%kostprijs%'
            )
            ORDER BY account_number
        """,
            as_dict=True,
        )

        return {
            "success": True,
            "accounts": accounts,
            "count": len(accounts),
            "message": f"Found {len(accounts)} accounts with inkoop/materiaal keywords",
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
