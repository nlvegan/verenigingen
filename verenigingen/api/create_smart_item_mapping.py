import frappe


@frappe.whitelist()
def create_smart_item_mapping_system():
    """Create a comprehensive item mapping system for E-Boekhouden accounts"""
    try:
        response = []
        response.append("=== CREATING SMART ITEM MAPPING SYSTEM ===")

        # Get existing ERPNext accounts with E-Boekhouden codes
        existing_accounts = frappe.db.sql(
            """
            SELECT name, account_name, account_type, root_type, eboekhouden_grootboek_nummer
            FROM `tabAccount`
            WHERE company = 'Ned Ver Vegan'
            AND eboekhouden_grootboek_nummer IS NOT NULL
            AND eboekhouden_grootboek_nummer != ''
            ORDER BY eboekhouden_grootboek_nummer
        """,
            as_dict=True,
        )

        response.append(f"Found {len(existing_accounts)} ERPNext accounts with E-Boekhouden codes")

        # Create intelligent item mappings
        item_mappings = []

        # Dutch accounting patterns for intelligent naming
        income_patterns = {
            "contributie": "Membership Contributions",
            "donatie": "Donations",
            "subsidie": "Grants and Subsidies",
            "verkoop": "Product Sales",
            "advertentie": "Advertising Revenue",
            "rente": "Interest Income",
            "commissie": "Commission Income",
            "opbrengst": "Revenue",
            "inkomst": "Income",
        }

        expense_patterns = {
            "loon": "Salary and Wages",
            "huur": "Rent Expenses",
            "kantoor": "Office Expenses",
            "reis": "Travel Expenses",
            "marketing": "Marketing Services",
            "telefoon": "Communication Expenses",
            "verzekering": "Insurance",
            "accountant": "Professional Services",
            "software": "Software and IT",
            "materiaal": "Materials",
            "kosten": "General Expenses",
            "afschrijving": "Depreciation",
        }

        for account in existing_accounts:
            eb_code = account.eboekhouden_grootboek_nummer
            account_name = account.account_name.lower()
            account_type = account.account_type
            root_type = account.root_type

            # Generate intelligent item name
            item_name = None
            item_code = f"EB-{eb_code}"
            is_sales_item = 0
            is_purchase_item = 0
            item_group = "E-Boekhouden Import"

            # Clean account name (remove company suffix and code prefix)
            clean_name = account.account_name
            clean_name = clean_name.replace(" - NVV", "")
            clean_name = clean_name.replace(f"{eb_code} - ", "")

            if account_type == "Income Account" or root_type == "Income":
                is_sales_item = 1
                item_group = "Revenue Items"

                # Check for known income patterns
                for pattern, suggested_name in income_patterns.items():
                    if pattern in account_name:
                        item_name = suggested_name
                        break

                if not item_name:
                    # Use cleaned account name
                    item_name = clean_name
                    if not item_name.endswith(("Income", "Revenue")):
                        item_name += " Revenue"

            elif account_type == "Expense Account" or root_type == "Expense":
                is_purchase_item = 1
                item_group = "Expense Items"

                # Check for known expense patterns
                for pattern, suggested_name in expense_patterns.items():
                    if pattern in account_name:
                        item_name = suggested_name
                        break

                if not item_name:
                    # Use cleaned account name
                    item_name = clean_name
                    if not item_name.endswith(("Expense", "Cost", "Service")):
                        item_name += " Expense"

            else:
                # For other account types, create generic items but mark them differently
                item_name = clean_name
                item_group = "Other"
                if root_type == "Asset":
                    item_name += " (Asset)"
                elif root_type == "Liability":
                    item_name += " (Liability)"

            # Ensure item name is not too long
            if len(item_name) > 60:
                item_name = item_name[:57] + "..."

            mapping = {
                "account_code": eb_code,
                "account_name": account.account_name,
                "account_type": account_type,
                "root_type": root_type,
                "erpnext_account": account.name,
                "item_code": item_code,
                "item_name": item_name,
                "item_group": item_group,
                "is_sales_item": is_sales_item,
                "is_purchase_item": is_purchase_item,
            }

            item_mappings.append(mapping)

        # Sort by account code
        item_mappings.sort(key=lambda x: x["account_code"])

        # Display mappings by category
        categories = {"Revenue Items": [], "Expense Items": [], "Other": []}

        for mapping in item_mappings:
            categories[mapping["item_group"]].append(mapping)

        for category, mappings in categories.items():
            if mappings:
                response.append(f"\n=== {category.upper()} ===")
                for mapping in mappings:
                    response.append(f"Account: {mapping['account_code']} - {mapping['account_name']}")
                    response.append(f"  → Item: {mapping['item_code']} - {mapping['item_name']}")
                    response.append(f"  Group: {mapping['item_group']}")
                    if mapping["is_sales_item"]:
                        response.append("  Type: Sales Item")
                    elif mapping["is_purchase_item"]:
                        response.append("  Type: Purchase Item")
                    response.append("")

        # Store mappings for next phase
        frappe.cache().set_value("smart_item_mappings", item_mappings, expires_in_sec=3600)

        response.append("\n=== SUMMARY ===")
        response.append(f"Total mappings created: {len(item_mappings)}")
        response.append(f"Revenue items: {len(categories['Revenue Items'])}")
        response.append(f"Expense items: {len(categories['Expense Items'])}")
        response.append(f"Other items: {len(categories['Other'])}")

        return "\n".join(response)

    except Exception as e:
        return f"Error: {e}\n{frappe.get_traceback()}"


