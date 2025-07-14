"""
E-Boekhouden Import Utilities
Supporting functions for proper data mapping and creation
"""

import re

import frappe
from frappe.utils import cstr


def clean_description_for_item_code(description: str) -> str:
    """Clean description to create valid item code"""
    if not description:
        return "SERVICE-ITEM"

    # Remove special characters and limit length
    cleaned = re.sub(r"[^a-zA-Z0-9\s\-]", "", description)
    cleaned = re.sub(r"\s+", "-", cleaned.strip())
    cleaned = cleaned.upper()[:20]  # ERPNext item code limit

    if not cleaned:
        return "SERVICE-ITEM"

    return cleaned


def determine_item_group_from_description(description: str) -> str:
    """Determine item group based on description keywords"""
    if not description:
        return "Services"

    description_lower = description.lower()

    # Service keywords
    service_keywords = ["service", "dienst", "advies", "consultancy", "onderhoud", "reparatie"]
    if any(keyword in description_lower for keyword in service_keywords):
        return "Services"

    # Product keywords
    product_keywords = ["product", "artikel", "materiaal", "onderdeel"]
    if any(keyword in description_lower for keyword in product_keywords):
        return "Products"

    # Default to services
    return "Services"


def map_grootboek_to_erpnext_account(grootboek_nr: str, transaction_type: str, company: str) -> str:
    """Map e-boekhouden Grootboek number to ERPNext account"""
    if not grootboek_nr:
        return None

    # Check if we have a mapping
    mapped_account = frappe.db.get_value(
        "E-Boekhouden Account Map", {"eboekhouden_grootboek": grootboek_nr}, "erpnext_account"
    )

    if mapped_account:
        return mapped_account

    # Try to find account by number in account name
    account = frappe.db.get_value(
        "Account", {"company": company, "account_name": ["like", f"%{grootboek_nr}%"]}, "name"
    )

    if account:
        # Create mapping for future use
        create_account_mapping(grootboek_nr, account)
        return account

    # Create new account if needed
    return create_account_from_grootboek(grootboek_nr, transaction_type, company)


def create_account_mapping(grootboek_nr: str, erpnext_account: str):
    """Create account mapping for future lookups"""
    try:
        mapping = frappe.new_doc("E-Boekhouden Account Map")
        mapping.eboekhouden_grootboek = grootboek_nr
        mapping.erpnext_account = erpnext_account
        mapping.auto_created = 1
        mapping.insert(ignore_permissions=True)
    except Exception:
        # Ignore if mapping already exists
        pass


def create_account_from_grootboek(grootboek_nr: str, transaction_type: str, company: str) -> str:
    """Create new account based on Grootboek number"""

    # Determine account type and parent based on number
    account_info = classify_grootboek_number(grootboek_nr)

    # Find parent account
    parent_account = find_parent_account(account_info["root_type"], account_info["account_type"], company)

    if not parent_account:
        # Fall back to default accounts
        return get_default_account(transaction_type, company)

    # Create account
    account = frappe.new_doc("Account")
    account.account_name = f"{grootboek_nr} - {account_info['name']}"
    account.parent_account = parent_account
    account.account_type = account_info["account_type"]
    account.root_type = account_info["root_type"]
    account.company = company
    account.custom_eboekhouden_grootboek = grootboek_nr

    try:
        account.insert(ignore_permissions=True)

        # Create mapping
        create_account_mapping(grootboek_nr, account.name)

        return account.name
    except Exception as e:
        frappe.log_error(f"Failed to create account for {grootboek_nr}: {str(e)}")
        return get_default_account(transaction_type, company)


