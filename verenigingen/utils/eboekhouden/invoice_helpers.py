# Helper functions for enhanced invoice creation from E-Boekhouden data
import frappe
from frappe.utils import add_days, flt, now

from .field_mapping import (
    ACCOUNT_TYPE_MAP,
    BTW_CODE_MAP,
    DEFAULT_ITEM_GROUPS,
    DEFAULT_PAYMENT_TERMS,
    INVOICE_FIELD_MAP,
    ITEM_GROUP_KEYWORDS,
    LINE_ITEM_FIELD_MAP,
    PRICE_CATEGORY_RANGES,
    UOM_MAP,
)


def resolve_customer(relation_id, debug_info=None):
    """Resolve relation ID to proper customer using enhanced party resolver"""
    from .party_resolver import EBoekhoudenPartyResolver

    resolver = EBoekhoudenPartyResolver()
    return resolver.resolve_customer(relation_id, debug_info)


def resolve_supplier(relation_id, debug_info=None):
    """Resolve relation ID to proper supplier using enhanced party resolver"""
    from .party_resolver import EBoekhoudenPartyResolver

    resolver = EBoekhoudenPartyResolver()
    return resolver.resolve_supplier(relation_id, debug_info)


def get_default_customer():
    """Get or create default customer"""
    customer_name = "E-Boekhouden Import Customer"
    if not frappe.db.exists("Customer", customer_name):
        customer = frappe.new_doc("Customer")
        customer.customer_name = customer_name
        customer.customer_group = "All Customer Groups"
        customer.territory = "All Territories"
        customer.insert()
    return customer_name


def get_default_supplier():
    """Get or create default supplier"""
    supplier_name = "E-Boekhouden Import Supplier"
    if not frappe.db.exists("Supplier", supplier_name):
        supplier = frappe.new_doc("Supplier")
        supplier.supplier_name = supplier_name
        supplier.supplier_group = "All Supplier Groups"
        supplier.insert()
    return supplier_name


def create_provisional_customer(relation_id, debug_info):
    """Create provisional customer for later enrichment"""
    customer_name = f"E-Boekhouden Customer {relation_id}"

    # Check if already exists
    if frappe.db.exists("Customer", {"customer_name": customer_name}):
        return customer_name

    customer = frappe.new_doc("Customer")
    customer.customer_name = customer_name
    customer.customer_group = "All Customer Groups"
    customer.territory = "All Territories"
    customer.eboekhouden_relation_code = str(relation_id)
    customer.insert()

    debug_info.append(f"Created provisional customer: {customer.name}")
    return customer.name


def create_provisional_supplier(relation_id, debug_info):
    """Create provisional supplier for later enrichment"""
    supplier_name = f"E-Boekhouden Supplier {relation_id}"

    # Check if already exists
    if frappe.db.exists("Supplier", {"supplier_name": supplier_name}):
        return supplier_name

    supplier = frappe.new_doc("Supplier")
    supplier.supplier_name = supplier_name
    supplier.supplier_group = "All Supplier Groups"
    supplier.eboekhouden_relation_code = str(relation_id)
    supplier.insert()

    debug_info.append(f"Created provisional supplier: {supplier.name}")
    return supplier.name


def get_or_create_payment_terms(days):
    """Get or create payment terms template with enhanced Dutch business logic"""
    if not days or days <= 0:
        days = 30  # Default to 30 days

    # Check for standard Dutch payment terms
    if days in DEFAULT_PAYMENT_TERMS:
        template_name = DEFAULT_PAYMENT_TERMS[days]
    else:
        template_name = f"Netto {days} dagen"

    # Check if template already exists
    if frappe.db.exists("Payment Terms Template", template_name):
        return template_name

    # Create new payment terms template
    try:
        template = frappe.new_doc("Payment Terms Template")
        template.template_name = template_name

        # Standard single payment term
        template.append(
            "terms",
            {
                "due_date_based_on": "Day(s) after invoice date",
                "credit_days": int(days),
                "invoice_portion": 100.0,
                "description": f"Full payment due {days} days after invoice date",
            },
        )

        # Add common Dutch payment descriptions
        descriptions = {
            7: "Betaling binnen 7 dagen",
            14: "Betaling binnen 14 dagen",
            21: "Betaling binnen 21 dagen",
            30: "Betaling binnen 30 dagen",
            45: "Betaling binnen 45 dagen",
            60: "Betaling binnen 60 dagen",
        }

        if days in descriptions:
            template.terms[0].description = descriptions[days]

        template.insert()

        return template.name

    except Exception as e:
        # If creation fails, return a default
        frappe.log_error(f"Failed to create payment terms for {days} days: {str(e)}")
        return "Net 30"  # ERPNext default


