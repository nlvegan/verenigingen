"""
Improved item naming for E-boekhouden imports
"""

import frappe


def get_or_create_item_improved(account_code, company, transaction_type="Both", description=None):
    """
    Get or create item with improved naming based on account information

    Args:
        account_code: E-boekhouden account code (grootboekrekening)
        company: Company name
        transaction_type: "Sales", "Purchase", or "Both"
        description: Optional transaction description for context

    Returns:
        Item code (name) to use in invoice
    """
    if not account_code:
        account_code = "MISC"

    # First, check if there's a mapping
    from verenigingen.verenigingen.doctype.e_boekhouden_item_mapping.e_boekhouden_item_mapping import (
        get_item_for_account,
    )

    mapped_item = get_item_for_account(account_code, company, transaction_type)
    if mapped_item and frappe.db.exists("Item", mapped_item):
        return mapped_item

    # If no mapping, create item based on account information
    account_info = frappe.db.get_value(
        "Account",
        {"account_number": account_code, "company": company},
        ["account_name", "account_type", "root_type"],
        as_dict=True,
    )

    if account_info and account_info.account_name:
        # Use account name as base for item name
        item_name = clean_item_name(account_info.account_name)
    else:
        # Fallback to old behavior but with better prefix
        if transaction_type == "Sales":
            item_name = "Income {account_code}"
        elif transaction_type == "Purchase":
            item_name = "Expense {account_code}"
        else:
            item_name = "Service {account_code}"

    # Check if item already exists
    if frappe.db.exists("Item", item_name):
        return item_name

    # Create new item
    try:
        item = frappe.new_doc("Item")
        item.item_code = item_name
        item.item_name = item_name

        # Set item group based on account type
        if account_info:
            if account_info.root_type == "Income":
                item.item_group = get_or_create_item_group("Income Services")
            elif account_info.root_type == "Expense":
                item.item_group = get_or_create_item_group("Expense Services")
            else:
                item.item_group = get_or_create_item_group("General Services")
        else:
            item.item_group = get_or_create_item_group("Services")

        item.stock_uom = "Nos"
        item.is_stock_item = 0

        # Add description if available
        if description:
            item.description = "Auto-created from E-boekhouden account {account_code}"
            if account_info and account_info.account_name:
                item.description += f" ({account_info.account_name})"

        item.insert(ignore_permissions=True)
        return item_name

    except Exception as e:
        frappe.log_error(f"Failed to create item {item_name}: {str(e)}")
        # Return a generic item as fallback
        return get_or_create_generic_item(company)


def clean_item_name(account_name):
    """Clean account name to make a valid item name"""
    # Remove account number prefixes if present
    import re

    cleaned = re.sub(r"^\d+\s*-\s*", "", account_name)

    # Remove company abbreviations
    cleaned = re.sub(r"\s*-\s*[A-Z]{2,4}$", "", cleaned)

    # Limit length
    if len(cleaned) > 100:
        cleaned = cleaned[:97] + "..."

    return cleaned.strip()


def get_or_create_item_group(group_name):
    """Get or create item group"""
    if frappe.db.exists("Item Group", group_name):
        return group_name

    # Find parent group
    parent = "Services"
    if not frappe.db.exists("Item Group", parent):
        parent = frappe.db.get_value("Item Group", {"is_group": 1}, "name")

    # Create new group
    try:
        group = frappe.new_doc("Item Group")
        group.item_group_name = group_name
        group.parent_item_group = parent
        group.is_group = 1
        group.insert(ignore_permissions=True)
        return group_name
    except Exception:
        # Return default group
        return frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups"


def get_or_create_generic_item(company):
    """Get or create a generic item as last resort"""
    generic_name = "General Service"

    if not frappe.db.exists("Item", generic_name):
        try:
            item = frappe.new_doc("Item")
            item.item_code = generic_name
            item.item_name = generic_name
            item.item_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
            item.stock_uom = "Nos"
            item.is_stock_item = 0
            item.description = "Generic service item for unmapped transactions"
            item.insert(ignore_permissions=True)
        except Exception:
            pass

    return generic_name


def migrate_existing_items():
    """
    One-time migration to improve existing item names
    This can be run to update items created with the old naming convention
    """
    frappe.set_user("Administrator")

    # Find items created with old pattern
    old_pattern_items = frappe.db.sql(
        """
        SELECT name, item_code
        FROM `tabItem`
        WHERE item_code LIKE 'Service %'
        AND item_code REGEXP '^Service [0-9]+$'
    """,
        as_dict=True,
    )

    updated_count = 0

    for item in old_pattern_items:
        # Extract account code
        account_code = item.item_code.replace("Service ", "")

        # Find account information
        account_info = frappe.db.get_value(
            "Account", {"account_number": account_code}, ["account_name", "company"], as_dict=True
        )

        if account_info and account_info.account_name:
            new_name = clean_item_name(account_info.account_name)

            # Check if new name already exists
            if not frappe.db.exists("Item", new_name):
                try:
                    # Rename the item
                    frappe.rename_doc("Item", item.name, new_name, force=True)
                    updated_count += 1
                    print(f"Renamed {item.item_code} to {new_name}")
                except Exception as e:
                    print(f"Failed to rename {item.item_code}: {str(e)}")

    frappe.db.commit()
    return {"success": True, "updated": updated_count}
