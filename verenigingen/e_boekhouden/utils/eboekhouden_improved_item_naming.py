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

    # Step 1: Bank Cost Pattern Detection (check first, higher priority)
    if _is_bank_cost_transaction(description, account_code):
        # For bank costs, use a standardized bank cost item
        bank_cost_item = get_or_create_bank_cost_item(company)
        frappe.logger().info(
            f"E-Boekhouden Item Creation: Using Bank Cost item for bank fee: {bank_cost_item}"
        )
        return bank_cost_item

    # Step 2: Row-level pattern detection for WooCommerce sales
    if _is_event_ticket_row(description, account_code, price):
        # For event ticket sales rows, use standardized item
        event_ticket_item = get_or_create_event_ticket_item(company)
        frappe.logger().info(
            f"E-Boekhouden Item Creation: Using Event Ticket item for product sale: {event_ticket_item}"
        )
        return event_ticket_item

    # Step 2: Check for existing item by description (enhanced approach)
    if description:
        existing_by_desc = frappe.db.get_value("Item", {"description": description}, "name")
        if existing_by_desc:
            frappe.logger().info(
                f"E-Boekhouden Item Creation: Found existing item by description: {existing_by_desc}"
            )
            return existing_by_desc

    # Step 3: Check if there's a mapping in the DocType
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

    # Step 4: Generate item code and apply smart categorization
    if description:
        # For descriptions, do minimal cleaning - just make it safe for item codes
        import re

        clean_desc = description.strip()
        # Remove any existing prefixes to avoid double prefixes
        clean_desc = re.sub(r"^(EBH-|ebh-)", "", clean_desc, flags=re.IGNORECASE)
        # Make safe for item code (keep alphanumeric, spaces, hyphens, underscores)
        clean_desc = "".join(c for c in clean_desc if c.isalnum() or c in " -_").strip()
        clean_desc = clean_desc.replace(" ", "-").upper()[:40]  # Allow longer item codes
        item_code = clean_desc  # Use description alone, no prefix
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

    # Step 5: Smart item group determination
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

        # Create Item Defaults with proper account mapping instead of fallback
        try:
            # Get the mapped ERPNext account for this eBoekhouden account
            from verenigingen.e_boekhouden.utils.invoice_helpers import map_grootboek_to_erpnext_account

            mapped_account = None
            if account_code:
                debug_info = []
                try:
                    mapped_account = map_grootboek_to_erpnext_account(
                        account_code, transaction_type.lower(), debug_info, allow_fallback=False
                    )
                except Exception as e:
                    frappe.logger().debug(f"No account mapping found for {account_code}: {str(e)}")
                    mapped_account = None

            # Only create Item Defaults if we have a proper account mapping
            if mapped_account:
                # Check if Item Default already exists
                existing_default = frappe.db.exists("Item Default", {"parent": item_code, "company": company})

                if not existing_default:
                    item_default = frappe.new_doc("Item Default")
                    item_default.parent = item_code
                    item_default.parenttype = "Item"
                    item_default.parentfield = "item_defaults"
                    item_default.company = company

                    # Set the appropriate account based on transaction type
                    if transaction_type in ["Sales", "Both"]:
                        item_default.income_account = mapped_account
                    if transaction_type in ["Purchase", "Both"]:
                        item_default.expense_account = mapped_account

                    item_default.insert()
                    frappe.logger().info(
                        f"E-Boekhouden Item Creation: Created Item Default for '{item_code}' with {transaction_type.lower()}_account: {mapped_account}"
                    )
                else:
                    frappe.logger().debug(f"Item Default already exists for {item_code}")
            else:
                frappe.logger().warning(
                    f"E-Boekhouden Item Creation: No account mapping found for account {account_code}, item '{item_code}' created without default accounts"
                )

        except Exception as e:
            frappe.logger().error(f"Failed to create Item Default for {item_code}: {str(e)}")
            # Don't fail the item creation if Item Default creation fails

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
    """Clean account name to make a valid item name

    Note: This function is specifically for cleaning ACCOUNT NAMES,
    not invoice descriptions. Invoice descriptions should be preserved as-is.
    """
    import re

    cleaned = account_name.strip()

    # Remove account number prefixes if present
    cleaned = re.sub(r"^\d+\s*-\s*", "", cleaned)

    # Remove company abbreviations
    cleaned = re.sub(r"\s*-\s*[A-Z]{2,4}$", "", cleaned)

    # Remove "EBH-" prefix if already present to avoid double prefixes
    cleaned = re.sub(r"^EBH-", "", cleaned)

    # For complex patterns like "EBH-VIRTUAL-SERVER-ID-12381564-MAA: Virtual Server ID: 12381564, maand januari"
    # Extract the meaningful part after the colon if present
    if ":" in cleaned:
        # Split on colon and process each part
        parts = cleaned.split(":", 1)
        if len(parts) == 2:
            prefix_part = parts[0].strip()
            description_part = parts[1].strip()

            # Remove redundant ID patterns from description
            description_part = re.sub(r"Virtual Server ID:\s*\d+,?\s*", "", description_part)
            description_part = re.sub(r"ID:\s*\d+,?\s*", "", description_part)
            description_part = re.sub(r",?\s*maand\s+\w+$", "", description_part)

            # If description part has meaningful content, use it; otherwise use prefix
            if (
                description_part
                and len(description_part.strip()) > 3
                and not description_part.strip().lower() in ["service", "item"]
            ):
                cleaned = description_part.strip()
            else:
                # Clean up the prefix part by removing redundant patterns
                prefix_part = re.sub(r"-ID-\d+", "", prefix_part)
                prefix_part = re.sub(r"EBH-VIRTUAL-SERVER", "Virtual-Server", prefix_part)
                prefix_part = re.sub(r"-MAA$", "", prefix_part)
                cleaned = prefix_part.strip()
    else:
        # For simple patterns without colon, just clean basic redundancies
        cleaned = re.sub(r"Virtual Server ID:\s*\d+,?\s*", "", cleaned)
        cleaned = re.sub(r"ID:\s*\d+,?\s*", "", cleaned)
        cleaned = re.sub(r",?\s*maand\s+\w+$", "", cleaned)

    # Final cleanup
    cleaned = re.sub(r"^[:\-,\s]+", "", cleaned)  # Remove leading punctuation
    cleaned = re.sub(r"[:\-,\s]+$", "", cleaned)  # Remove trailing punctuation

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