@frappe.whitelist()
def create_items_from_mappings():
    """Create actual ERPNext items based on the smart mappings"""
    try:
        response = []
        response.append("=== CREATING ITEMS FROM MAPPINGS ===")

        # Get cached mappings
        mappings = frappe.cache().get_value("smart_item_mappings")
        if not mappings:
            response.append("No mappings found. Please run create_smart_item_mapping_system first.")
            return "\n".join(response)

        # Create item groups first
        item_groups = ["Revenue Items", "Expense Items", "E-Boekhouden Import"]

        for group_name in item_groups:
            if not frappe.db.exists("Item Group", group_name):
                group = frappe.new_doc("Item Group")
                group.item_group_name = group_name
                group.parent_item_group = "All Item Groups"
                group.insert(ignore_permissions=True)
                response.append(f"Created item group: {group_name}")

        # Create items
        created_count = 0
        updated_count = 0
        errors = []

        for mapping in mappings:
            try:
                item_code = mapping["item_code"]

                # Check if item already exists
                if frappe.db.exists("Item", item_code):
                    # Update existing item
                    item = frappe.get_doc("Item", item_code)
                    item.item_name = mapping["item_name"]
                    item.item_group = mapping["item_group"]
                    item.is_sales_item = mapping["is_sales_item"]
                    item.is_purchase_item = mapping["is_purchase_item"]

                    # Set default accounts
                    if mapping["is_sales_item"]:
                        item.income_account = mapping["erpnext_account"]
                    elif mapping["is_purchase_item"]:
                        item.expense_account = mapping["erpnext_account"]

                    item.save(ignore_permissions=True)
                    updated_count += 1

                else:
                    # Create new item
                    item = frappe.new_doc("Item")
                    item.item_code = item_code
                    item.item_name = mapping["item_name"]
                    item.item_group = mapping["item_group"]
                    item.stock_uom = "Nos"
                    item.is_stock_item = 0
                    item.is_sales_item = mapping["is_sales_item"]
                    item.is_purchase_item = mapping["is_purchase_item"]

                    # Set default accounts
                    if mapping["is_sales_item"]:
                        item.income_account = mapping["erpnext_account"]
                    elif mapping["is_purchase_item"]:
                        item.expense_account = mapping["erpnext_account"]

                    # Add custom field for E-Boekhouden account code
                    item.custom_eboekhouden_account_code = mapping["account_code"]

                    item.insert(ignore_permissions=True)
                    created_count += 1

                if (created_count + updated_count) % 10 == 0:
                    response.append(f"Processed {created_count + updated_count} items...")

            except Exception as e:
                error_msg = f"Error creating item for account {mapping['account_code']}: {str(e)}"
                errors.append(error_msg)
                continue

        frappe.db.commit()

        response.append("\n=== RESULTS ===")
        response.append(f"Items created: {created_count}")
        response.append(f"Items updated: {updated_count}")
        response.append(f"Errors: {len(errors)}")

        if errors:
            response.append("\nErrors encountered:")
            for error in errors[:5]:  # Show first 5 errors
                response.append(f"  - {error}")

        return "\n".join(response)

    except Exception as e:
        return f"Error: {e}\n{frappe.get_traceback()}"


@frappe.whitelist()
def create_tegenrekening_mapping_helper():
    """Create a helper function for mapping tegenrekening codes to items during migration"""

    # This will be used in the migration code
    # mapping_code = '''  # Removed unused variable - full string commented out
    # def get_item_for_tegenrekening(account_code, description="", transaction_type="purchase"):
    #     """
    #     Get or create appropriate item for a tegenrekening (contra account)
    #
    #     Args:
    #         account_code: E-Boekhouden account code
    #         description: Transaction description
    #         transaction_type: "purchase" or "sales"
    #
    #     Returns:
    #         item_code: ERPNext item code to use
    #     """
    #
    #     # First, try to find item with matching E-Boekhouden account code
    #     item_code = f"EB-{account_code}"
    #
    #     if frappe.db.exists("Item", item_code):
    #         return item_code
    #
    #     # If not found, try to find by account mapping
    #     account_name = frappe.db.get_value("Account", {
    #         "company": company,
    #         "eboekhouden_grootboek_nummer": account_code
    #     }, "name")
    #
    #     if account_name:
    #         # Account exists, create item dynamically
    #         item = frappe.new_doc("Item")
    #         item.item_code = item_code
    #         item.item_name = f"Account {account_code} Transaction"
    #         item.item_group = "E-Boekhouden Import"
    #         item.stock_uom = "Nos"
    #         item.is_stock_item = 0
    #
    #         if transaction_type == "sales":
    #             item.is_sales_item = 1
    #             item.income_account = account_name
    #         else:
    #             item.is_purchase_item = 1
    #             item.expense_account = account_name
    #
    #         item.insert(ignore_permissions=True)
    #         return item_code
    #
    #     # Fallback to generic item
    #     return "E-BOEKHOUDEN-GENERIC"
    # '''  # End of commented mapping_code

    return """
=== TEGENREKENING MAPPING HELPER CREATED ===

This helper function should be added to your migration utility:

{mapping_code}

Usage in migration:
```python
# In purchase invoice creation
item_code = get_item_for_tegenrekening(
    regel.get("TegenrekeningCode"),
    mut.get("Omschrijving"),
    "purchase"
)

pi.append("items", {{
    "item_code": item_code,
    "qty": 1,
    "rate": amount,
    "cost_center": cost_center
}})
```

This approach:
✅ Uses pre-created items when available
✅ Creates items dynamically for unmapped accounts
✅ Maintains proper account linkage
✅ Handles both sales and purchase scenarios
"""
