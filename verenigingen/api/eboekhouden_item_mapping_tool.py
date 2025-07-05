import frappe


@frappe.whitelist()
def get_unmapped_accounts(company):
    """Get E-boekhouden accounts that don't have item mappings yet"""
    frappe.set_user("Administrator")

    try:
        # Get all accounts with account numbers
        all_accounts = frappe.db.sql(
            """
            SELECT
                a.account_number as account_code,
                a.account_name,
                a.account_type,
                a.root_type
            FROM `tabAccount` a
            WHERE a.company = %s
            AND a.account_number IS NOT NULL
            AND a.account_number != ''
            AND a.is_group = 0
            AND a.root_type IN ('Income', 'Expense')
            ORDER BY a.account_number
        """,
            company,
            as_dict=True,
        )

        # Get existing mappings
        mapped_accounts = frappe.db.sql_list(
            """
            SELECT DISTINCT account_code
            FROM `tabE-Boekhouden Item Mapping`
            WHERE company = %s
        """,
            company,
        )

        # Filter unmapped accounts
        unmapped = []
        for account in all_accounts:
            if account.account_code not in mapped_accounts:
                # Add suggested item based on account name
                account["suggested_item"] = suggest_item_name(account)
                unmapped.append(account)

        return {"success": True, "accounts": unmapped, "total": len(unmapped)}

    except Exception as e:
        frappe.log_error(f"Error getting unmapped accounts: {str(e)}")
        return {"success": False, "error": str(e)}


def suggest_item_name(account):
    """Suggest an item name based on account information"""
    account_name = account.get("account_name", "").lower()

    # Common patterns
    suggestions = {
        # Income
        "contributie": "Membership Contribution",
        "donatie": "Donation",
        "verkoop": "Product Sales",
        "advertentie": "Advertisement Income",
        "commissie": "Commission Income",
        "rente": "Interest Income",
        "subsidie": "Subsidy Income",
        "fondsen": "Fund Income",
        "evenement": "Event Income",
        "tickets": "Event Tickets",
        "webshop": "Webshop Sales",
        # Expenses
        "lonen": "Salary Expense",
        "sociale lasten": "Social Security",
        "vakantiegeld": "Holiday Allowance",
        "huur": "Rent Expense",
        "telefoon": "Telephone Expense",
        "internet": "Internet Expense",
        "verzekering": "Insurance",
        "administratie": "Administration",
        "bank": "Bank Charges",
        "drukwerk": "Printing",
        "porto": "Postage",
        "kantoor": "Office Supplies",
        "reis": "Travel Expense",
        "marketing": "Marketing",
        "accountant": "Accounting Fees",
        "afschrijving": "Depreciation",
        "energie": "Utilities",
        "onderhoud": "Maintenance",
        "licentie": "License Fees",
        "abonnement": "Subscriptions",
        "representatie": "Entertainment",
        "advies": "Consultancy",
        "juridisch": "Legal Fees",
    }

    # Check for matches
    for pattern, suggestion in suggestions.items():
        if pattern in account_name:
            return suggestion

    # Clean up account name as fallback
    from verenigingen.utils.eboekhouden_improved_item_naming import clean_item_name

    cleaned = clean_item_name(account.get("account_name", ""))

    # Don't suggest if it's too generic
    if cleaned and len(cleaned) > 3 and not cleaned.isdigit():
        return cleaned

    return None


@frappe.whitelist()
def create_mapping(company, account_code, account_name, item_code, transaction_type="Both"):
    """Create a new item mapping"""
    frappe.set_user("Administrator")

    try:
        # Check if item needs to be created
        if item_code.startswith("[CREATE]"):
            item_name = item_code.replace("[CREATE]", "")

            # Create item if it doesn't exist
            if not frappe.db.exists("Item", item_name):
                item = frappe.new_doc("Item")
                item.item_code = item_name
                item.item_name = item_name
                item.item_group = "Services"
                item.stock_uom = "Nos"
                item.is_stock_item = 0
                item.description = f"Created for E-boekhouden account {account_code} - {account_name}"
                item.insert(ignore_permissions=True)

            item_code = item_name

        # Create mapping
        mapping = frappe.new_doc("E-Boekhouden Item Mapping")
        mapping.company = company
        mapping.account_code = account_code
        mapping.account_name = account_name
        mapping.item_code = item_code
        mapping.transaction_type = transaction_type
        mapping.is_active = 1
        mapping.insert(ignore_permissions=True)

        frappe.db.commit()

        return {"success": True, "mapping": mapping.name}

    except Exception as e:
        frappe.log_error(f"Error creating mapping: {str(e)}")
        return {"success": False, "error": str(e)}