def classify_grootboek_number(grootboek_nr: str) -> dict:
    """Classify Grootboek number according to Dutch chart of accounts"""

    try:
        number = int(grootboek_nr)
    except (ValueError, TypeError):
        return {"root_type": "Expense", "account_type": None, "name": f"Account {grootboek_nr}"}

    # Standard Dutch chart of accounts classification
    if 1000 <= number <= 1999:  # Assets
        if 1000 <= number <= 1199:
            return {"root_type": "Asset", "account_type": "Fixed Asset", "name": "Vaste activa"}
        elif 1200 <= number <= 1599:
            return {"root_type": "Asset", "account_type": "Current Asset", "name": "Vlottende activa"}
        elif 1600 <= number <= 1799:
            return {"root_type": "Asset", "account_type": "Receivable", "name": "Debiteuren"}
        else:
            return {"root_type": "Asset", "account_type": "Current Asset", "name": "Overige activa"}

    elif 2000 <= number <= 2999:  # Liabilities
        if 2000 <= number <= 2399:
            return {"root_type": "Liability", "account_type": None, "name": "Eigen vermogen"}
        elif 2400 <= number <= 2599:
            return {"root_type": "Liability", "account_type": None, "name": "Voorzieningen"}
        elif 2600 <= number <= 2799:
            return {"root_type": "Liability", "account_type": "Payable", "name": "Crediteuren"}
        else:
            return {"root_type": "Liability", "account_type": None, "name": "Overige schulden"}

    elif 4000 <= number <= 4999:  # Costs
        return {"root_type": "Expense", "account_type": "Expense Account", "name": "Kosten"}

    elif 8000 <= number <= 8999:  # Revenue
        return {"root_type": "Income", "account_type": "Income Account", "name": "Opbrengsten"}

    else:
        return {"root_type": "Expense", "account_type": None, "name": f"Account {grootboek_nr}"}


def find_parent_account(root_type: str, account_type: str, company: str) -> str:
    """Find appropriate parent account"""

    # Try to find specific parent first
    if account_type:
        parent = frappe.db.get_value(
            "Account", {"account_type": account_type, "is_group": 1, "company": company}, "name"
        )
        if parent:
            return parent

    # Fall back to root type
    parent = frappe.db.get_value(
        "Account", {"root_type": root_type, "is_group": 1, "company": company}, "name"
    )

    return parent


def get_default_account(transaction_type: str, company: str) -> str:
    """Get default account for transaction type"""
    if transaction_type == "sales":
        return get_default_income_account(company)
    else:
        return get_default_expense_account(company)


def get_default_income_account(company: str) -> str:
    """Get default income account"""
    account = frappe.db.get_value(
        "Account", {"company": company, "root_type": "Income", "is_group": 0}, "name"
    )

    if not account:
        # Create default income account
        account = create_default_account("Sales", "Income", "Income Account", company)

    return account


def get_default_expense_account(company: str) -> str:
    """Get default expense account"""
    account = frappe.db.get_value(
        "Account", {"company": company, "root_type": "Expense", "is_group": 0}, "name"
    )

    if not account:
        # Create default expense account
        account = create_default_account("Expenses", "Expense", "Expense Account", company)

    return account


def create_default_account(name: str, root_type: str, account_type: str, company: str) -> str:
    """Create default account"""
    # Find parent
    parent = frappe.db.get_value(
        "Account", {"root_type": root_type, "is_group": 1, "company": company}, "name"
    )

    if not parent:
        return None

    account = frappe.new_doc("Account")
    account.account_name = name
    account.parent_account = parent
    account.account_type = account_type
    account.root_type = root_type
    account.company = company
    account.insert(ignore_permissions=True)

    return account.name


def get_or_create_tax_account(btw_code: str, transaction_type: str, company: str) -> str:
    """Get or create tax account for BTW code"""

    # Define tax account mapping
    if transaction_type == "sales":
        account_map = {
            "HOOG_VERK_21": "BTW te betalen hoog 21%",
            "LAAG_VERK_9": "BTW te betalen laag 9%",
            "LAAG_VERK_6": "BTW te betalen laag 6%",
        }
        root_type = "Liability"
    else:
        account_map = {
            "HOOG_INK_21": "Voorbelasting hoog 21%",
            "LAAG_INK_9": "Voorbelasting laag 9%",
            "LAAG_INK_6": "Voorbelasting laag 6%",
        }
        root_type = "Asset"

    account_name = account_map.get(btw_code, f"BTW {btw_code}")

    # Check if account exists
    existing = frappe.db.get_value("Account", {"account_name": account_name, "company": company}, "name")

    if existing:
        return existing

    # Create tax account
    parent = frappe.db.get_value(
        "Account", {"account_type": "Tax", "is_group": 1, "company": company}, "name"
    )

    if not parent:
        # Create tax parent if it doesn't exist
        parent = create_tax_parent_account(company)

    account = frappe.new_doc("Account")
    account.account_name = account_name
    account.parent_account = parent
    account.account_type = "Tax"
    account.root_type = root_type
    account.company = company
    account.insert(ignore_permissions=True)

    return account.name


