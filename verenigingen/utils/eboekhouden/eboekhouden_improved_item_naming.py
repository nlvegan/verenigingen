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
    # Log missing account code - this is a data quality issue
    if not account_code:
        frappe.log_error(
            title="E-Boekhouden Item Creation: Missing Account Code",
            message=f"Missing account code for item creation. Company: {company}, Transaction Type: {transaction_type}, Description: {description}. Using 'MISC' as fallback.",
        )
        account_code = "MISC"

    # First, check if there's a mapping
    from verenigingen.verenigingen.doctype.e_boekhouden_item_mapping.e_boekhouden_item_mapping import (
        get_item_for_account,
    )

    try:
        mapped_item = get_item_for_account(account_code, company, transaction_type)
        if mapped_item and frappe.db.exists("Item", mapped_item):
            # Log successful mapping usage
            frappe.logger().info(
                f"E-Boekhouden Item Creation: Using mapped item '{mapped_item}' for account {account_code}"
            )
            return mapped_item
    except Exception as e:
        frappe.log_error(
            title="E-Boekhouden Item Creation: Mapping Check Failed",
            message=f"Failed to check item mapping for account {account_code}: {str(e)}",
        )

    # If no mapping, create item based on account information
    try:
        account_info = frappe.db.get_value(
            "Account",
            {"account_number": account_code, "company": company},
            ["account_name", "account_type", "root_type"],
            as_dict=True,
        )
    except Exception as e:
        frappe.log_error(
            title="E-Boekhouden Item Creation: Account Lookup Failed",
            message=f"Failed to retrieve account information for code {account_code} in company {company}: {str(e)}",
        )
        account_info = None

    if account_info and account_info.account_name:
        # Use account name as base for item name
        item_name = clean_item_name(account_info.account_name)
        frappe.logger().info(
            f"E-Boekhouden Item Creation: Using account name '{account_info.account_name}' for item creation (code: {account_code})"
        )
    else:
        # Log data quality issue - account not found or incomplete
        if not account_info:
            frappe.log_error(
                title="E-Boekhouden Item Creation: Account Not Found",
                message=f"Account with code '{account_code}' missing from company '{company}'. This indicates missing or incomplete chart of accounts import. Using fallback naming.",
            )
        else:
            frappe.log_error(
                title="E-Boekhouden Item Creation: Account Missing Name",
                message=f"Account with code '{account_code}' exists but has no account_name. Account info: {account_info}. Using fallback naming.",
            )

        # Fallback with improved logging
        if transaction_type == "Sales":
            item_name = f"Income {account_code}"
        elif transaction_type == "Purchase":
            item_name = f"Expense {account_code}"
        else:
            item_name = f"Service {account_code}"

        frappe.logger().warning(
            f"E-Boekhouden Item Creation: Using fallback item name '{item_name}' for account {account_code}"
        )

    # Check if item already exists
    if frappe.db.exists("Item", item_name):
        frappe.logger().info(f"E-Boekhouden Item Creation: Item '{item_name}' already exists, reusing")
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
                frappe.logger().info(
                    f"E-Boekhouden Item Creation: Assigned item '{item_name}' to Income Services group"
                )
            elif account_info.root_type == "Expense":
                item.item_group = get_or_create_item_group("Expense Services")
                frappe.logger().info(
                    f"E-Boekhouden Item Creation: Assigned item '{item_name}' to Expense Services group"
                )
            else:
                item.item_group = get_or_create_item_group("General Services")
                frappe.logger().info(
                    f"E-Boekhouden Item Creation: Assigned item '{item_name}' to General Services group (root_type: {account_info.root_type})"
                )
        else:
            item.item_group = get_or_create_item_group("Services")
            frappe.logger().warning(
                f"E-Boekhouden Item Creation: No account info available, assigned item '{item_name}' to default Services group"
            )

        item.stock_uom = "Nos"
        item.is_stock_item = 0

        # Add description if available
        if description:
            item.description = f"Auto-created from E-boekhouden account {account_code}"
            if account_info and account_info.account_name:
                item.description += f" ({account_info.account_name})"
        else:
            item.description = f"Auto-created from E-boekhouden account {account_code}"

        item.insert(ignore_permissions=True)
        frappe.logger().info(
            f"E-Boekhouden Item Creation: Successfully created item '{item_name}' for account {account_code}"
        )
        return item_name

    except Exception as e:
        frappe.log_error(
            title="E-Boekhouden Item Creation: Item Creation Failed",
            message=f"Failed to create item '{item_name}' for account {account_code}: {str(e)}\n\nFalling back to generic item creation.",
        )
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
    """Get or create item group with proper validation (for eBoekhouden migration only)"""
    if frappe.db.exists("Item Group", group_name):
        return group_name

    # Log auto-creation for audit trail
    frappe.log_error(
        f"Auto-creating item group '{group_name}' during eBoekhouden migration. "
        "Consider pre-creating item groups for better data organization.",
        "eBoekhouden Migration Auto-Creation",
    )

    # Find parent group with explicit validation
    parent = None
    if frappe.db.exists("Item Group", "Services"):
        parent = "Services"
    else:
        # Look for any group parent
        parent = frappe.db.get_value("Item Group", {"is_group": 1}, "name")
        if not parent:
            frappe.throw(
                "No parent item group found. Please ensure 'Services' item group exists or configure a parent group before running eBoekhouden migration."
            )

    # Create new group with explicit error handling
    try:
        group = frappe.new_doc("Item Group")
        group.item_group_name = group_name
        group.parent_item_group = parent
        group.is_group = 1
        group.insert(ignore_permissions=True)

        frappe.logger().info(
            f"eBoekhouden Migration: Created item group '{group_name}' under parent '{parent}'"
        )
        return group_name

    except Exception as e:
        frappe.log_error(
            f"Failed to create item group '{group_name}': {str(e)}",
            "eBoekhouden Migration Item Group Creation Error",
        )

        # Use fallback with explicit validation
        fallback_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
        if not fallback_group:
            frappe.throw(
                "Cannot create item group and no fallback group available. Please configure item groups before running eBoekhouden migration."
            )

        frappe.logger().warning(
            f"eBoekhouden Migration: Using fallback item group '{fallback_group}' for '{group_name}'"
        )
        return fallback_group


def get_or_create_generic_item(company):
    """Get or create a generic item as last resort"""
    generic_name = "General Service"

    # Log use of generic fallback - this indicates a significant data quality issue
    frappe.log_error(
        title="E-Boekhouden Item Creation: Using Generic Fallback",
        message=f"Using generic fallback item '{generic_name}' for company {company}. This indicates a critical failure in the intelligent item creation process and should be investigated immediately.",
    )

    if not frappe.db.exists("Item", generic_name):
        try:
            item = frappe.new_doc("Item")
            item.item_code = generic_name
            item.item_name = generic_name
            item.item_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
            item.stock_uom = "Nos"
            item.is_stock_item = 0
            item.description = "Generic service item for unmapped transactions - CREATED AS FALLBACK"
            item.insert(ignore_permissions=True)
            frappe.logger().info(
                f"E-Boekhouden Item Creation: Created generic fallback item '{generic_name}'"
            )
        except Exception as e:
            frappe.log_error(
                title="E-Boekhouden Item Creation: Generic Item Creation Failed",
                message=f"Failed to create generic fallback item '{generic_name}': {str(e)}. This is a critical system error.",
            )
            # If we can't even create a generic item, something is very wrong
            frappe.throw(f"Critical error: Unable to create generic fallback item: {str(e)}")

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