def _is_event_ticket_row(description, account_code, price):
    """
    Detect if a row represents the main product sale (event tickets) in WooCommerce

    Simple logic: if it's not bank costs, and has substantial value, it's likely the main product
    """
    # If it's already detected as bank costs, it's not an event ticket
    if _is_bank_cost_transaction(description, account_code):
        return False

    # If price is provided, use it as signal
    # Event tickets typically have substantial amounts (> €1.00)
    if price and float(price) > 1.0:
        return True

    # For small amounts that aren't bank costs, still could be event tickets
    return True


def _is_bank_cost_transaction(description, account_code):
    """
    Detect if a transaction represents bank costs/fees

    Check both description and account code (via account mapping lookup) for bank cost patterns
    """
    if not description and not account_code:
        return False

    # Check description patterns
    if description:
        description_lower = description.lower()
        description_patterns = [
            "bankkosten",
            "bank charges",
            "bank fee",
            "banking fees",
            "bank cost",
            "transaction fee",
            "transactiekosten",
            "provisie bank",
            "bank commission",
        ]

        if any(pattern in description_lower for pattern in description_patterns):
            return True

    # Check account code by looking up the ledger name from E-Boekhouden Ledger Mapping
    if account_code:
        try:
            # Look up the ledger name from E-Boekhouden Ledger Mapping table
            ledger_mapping = frappe.db.sql(
                """
                SELECT ledger_name, ledger_code, erpnext_account
                FROM `tabE-Boekhouden Ledger Mapping`
                WHERE ledger_id = %s
                LIMIT 1
            """,
                [str(account_code)],
            )

            if ledger_mapping and ledger_mapping[0]:
                ledger_name = ledger_mapping[0][0] or ""
                ledger_code = ledger_mapping[0][1] or ""
                erpnext_account = ledger_mapping[0][2] or ""

                frappe.logger().info(
                    f"E-Boekhouden Bank Cost Check: Found ledger '{ledger_name}' (code: {ledger_code}) for id {account_code}"
                )

                # Check if the ledger name contains bank cost indicators
                bank_cost_patterns = ["bankkosten", "bank cost", "bank fee", "banking fee", "transaction fee"]

                ledger_name_lower = ledger_name.lower()
                for pattern in bank_cost_patterns:
                    if pattern in ledger_name_lower:
                        frappe.logger().info(
                            f"E-Boekhouden Bank Cost: Detected pattern '{pattern}' in ledger name '{ledger_name}'"
                        )
                        return True

                # Also check the ERPNext account name if available
                if erpnext_account:
                    erpnext_account_lower = erpnext_account.lower()
                    for pattern in bank_cost_patterns:
                        if pattern in erpnext_account_lower:
                            frappe.logger().info(
                                f"E-Boekhouden Bank Cost: Detected pattern '{pattern}' in ERPNext account '{erpnext_account}'"
                            )
                            return True
            else:
                frappe.logger().info(
                    f"E-Boekhouden Bank Cost Check: No ledger mapping found for id {account_code}"
                )

        except Exception as e:
            # If lookup fails, log the error
            frappe.logger().error(f"Failed to lookup ledger for {account_code}: {e}")
            pass

    return False