def process_line_items(invoice, regels, invoice_type, cost_center, debug_info):
    """Process e-boekhouden line items with proper VAT handling"""
    if not regels:
        debug_info.append("No line items (Regels) found, creating fallback item")
        return False

    debug_info.append(f"Processing {len(regels)} line items")

    for regel in regels:
        # Get or create item with enhanced categorization
        item_code = get_or_create_item_from_description(
            regel.get("Omschrijving", "Service"),
            regel.get("Eenheid", "Nos"),
            debug_info,
            btw_code=regel.get("BTWCode"),
            account_code=regel.get("GrootboekNummer"),
            price=flt(regel.get("Prijs", 0)),
        )

        # Map GL account
        gl_account = map_grootboek_to_erpnext_account(regel.get("GrootboekNummer"), invoice_type, debug_info)

        line_item = {
            "item_code": item_code,
            "item_name": regel.get("Omschrijving", "Service"),
            "description": regel.get("Omschrijving", ""),
            "qty": flt(regel.get("Aantal", 1)),
            "uom": map_unit_of_measure(regel.get("Eenheid", "Nos")),
            "rate": flt(regel.get("Prijs", 0)),
            "cost_center": cost_center,
        }

        # Set appropriate account
        if invoice_type == "sales":
            line_item["income_account"] = gl_account
        else:
            line_item["expense_account"] = gl_account

        # Cost center if available
        if regel.get("KostenplaatsId"):
            line_item["cost_center"] = get_cost_center(regel.get("KostenplaatsId"))

        invoice.append("items", line_item)
        debug_info.append(
            f"Added line item: {regel.get('Omschrijving', 'Unknown')} - {line_item['qty']} x {line_item['rate']}"
        )

    return True


def add_tax_lines(invoice, regels, invoice_type, debug_info):
    """Add tax lines based on BTW codes with enhanced calculations"""
    if not regels:
        debug_info.append("No line items (Regels) for tax calculation")
        return

    # Group by BTW code and calculate taxable amounts
    btw_summary = {}
    total_net_amount = 0

    for regel in regels:
        btw_code = regel.get("BTWCode", "").upper()

        # Calculate line total (net amount)
        line_qty = flt(regel.get("Aantal", 1))
        line_price = flt(regel.get("Prijs", 0))
        line_total = line_qty * line_price
        total_net_amount += line_total

        debug_info.append(
            f"Line item: {regel.get('Omschrijving', 'Unknown')} - {line_qty} x {line_price} = {line_total} (BTW: {btw_code})"
        )

        if btw_code and btw_code not in ["GEEN", "VRIJ", ""]:
            if btw_code not in btw_summary:
                btw_info = BTW_CODE_MAP.get(btw_code, {})
                if not btw_info:
                    debug_info.append(f"WARNING: Unknown BTW code: {btw_code}")
                    continue

                btw_summary[btw_code] = {
                    "taxable_amount": 0,
                    "rate": btw_info.get("rate", 0),
                    "description": btw_info.get("description", f"BTW {btw_code}"),
                    "account_name": btw_info.get("account_name"),
                    "type": btw_info.get("type"),
                }

            btw_summary[btw_code]["taxable_amount"] += line_total

    debug_info.append(f"Total net amount: {total_net_amount}")
    debug_info.append(f"BTW codes found: {list(btw_summary.keys())}")

    # Create tax lines
    total_tax_amount = 0

    for btw_code, data in btw_summary.items():
        if data["rate"] > 0 and data["taxable_amount"] > 0:
            tax_amount = round(data["taxable_amount"] * data["rate"] / 100, 2)
            total_tax_amount += tax_amount

            tax_account = get_tax_account(btw_code, invoice_type, invoice.company, debug_info)

            if tax_account:
                # Create proper tax line for ERPNext
                tax_line = {
                    "charge_type": "Actual",
                    "account_head": tax_account,
                    "tax_amount": tax_amount,
                    "description": f"{data['description']} ({data['rate']}%)",
                    "rate": 0,  # Using actual amount instead of percentage
                    "base_tax_amount": tax_amount,
                    "base_tax_amount_after_discount_amount": tax_amount,
                    "tax_amount_after_discount_amount": tax_amount,
                }

                # Add cost center if available
                if hasattr(invoice, "cost_center") and invoice.cost_center:
                    tax_line["cost_center"] = invoice.cost_center

                invoice.append("taxes", tax_line)
                debug_info.append(
                    f"Added tax line: {data['description']} - Taxable: €{data['taxable_amount']}, Tax: €{tax_amount}"
                )
            else:
                debug_info.append(f"WARNING: No tax account found for BTW code: {btw_code}")
        elif data["rate"] == 0:
            debug_info.append(f"Zero-rate tax code: {btw_code} - {data['description']}")

    debug_info.append(f"Total tax amount: €{total_tax_amount}")

    # Validate total amounts
    if total_tax_amount > 0:
        calculated_total = total_net_amount + total_tax_amount
        debug_info.append(f"Calculated total (net + tax): €{calculated_total}")

    return {"net_amount": total_net_amount, "tax_amount": total_tax_amount}


