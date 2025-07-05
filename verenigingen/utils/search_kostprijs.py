"""
Search for Kostprijs omzet grondstoffen reference
"""

import frappe


@frappe.whitelist()
def search_kostprijs_reference():
    """Search for the mysterious Kostprijs omzet grondstoffen text"""

    results = {"accounts": [], "items": [], "item_defaults": [], "text_search": []}

    # Search in accounts
    accounts = frappe.db.sql(
        """
        SELECT name, account_name, account_number, eboekhouden_grootboek_nummer
        FROM `tabAccount`
        WHERE account_name LIKE '%kostprijs%'
           OR account_name LIKE '%omzet%'
           OR account_name LIKE '%grondstoffen%'
        LIMIT 20
    """,
        as_dict=True,
    )
    results["accounts"] = accounts

    # Search in items
    items = frappe.db.sql(
        """
        SELECT name, item_name, item_code, description
        FROM `tabItem`
        WHERE item_name LIKE '%kostprijs%'
           OR item_name LIKE '%omzet%'
           OR item_name LIKE '%grondstoffen%'
           OR description LIKE '%kostprijs%'
        LIMIT 20
    """,
        as_dict=True,
    )
    results["items"] = items

    # Search in item defaults for any expense accounts containing these words
    item_defaults = frappe.db.sql(
        """
        SELECT parent as item, expense_account, income_account
        FROM `tabItem Default`
        WHERE expense_account LIKE '%kostprijs%'
           OR expense_account LIKE '%omzet%'
           OR expense_account LIKE '%grondstoffen%'
        LIMIT 20
    """,
        as_dict=True,
    )
    results["item_defaults"] = item_defaults

    # Test creating a simple Sales Invoice to see where the error comes from
    try:
        # Create test sales invoice
        si = frappe.new_doc("Sales Invoice")
        si.company = "Ned Ver Vegan"
        si.posting_date = "2024-01-01"

        # Get or create a customer
        customer = frappe.db.get_value("Customer", {"customer_group": "All Customer Groups"}, "name")
        if not customer:
            # Create a test customer
            cust = frappe.new_doc("Customer")
            cust.customer_name = "Test Customer"
            cust.customer_group = "All Customer Groups"
            cust.territory = "All Territories"
            cust.save(ignore_permissions=True)
            customer = cust.name

        si.customer = customer

        # Get the EB-80010 item that should exist
        item_code = "EB-80010"
        if not frappe.db.exists("Item", item_code):
            # Create it with smart mapper
            from verenigingen.utils.smart_tegenrekening_mapper import SmartTegenrekeningMapper

            mapper = SmartTegenrekeningMapper()
            item_result = mapper.get_item_for_tegenrekening("80010", "Test item", "sales", 100)
            if item_result:
                item_code = item_result.get("item_code", "E-Boekhouden Import Item")

        # Add the item
        si.append("items", {"item_code": item_code, "qty": 1, "rate": 100})

        # Try to save
        si.save()

        results["test_invoice"] = {"success": True, "invoice_name": si.name, "item_used": item_code}

    except Exception as e:
        results["test_invoice"] = {"success": False, "error": str(e), "traceback": frappe.get_traceback()}

    # Check if there's a translation or label containing this text
    translations = frappe.db.sql(
        """
        SELECT source_text, translated_text
        FROM `tabTranslation`
        WHERE source_text LIKE '%kostprijs%'
           OR translated_text LIKE '%kostprijs%'
           OR source_text LIKE '%expense account%'
           OR translated_text LIKE '%expense account%'
        LIMIT 10
    """,
        as_dict=True,
    )
    results["translations"] = translations

    # Check Properties/Property Setters
    property_setters = frappe.db.sql(
        """
        SELECT doc_type, field_name, property, value
        FROM `tabProperty Setter`
        WHERE value LIKE '%kostprijs%'
           OR value LIKE '%expense%'
        LIMIT 10
    """,
        as_dict=True,
    )
    results["property_setters"] = property_setters

    return results


@frappe.whitelist()
def test_minimal_sales_invoice():
    """Test creating the most minimal sales invoice possible"""

    try:
        # Get basic requirements
        company = "Ned Ver Vegan"

        # Get any existing customer
        customer = frappe.db.get_value("Customer", {}, "name")
        if not customer:
            return {"error": "No customers found"}

        # Get a basic item
        item = frappe.db.get_value("Item", {"is_sales_item": 1}, "name")
        if not item:
            item = "E-Boekhouden Import Item"

        # Create invoice
        si = frappe.new_doc("Sales Invoice")
        si.company = company
        si.customer = customer
        si.posting_date = frappe.utils.today()

        # Add item with minimal fields
        si.append("items", {"item_code": item, "qty": 1, "rate": 10})

        # Try save without validation
        si.flags.ignore_validate = True
        si.save()

        return {"success": True, "invoice": si.name, "customer": customer, "item": item}

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "short_error": str(e).split("\n")[0] if "\n" in str(e) else str(e),
        }