def create_tax_parent_account(company: str) -> str:
    """Create parent tax account group"""
    # Find root parent
    root_parent = frappe.db.get_value(
        "Account", {"root_type": "Liability", "is_group": 1, "company": company, "parent_account": ""}, "name"
    )

    account = frappe.new_doc("Account")
    account.account_name = "Tax Accounts"
    account.parent_account = root_parent
    account.is_group = 1
    account.root_type = "Liability"
    account.company = company
    account.insert(ignore_permissions=True)

    return account.name


def create_customer_from_relation_id(relation_id: str) -> str:
    """Create customer from relation ID"""
    customer = frappe.new_doc("Customer")
    customer.customer_name = f"E-Boekhouden {relation_id}"
    customer.customer_group = "All Customer Groups"
    customer.territory = "All Territories"
    customer.custom_eboekhouden_relation_id = relation_id
    customer.custom_needs_enrichment = 1
    customer.insert(ignore_permissions=True)

    return customer.name


def create_supplier_from_relation_id(relation_id: str) -> str:
    """Create supplier from relation ID"""
    supplier = frappe.new_doc("Supplier")
    supplier.supplier_name = f"E-Boekhouden {relation_id}"
    supplier.supplier_group = "All Supplier Groups"
    supplier.custom_eboekhouden_relation_id = relation_id
    supplier.custom_needs_enrichment = 1
    supplier.insert(ignore_permissions=True)

    return supplier.name


def get_or_create_default_customer() -> str:
    """Get or create default customer"""
    customer_name = "Guest Customer"

    if not frappe.db.exists("Customer", customer_name):
        customer = frappe.new_doc("Customer")
        customer.customer_name = customer_name
        customer.customer_group = "All Customer Groups"
        customer.territory = "All Territories"
        customer.insert(ignore_permissions=True)

    return customer_name


def get_or_create_default_supplier() -> str:
    """Get or create default supplier"""
    supplier_name = "Default Supplier"

    if not frappe.db.exists("Supplier", supplier_name):
        supplier = frappe.new_doc("Supplier")
        supplier.supplier_name = supplier_name
        supplier.supplier_group = "All Supplier Groups"
        supplier.insert(ignore_permissions=True)

    return supplier_name


def get_cost_center_by_eboekhouden_id(kostenplaats_id: str) -> str:
    """Get cost center by e-boekhouden ID"""
    return frappe.db.get_value("Cost Center", {"custom_eboekhouden_kostenplaats_id": kostenplaats_id}, "name")


def get_or_create_sales_tax_template(company: str) -> str:
    """Get or create sales tax template"""
    template_name = f"Sales Taxes - {company}"

    if not frappe.db.exists("Sales Taxes and Charges Template", template_name):
        template = frappe.new_doc("Sales Taxes and Charges Template")
        template.title = template_name
        template.company = company
        template.insert(ignore_permissions=True)

    return template_name


def get_or_create_purchase_tax_template(company: str) -> str:
    """Get or create purchase tax template"""
    template_name = f"Purchase Taxes - {company}"

    if not frappe.db.exists("Purchase Taxes and Charges Template", template_name):
        template = frappe.new_doc("Purchase Taxes and Charges Template")
        template.title = template_name
        template.company = company
        template.insert(ignore_permissions=True)

    return template_name


def create_fallback_line_item(mutation_detail: Dict, transaction_type: str, company: str) -> Dict:
    """Create fallback line item when no detailed line items available"""

    amount = abs(flt(mutation_detail.get("amount", 0)))
    description = mutation_detail.get("description", "E-Boekhouden Import")

    # Try to map main ledger account
    ledger_id = mutation_detail.get("ledgerId")
    account = None

    if ledger_id:
        account = map_grootboek_to_erpnext_account(ledger_id, transaction_type, company)

    line_item = {
        "item_code": get_or_create_item_from_description(description),
        "item_name": description,
        "description": description,
        "qty": 1,
        "uom": "Nos",
        "rate": amount,
        "amount": amount,
    }

    if transaction_type == "sales":
        line_item["income_account"] = account or get_default_income_account(company)
    else:
        line_item["expense_account"] = account or get_default_expense_account(company)

    return line_item