def get_or_create_item_from_description(
    description, unit="Nos", debug_info=None, btw_code=None, account_code=None, price=None
):
    """Smart item creation based on description with enhanced categorization"""
    if debug_info is None:
        debug_info = []

    # Check for existing item by description
    existing = frappe.db.get_value("Item", {"description": description}, "name")
    if existing:
        debug_info.append(f"Found existing item: {existing}")
        return existing

    # Generate item code
    item_code = generate_item_code(description)

    # Check if item code already exists
    if frappe.db.exists("Item", item_code):
        debug_info.append(f"Item code already exists: {item_code}")
        return item_code

    # Determine item group using enhanced logic
    item_group = determine_item_group(description, btw_code, account_code, price)
    debug_info.append(
        f"Determined item group: {item_group} (BTW: {btw_code}, Account: {account_code}, Price: {price})"
    )

    # Create new item
    item = frappe.new_doc("Item")
    item.item_code = item_code
    item.item_name = description[:140]  # Limit length
    item.description = description
    item.item_group = item_group

    # Smart UOM assignment
    mapped_uom = map_unit_of_measure(unit)
    if mapped_uom == "Nos" and unit in ["Nos", None, ""]:
        # If no specific unit given, suggest based on item group
        from .uom_manager import UOMManager

        suggested_uom = UOMManager.get_uom_for_category(item_group)
        item.stock_uom = suggested_uom
        debug_info.append(f"Suggested UOM based on category: {suggested_uom}")
    else:
        item.stock_uom = mapped_uom

    # Smart stock item determination based on group
    if item_group in ["Products", "Office Supplies"]:
        item.is_stock_item = 1
        item.maintain_stock = 1
        item.valuation_method = "FIFO"
        item.has_batch_no = 0
        item.has_serial_no = 0
        debug_info.append("Configured as stock item")
    else:
        item.is_stock_item = 0
        item.maintain_stock = 0

    item.is_sales_item = 1
    item.is_purchase_item = 1

    # Add Dutch description and metadata
    if hasattr(item, "custom_dutch_description"):
        item.custom_dutch_description = description

    # Add price categorization for future reference
    if price and hasattr(item, "custom_price_category"):
        if 0 < flt(price) <= PRICE_CATEGORY_RANGES["consumable"][1]:
            item.custom_price_category = "Consumable"
        elif flt(price) <= PRICE_CATEGORY_RANGES["equipment"][1]:
            item.custom_price_category = "Equipment"
        else:
            item.custom_price_category = "Investment"

    # Additional metadata
    item.eboekhouden_import = 1

    item.insert()
    debug_info.append(f"Created new item: {item.item_code} in group {item.item_group}")
    return item.name


def generate_item_code(description):
    """Generate a clean item code from description"""
    # Take first 30 characters, clean up
    clean_desc = "".join(c for c in description if c.isalnum() or c in " -_").strip()
    clean_desc = clean_desc.replace(" ", "-").upper()[:30]

    # Add prefix for E-Boekhouden items
    return f"EBH-{clean_desc}"


