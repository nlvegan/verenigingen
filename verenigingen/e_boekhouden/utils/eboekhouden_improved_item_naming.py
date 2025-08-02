"""
Improved item naming for E-boekhouden imports
"""

import frappe
from frappe.utils import flt


def map_unit_of_measure(unit):
    """Map Dutch units to ERPNext UOMs"""
    uom_mapping = {
        # Dutch to English UOM mapping
        "Nos": "Unit",
        "Unit": "Unit",
        "Eenheid": "Unit",
        "Stuks": "Unit",
        "Per stuk": "Unit",
        "Uur": "Hour",
        "Hour": "Hour",
        "Dag": "Day",
        "Maand": "Month",
        "Jaar": "Year",
        "Kg": "Kg",
        "Liter": "Litre",
        "Meter": "Meter",
        "Service": "Unit",
        "Trip": "Unit",
        "License": "Unit",
    }

    return uom_mapping.get(unit, "Unit")


def determine_smart_item_group(description, btw_code=None, account_code=None, price=None, account_info=None):
    """Enhanced item group determination using multiple signals"""

    # Use existing item groups only (avoid non-existent groups)
    SAFE_ITEM_GROUPS = {
        "default": "Services",
        "service": "Services",
        "product": "Products",
        "travel": "Expense Items",  # Travel and Expenses -> Expense Items
        "marketing": "Services",  # Marketing and Advertising -> Services
        "utility": "Services",  # Utilities -> Services
        "office": "Consumable",  # Office Supplies -> Consumable
        "subscription": "Services",  # Software and Subscriptions -> Services
        "finance": "Services",  # Financial Services -> Services
        "catering": "Services",  # Catering and Events -> Services
        "sales": "Services",  # Backward compatibility
        "purchase": "Products",  # Backward compatibility
    }

    # Keywords for enhanced categorization
    ITEM_GROUP_KEYWORDS = {
        "travel": ["reis", "travel", "transport", "hotel", "accommodation", "trein", "vliegtuig"],
        "marketing": ["marketing", "advertis", "promotional", "poster", "flyer", "banner", "reclame"],
        "office": ["kantoor", "office", "supplies", "stationary", "pen", "paper", "papier"],
        "finance": ["bank", "transaction", "fee", "kosten", "sisow", "payment", "betaal"],
        "catering": ["catering", "restaurant", "diner", "lunch", "food", "eten", "meal"],
        "utility": ["electric", "gas", "water", "internet", "phone", "telefoon"],
        "subscription": ["subscription", "license", "software", "saas", "service"],
    }

    if description:
        description_lower = description.lower()

        # Priority 1: Check description keywords (most specific)
        for group, keywords in ITEM_GROUP_KEYWORDS.items():
            if any(keyword in description_lower for keyword in keywords):
                return SAFE_ITEM_GROUPS.get(group, "Services")

    # Priority 2: Use account information if available
    if account_info:
        if account_info.root_type == "Income":
            return "Services"  # Income typically services
        elif account_info.root_type == "Expense":
            return "Expense Items"
        elif account_info.root_type == "Asset":
            return "Products"

    # Priority 3: Use price range hints if available
    if price:
        price_float = flt(price)
        if 0 < price_float <= 50:  # Small amounts
            return "Consumable"
        elif price_float > 500:  # Large amounts
            return "Products"

    # Default fallback to Services
    return "Services"


def get_or_create_item_improved(
    account_code, company, transaction_type="Both", description=None, btw_code=None, price=None, unit="Unit"
):
    """
    Enhanced item creation with smart categorization and mapping integration

    Args:
        account_code: E-boekhouden account code (grootboekrekening)
        company: Company name
        transaction_type: "Sales", "Purchase", or "Both"
        description: Transaction description for enhanced categorization
        btw_code: VAT code for smart categorization
        price: Price for category determination
        unit: Unit of measure for mapping

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

    # Step 1: Check for existing item by description (enhanced approach)
    if description:
        existing_by_desc = frappe.db.get_value("Item", {"description": description}, "name")
        if existing_by_desc:
            frappe.logger().info(
                f"E-Boekhouden Item Creation: Found existing item by description: {existing_by_desc}"
            )
            return existing_by_desc

    # Step 2: Check if there's a mapping in the DocType
    from verenigingen.e_boekhouden.doctype.e_boekhouden_item_mapping.e_boekhouden_item_mapping import (
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
        # Don't log this as an error since most accounts won't have mappings
        frappe.logger().debug(f"No item mapping found for account {account_code}: {str(e)}")

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

    # Step 3: Generate item code and apply smart categorization
    if description:
        # Use description for more meaningful item code
        clean_desc = "".join(c for c in description if c.isalnum() or c in " -_").strip()
        clean_desc = clean_desc.replace(" ", "-").upper()[:30]
        item_code = f"EBH-{clean_desc}"
    else:
        item_code = item_name

    # Check if item already exists by code
    if frappe.db.exists("Item", item_code):
        frappe.logger().info(f"E-Boekhouden Item Creation: Item '{item_code}' already exists, reusing")
        return item_code

    # Also check by name for backward compatibility
    if frappe.db.exists("Item", item_name):
        frappe.logger().info(f"E-Boekhouden Item Creation: Item '{item_name}' already exists, reusing")
        return item_name

    # Step 4: Smart item group determination
    item_group = determine_smart_item_group(description, btw_code, account_code, price, account_info)

    # Create new item with enhanced categorization
    try:
        item = frappe.new_doc("Item")
        item.item_code = item_code  # Use the clean generated code
        item.item_name = description[:140] if description else item_name  # Use description for name
        item.description = description if description else item_name
        item.item_group = item_group  # Use smart categorization

        # Enhanced UOM assignment
        item.stock_uom = map_unit_of_measure(unit) if unit else "Unit"

        # Smart stock item determination based on group
        if item_group in ["Products", "Consumable"]:
            item.is_stock_item = 1
            item.maintain_stock = 1
            item.valuation_method = "FIFO"
        else:
            item.is_stock_item = 0
            item.maintain_stock = 0

        # Set sales/purchase flags based on transaction type
        if transaction_type in ["Sales", "Both"]:
            item.is_sales_item = 1
        if transaction_type in ["Purchase", "Both"]:
            item.is_purchase_item = 1

        # Add metadata for E-Boekhouden items
        if hasattr(item, "custom_eboekhouden_account_code"):
            item.custom_eboekhouden_account_code = str(account_code)

        item.insert()
        frappe.logger().info(
            f"E-Boekhouden Item Creation: Successfully created item '{item_code}' with group '{item_group}' for account {account_code}"
        )
        return item_code

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