def get_or_create_bank_cost_item(company):
    """
    Get or create a standardized Bank Costs item
    """
    item_code = "Bank-Costs"
    item_name = "Bank Costs"

    # Check if item already exists
    if frappe.db.exists("Item", item_code):
        frappe.logger().info(f"E-Boekhouden Bank Costs: Using existing item: {item_code}")
        return item_code

    # Create new bank costs item
    try:
        item = frappe.new_doc("Item")
        item.item_code = item_code
        item.item_name = item_name
        item.description = "Bank transaction fees and costs"

        # Set appropriate item group
        if frappe.db.exists("Item Group", "Banking"):
            item.item_group = "Banking"
        elif frappe.db.exists("Item Group", "Services"):
            item.item_group = "Services"
        else:
            # Use any available non-group item group as fallback
            item.item_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "Services"

        item.stock_uom = "Unit"
        item.is_stock_item = 0  # Service item, not tracked inventory
        item.maintain_stock = 0
        item.is_sales_item = 1  # Can appear on sales invoices (as negative fees)
        item.is_purchase_item = 1  # Can appear on purchase invoices (as expenses)

        # Add metadata for E-Boekhouden items
        if hasattr(item, "custom_eboekhouden_account_code"):
            item.custom_eboekhouden_account_code = "BANK_COSTS"

        item.insert()

        frappe.logger().info(f"E-Boekhouden Bank Costs: Created item: {item_code}")
        return item_code

    except Exception as e:
        frappe.log_error(
            title="E-Boekhouden Bank Costs: Item Creation Failed",
            message=f"Failed to create Bank Costs item: {str(e)}. Falling back to generic item creation.",
        )
        # Fallback to generic item creation
        return get_or_create_generic_item(company)


def get_or_create_event_ticket_item(company):
    """
    Get or create a standardized Event Ticket item for WooCommerce imports
    """
    item_code = "Event-Ticket"
    item_name = "Event Ticket"

    # Check if item already exists
    if frappe.db.exists("Item", item_code):
        frappe.logger().info(f"E-Boekhouden WooCommerce: Using existing Event Ticket item: {item_code}")
        return item_code

    # Create new event ticket item
    try:
        item = frappe.new_doc("Item")
        item.item_code = item_code
        item.item_name = item_name
        item.description = "Event tickets sold through WooCommerce"

        # Set appropriate item group - try Event Items first, fallback to Services
        if frappe.db.exists("Item Group", "Event Items"):
            item.item_group = "Event Items"
        elif frappe.db.exists("Item Group", "Services"):
            item.item_group = "Services"
        else:
            # Use any available non-group item group as fallback
            item.item_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "Services"

        item.stock_uom = "Unit"
        item.is_stock_item = 0  # Service item, not tracked inventory
        item.maintain_stock = 0
        item.is_sales_item = 1  # Event tickets are sold
        item.is_purchase_item = 0  # We don't purchase event tickets

        # Add metadata for E-Boekhouden items
        if hasattr(item, "custom_eboekhouden_account_code"):
            item.custom_eboekhouden_account_code = "WOOCOMMERCE_EVENT"

        item.insert()

        frappe.logger().info(f"E-Boekhouden WooCommerce: Created Event Ticket item: {item_code}")
        return item_code

    except Exception as e:
        frappe.log_error(
            title="E-Boekhouden WooCommerce: Event Ticket Item Creation Failed",
            message=f"Failed to create Event Ticket item: {str(e)}. Falling back to generic item creation.",
        )
        # Fallback to generic item creation
        return get_or_create_generic_item(company)