def determine_item_group(description, btw_code=None, account_code=None, price=None):
    """Enhanced item group determination using multiple signals"""
    from .field_mapping import ACCOUNT_CODE_ITEM_HINTS, PRICE_CATEGORY_RANGES, VAT_CATEGORY_HINTS

    description_lower = description.lower()

    # Priority 1: Check description keywords (most specific)
    for group, keywords in ITEM_GROUP_KEYWORDS.items():
        if any(keyword in description_lower for keyword in keywords):
            return DEFAULT_ITEM_GROUPS.get(group, "Services")

    # Priority 2: Use VAT code hints if available
    if btw_code and btw_code in VAT_CATEGORY_HINTS:
        group = VAT_CATEGORY_HINTS[btw_code]
        return DEFAULT_ITEM_GROUPS.get(group, "Services")

    # Priority 3: Use account code hints if available
    if account_code:
        try:
            account_num = int(str(account_code).split("-")[0].strip())
            for (start, end), group in ACCOUNT_CODE_ITEM_HINTS.items():
                if start <= account_num <= end:
                    return DEFAULT_ITEM_GROUPS.get(group, "Services")
        except (ValueError, IndexError):
            pass

    # Priority 4: Use price range hints
    if price:
        price_float = flt(price)
        if 0 < price_float <= PRICE_CATEGORY_RANGES["consumable"][1]:
            return "Office Supplies"
        elif price_float > PRICE_CATEGORY_RANGES["equipment"][0]:
            return "Products"

    # Default fallback
    return DEFAULT_ITEM_GROUPS.get("default", "Services")


def map_unit_of_measure(unit):
    """Map Dutch units to ERPNext UOMs using enhanced UOM manager"""
    from .uom_manager import map_unit_of_measure as uom_map

    return uom_map(unit)


def map_grootboek_to_erpnext_account(grootboek_nummer, transaction_type, debug_info=None):
    """Map eBoekhouden GL account to ERPNext account using modern mapping system"""
    if debug_info is None:
        debug_info = []

    if not grootboek_nummer:
        return get_default_account(transaction_type)

    # Check if ERPNext account already exists with this grootboek code
    company = frappe.defaults.get_user_default("Company") or "NVV"
    company_abbr = frappe.db.get_value("Company", company, "abbr")

    # Try direct account lookup first (accounts created by Chart of Accounts import)
    potential_account_names = [
        f"{grootboek_nummer} - {company_abbr}",  # Standard format
        f"{grootboek_nummer} - % - {company_abbr}",  # With description wildcard
    ]

    for pattern in potential_account_names:
        account = frappe.db.get_value(
            "Account", {"name": ["like", pattern], "company": company, "disabled": 0}, "name"
        )
        if account:
            debug_info.append(f"Found direct account match: {grootboek_nummer} -> {account}")
            return account

    # Use modern account mapping system as fallback
    try:
        from verenigingen.verenigingen.doctype.eboekhouden_account_map.eboekhouden_account_map import (
            EBoekhoudenAccountMap,
        )

        # Try to get existing mapping
        mapping = EBoekhoudenAccountMap.get_account_mapping(grootboek_nummer)

        if mapping:
            debug_info.append(f"Found modern mapping: {grootboek_nummer} -> {mapping['erpnext_account']}")
            return mapping["erpnext_account"]

        # Try to create auto-mapping
        account_name = f"Account {grootboek_nummer}"  # Would be better with real name from API

        auto_mapping = EBoekhoudenAccountMap.create_auto_mapping(grootboek_nummer, account_name, company)

        if auto_mapping:
            # Get the created mapping
            new_mapping = EBoekhoudenAccountMap.get_account_mapping(grootboek_nummer, company)
            if new_mapping:
                debug_info.append(
                    f"Created auto-mapping: {grootboek_nummer} -> {new_mapping['erpnext_account']}"
                )
                return new_mapping["erpnext_account"]

    except Exception as e:
        debug_info.append(f"Account mapping error: {str(e)}")

    # No mapping found - raise error to fail during configuration phase
    error_msg = f"No account mapping found for E-Boekhouden account {grootboek_nummer}. Please configure the account mapping before importing transactions."
    debug_info.append(f"ERROR: {error_msg}")
    frappe.throw(error_msg, title="Account Mapping Missing")


def get_default_account(transaction_type):
    """Get default account based on transaction type - DEPRECATED: Should not be used as fallback"""
    raise ValueError(
        f"get_default_account() called for transaction_type '{transaction_type}'. This function should not be used as a fallback - proper account mapping is required."
    )


def get_tax_account(btw_code, invoice_type, company, debug_info=None):
    """Get appropriate tax account for BTW code using existing accounts"""
    if debug_info is None:
        debug_info = []

    btw_info = BTW_CODE_MAP.get(btw_code, {})
    if not btw_info or not btw_info.get("account_name"):
        debug_info.append(f"No tax account mapping for BTW code: {btw_code}")
        return None

    # Try primary account mapping
    account_name = btw_info.get("account_name")
    if account_name and frappe.db.exists("Account", account_name):
        debug_info.append(f"Using primary tax account: {account_name}")
        return account_name

    # Try fallback account
    fallback_account = btw_info.get("account_fallback")
    if fallback_account and frappe.db.exists("Account", fallback_account):
        debug_info.append(f"Using fallback tax account: {fallback_account}")
        return fallback_account

    # Final fallback based on invoice type
    if invoice_type == "sales":
        final_fallback = "1500 - BTW af te dragen 21% - NVV"
    else:
        final_fallback = "1530 - BTW te vorderen - NVV"

    if frappe.db.exists("Account", final_fallback):
        debug_info.append(f"Using final fallback tax account: {final_fallback}")
        return final_fallback

    debug_info.append(f"No suitable tax account found for BTW code: {btw_code}")
    return None


def get_cost_center(cost_center_id):
    """Get cost center by ID"""
    # This would need to be implemented based on cost center mapping
    # For now, return a default
    return frappe.db.get_single_value("Company", "cost_center") or "Main - NVV"


def fetch_relation_details(relation_id):
    """Fetch relation details from e-boekhouden API"""
    # This would require API call to get relation details
    # For now, return None to use provisional creation
    return None


def create_customer_from_relation(relation_details, debug_info):
    """Create customer with proper details from relation data"""
    customer = frappe.new_doc("Customer")

    # Use actual name if available
    customer.customer_name = relation_details.get("name", f"E-Boekhouden {relation_details['id']}")
    customer.customer_group = "All Customer Groups"
    customer.territory = "All Territories"

    # Store relation ID for future matching
    customer.eboekhouden_relation_code = str(relation_details["id"])

    # Add contact info if available
    if relation_details.get("email"):
        customer.email_id = relation_details["email"]

    customer.insert()
    debug_info.append(f"Created customer from relation data: {customer.name}")
    return customer.name


def create_single_line_fallback(invoice, mutation_detail, cost_center, debug_info):
    """Create a single line item fallback when no detailed line items are available"""
    mutation_id = mutation_detail.get("id")
    description = mutation_detail.get("description", f"eBoekhouden Import {mutation_id}")
    amount = flt(mutation_detail.get("amount", 0))
    ledger_id = mutation_detail.get("ledgerId")

    debug_info.append("Creating single line fallback item")

    # Determine if this is sales or purchase based on document type
    transaction_type = "sales" if invoice.doctype == "Sales Invoice" else "purchase"

    # Use existing function to create line
    from verenigingen.utils.eboekhouden.eboekhouden_rest_full_migration import (
        create_invoice_line_for_tegenrekening,
    )

    line_dict = create_invoice_line_for_tegenrekening(
        tegenrekening_code=ledger_id,
        amount=abs(amount),
        description=description,
        transaction_type=transaction_type,
    )

    # Get or create item using intelligent creation
    from verenigingen.utils.eboekhouden.eboekhouden_improved_item_naming import get_or_create_item_improved

    # Use account code from the appropriate account for intelligent item creation
    account_code = ""
    if transaction_type == "sales":
        account_code = (
            line_dict.get("income_account", "").split(" - ")[0]
            if " - " in line_dict.get("income_account", "")
            else ""
        )
    else:
        account_code = (
            line_dict.get("expense_account", "").split(" - ")[0]
            if " - " in line_dict.get("expense_account", "")
            else ""
        )

    item_code = get_or_create_item_improved(
        account_code=account_code,
        company=invoice.company,
        transaction_type="Sales" if transaction_type == "sales" else "Purchase",
        description=line_dict["description"],
    )

    line_item = {
        "item_code": item_code,
        "description": line_dict["description"],
        "qty": line_dict["qty"],
        "rate": line_dict["rate"],
        "amount": line_dict["amount"],
        "cost_center": cost_center,
    }

    # Set appropriate account
    if transaction_type == "sales":
        line_item["income_account"] = line_dict["income_account"]
    else:
        line_item["expense_account"] = line_dict["expense_account"]

    invoice.append("items", line_item)
    debug_info.append(f"Added fallback line item: {line_dict['description']} - {line_dict['amount']}")
