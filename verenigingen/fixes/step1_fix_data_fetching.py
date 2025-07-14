"""
Step 1: Fix E-Boekhouden Data Fetching
Replace current poor implementation with proper full data extraction
"""

from typing import Dict, List, Optional

import frappe
from frappe.utils import add_days, flt, now


def create_sales_invoice_with_full_data(mutation_detail: Dict, company: str, cost_center: str) -> Dict:
    """
    Create Sales Invoice using ALL available data from e-boekhouden

    This replaces the current poor implementation that only uses summary data
    """
    try:
        si = frappe.new_doc("Sales Invoice")

        # ==========================================
        # BASIC FIELDS - Properly mapped
        # ==========================================
        si.company = company
        si.posting_date = mutation_detail.get("date")
        si.set_posting_time = 1  # Allow backdated entries

        # Currency (Dutch businesses use EUR)
        si.currency = "EUR"
        si.conversion_rate = 1.0

        # ==========================================
        # CUSTOMER - Resolve properly, don't use ID
        # ==========================================
        relation_id = mutation_detail.get("relationId")
        customer = resolve_customer_properly(relation_id)
        si.customer = customer

        # ==========================================
        # PAYMENT TERMS AND DUE DATE - Use API data
        # ==========================================
        payment_days = mutation_detail.get("Betalingstermijn", 30)
        if payment_days:
            si.payment_terms_template = get_or_create_payment_terms_template(payment_days)
            si.due_date = add_days(si.posting_date, payment_days)

        # ==========================================
        # REFERENCES - Capture all available
        # ==========================================
        if mutation_detail.get("Referentie"):
            si.po_no = mutation_detail.get("Referentie")

        # Description and remarks
        si.remarks = mutation_detail.get("description", "")

        # ==========================================
        # CREDIT NOTES - Handle negative amounts
        # ==========================================
        total_amount = flt(mutation_detail.get("amount", 0))
        si.is_return = total_amount < 0

        # ==========================================
        # CUSTOM TRACKING FIELDS
        # ==========================================
        si.custom_eboekhouden_mutation_nr = str(mutation_detail.get("id"))
        si.custom_eboekhouden_invoice_number = mutation_detail.get("invoiceNumber")
        si.custom_eboekhouden_import_date = now()
        si.custom_eboekhouden_relation_id = relation_id

        # ==========================================
        # LINE ITEMS - Process ALL line items with VAT
        # ==========================================
        if "Regels" in mutation_detail and mutation_detail["Regels"]:
            # Process each individual line item
            for regel in mutation_detail["Regels"]:
                line_item = create_line_item_from_regel(regel, "sales", company)
                si.append("items", line_item)

            # Add tax lines based on BTW codes in line items
            add_vat_lines_to_invoice(si, mutation_detail["Regels"], "sales")
        else:
            # Fallback for mutations without detailed line items
            fallback_item = create_fallback_line_item(mutation_detail, "sales", company)
            si.append("items", fallback_item)

        # ==========================================
        # TAX TEMPLATE - Set if we have taxes
        # ==========================================
        if si.taxes and len(si.taxes) > 0:
            si.taxes_and_charges = get_or_create_sales_tax_template(company)

        # Save and submit
        si.save()
        si.submit()

        return {
            "success": True,
            "doctype": "Sales Invoice",
            "name": si.name,
            "customer": si.customer,
            "total": si.grand_total,
            "line_items": len(si.items),
            "tax_lines": len(si.taxes) if si.taxes else 0,
        }

    except Exception as e:
        frappe.log_error(f"Error creating sales invoice from mutation: {str(e)}", "E-Boekhouden Import")
        return {"success": False, "error": str(e)}


def create_purchase_invoice_with_full_data(mutation_detail: Dict, company: str, cost_center: str) -> Dict:
    """
    Create Purchase Invoice using ALL available data from e-boekhouden
    """
    try:
        pi = frappe.new_doc("Purchase Invoice")

        # ==========================================
        # BASIC FIELDS
        # ==========================================
        pi.company = company
        pi.posting_date = mutation_detail.get("date")
        pi.bill_date = mutation_detail.get("date")  # Supplier invoice date
        pi.set_posting_time = 1

        # Currency
        pi.currency = "EUR"
        pi.conversion_rate = 1.0

        # ==========================================
        # SUPPLIER - Resolve properly
        # ==========================================
        relation_id = mutation_detail.get("relationId")
        supplier = resolve_supplier_properly(relation_id)
        pi.supplier = supplier

        # ==========================================
        # INVOICE NUMBERS - Use supplier's numbers
        # ==========================================
        if mutation_detail.get("invoiceNumber"):
            pi.bill_no = mutation_detail.get("invoiceNumber")
            pi.supplier_invoice_no = mutation_detail.get("invoiceNumber")

        # ==========================================
        # PAYMENT TERMS
        # ==========================================
        payment_days = mutation_detail.get("Betalingstermijn", 30)
        if payment_days:
            pi.payment_terms_template = get_or_create_payment_terms_template(payment_days)
            pi.due_date = add_days(pi.bill_date, payment_days)

        # Description
        pi.remarks = mutation_detail.get("description", "")

        # ==========================================
        # DEBIT NOTES - Handle negative amounts
        # ==========================================
        total_amount = flt(mutation_detail.get("amount", 0))
        pi.is_return = total_amount < 0

        # ==========================================
        # CUSTOM TRACKING FIELDS
        # ==========================================
        pi.custom_eboekhouden_mutation_nr = str(mutation_detail.get("id"))
        pi.custom_eboekhouden_import_date = now()
        pi.custom_eboekhouden_relation_id = relation_id

        # ==========================================
        # LINE ITEMS WITH VAT
        # ==========================================
        if "Regels" in mutation_detail and mutation_detail["Regels"]:
            for regel in mutation_detail["Regels"]:
                line_item = create_line_item_from_regel(regel, "purchase", company)
                pi.append("items", line_item)

            add_vat_lines_to_invoice(pi, mutation_detail["Regels"], "purchase")
        else:
            fallback_item = create_fallback_line_item(mutation_detail, "purchase", company)
            pi.append("items", fallback_item)

        # ==========================================
        # TAX TEMPLATE
        # ==========================================
        if pi.taxes and len(pi.taxes) > 0:
            pi.taxes_and_charges = get_or_create_purchase_tax_template(company)

        pi.save()
        pi.submit()

        return {
            "success": True,
            "doctype": "Purchase Invoice",
            "name": pi.name,
            "supplier": pi.supplier,
            "total": pi.grand_total,
            "line_items": len(pi.items),
            "tax_lines": len(pi.taxes) if pi.taxes else 0,
        }

    except Exception as e:
        frappe.log_error(f"Error creating purchase invoice from mutation: {str(e)}", "E-Boekhouden Import")
        return {"success": False, "error": str(e)}


def create_line_item_from_regel(regel: Dict, transaction_type: str, company: str) -> Dict:
    """
    Create proper line item from e-boekhouden Regel (line item)

    This replaces the terrible current approach of everything being "Service Item"
    """

    # ==========================================
    # ITEM CREATION - Based on actual description
    # ==========================================
    description = regel.get("Omschrijving", "Service")
    item_code = get_or_create_item_from_description(description, regel.get("Eenheid", "Nos"))

    # ==========================================
    # QUANTITIES AND PRICES - From actual data
    # ==========================================
    qty = flt(regel.get("Aantal", 1))
    rate = flt(regel.get("Prijs", 0))
    amount = qty * rate

    # ==========================================
    # ACCOUNT MAPPING - From Grootboek number
    # ==========================================
    grootboek_nr = regel.get("GrootboekNummer")
    account = map_grootboek_to_erpnext_account(grootboek_nr, transaction_type, company)

    line_item = {
        "item_code": item_code,
        "item_name": description,
        "description": description,
        "qty": qty,
        "uom": map_unit_of_measure(regel.get("Eenheid", "Nos")),
        "rate": rate,
        "amount": amount,
    }

    # Set appropriate account based on transaction type
    if transaction_type == "sales":
        line_item["income_account"] = account or get_default_income_account(company)
    else:
        line_item["expense_account"] = account or get_default_expense_account(company)

    # ==========================================
    # COST CENTER - If specified in line item
    # ==========================================
    if regel.get("KostenplaatsId"):
        cost_center = get_cost_center_by_eboekhouden_id(regel.get("KostenplaatsId"))
        if cost_center:
            line_item["cost_center"] = cost_center

    return line_item


def add_vat_lines_to_invoice(invoice, regels: List[Dict], invoice_type: str):
    """
    Add VAT/BTW lines based on BTW codes in line items

    This is COMPLETELY MISSING from current implementation
    """

    # Group amounts by BTW code
    btw_summary = {}

    for regel in regels:
        btw_code = regel.get("BTWCode", "").upper()

        if btw_code and btw_code != "GEEN":
            if btw_code not in btw_summary:
                btw_summary[btw_code] = {"taxable_amount": 0, "rate": get_btw_rate_from_code(btw_code)}

            # Calculate line total (excluding VAT)
            line_total = flt(regel.get("Aantal", 1)) * flt(regel.get("Prijs", 0))
            btw_summary[btw_code]["taxable_amount"] += line_total

    # Create tax lines
    for btw_code, data in btw_summary.items():
        if data["rate"] > 0:
            tax_amount = data["taxable_amount"] * data["rate"] / 100
            tax_account = get_or_create_tax_account(btw_code, invoice_type, invoice.company)

            invoice.append(
                "taxes",
                {
                    "charge_type": "Actual",
                    "account_head": tax_account,
                    "tax_amount": tax_amount,
                    "description": f"BTW {data['rate']}% ({btw_code})",
                    "rate": 0,  # Using actual amount, not rate
                    "base_tax_amount": tax_amount,
                    "base_total": data["taxable_amount"],
                },
            )


# ==========================================
# SUPPORTING FUNCTIONS
# ==========================================


def resolve_customer_properly(relation_id: str) -> str:
    """Resolve relation ID to proper customer name, not just the ID"""
    if not relation_id:
        return get_or_create_default_customer()

    # Check if we already have this customer
    existing = frappe.db.get_value("Customer", {"custom_eboekhouden_relation_id": relation_id}, "name")

    if existing:
        return existing

    # Create new customer with proper name
    return create_customer_from_relation_id(relation_id)


def resolve_supplier_properly(relation_id: str) -> str:
    """Resolve relation ID to proper supplier name"""
    if not relation_id:
        return get_or_create_default_supplier()

    existing = frappe.db.get_value("Supplier", {"custom_eboekhouden_relation_id": relation_id}, "name")

    if existing:
        return existing

    return create_supplier_from_relation_id(relation_id)


def get_or_create_payment_terms_template(days: int) -> str:
    """Create payment terms template for the specified days"""
    template_name = f"Netto {days} dagen"

    if not frappe.db.exists("Payment Terms Template", template_name):
        template = frappe.new_doc("Payment Terms Template")
        template.template_name = template_name
        template.append(
            "terms",
            {"due_date_based_on": "Day(s) after invoice date", "credit_days": days, "invoice_portion": 100.0},
        )
        template.insert(ignore_permissions=True)

    return template_name


def get_or_create_item_from_description(description: str, unit: str = "Nos") -> str:
    """Create item based on actual description, not generic 'Service Item'"""

    # Clean description for item code
    item_code = clean_description_for_item_code(description)

    # Check if item already exists
    if frappe.db.exists("Item", item_code):
        return item_code

    # Create new item
    item = frappe.new_doc("Item")
    item.item_code = item_code
    item.item_name = description[:140]  # ERPNext limit
    item.description = description
    item.item_group = determine_item_group_from_description(description)
    item.stock_uom = map_unit_of_measure(unit)
    item.is_stock_item = 0
    item.is_sales_item = 1
    item.is_purchase_item = 1

    try:
        item.insert(ignore_permissions=True)
        return item.name
    except frappe.DuplicateEntryError:
        # Handle race condition
        return item_code


def get_btw_rate_from_code(btw_code: str) -> float:
    """Get BTW rate from Dutch tax code"""
    btw_rates = {
        "HOOG_VERK_21": 21.0,
        "LAAG_VERK_9": 9.0,
        "LAAG_VERK_6": 6.0,
        "HOOG_INK_21": 21.0,
        "LAAG_INK_9": 9.0,
        "LAAG_INK_6": 6.0,
        "GEEN": 0.0,
        "VERL_VERK": 0.0,  # Verlegd = reverse charge
        "BU_EU_VERK": 0.0,  # Outside EU
    }

    return btw_rates.get(btw_code, 0.0)


def map_unit_of_measure(dutch_unit: str) -> str:
    """Map Dutch units to ERPNext UOM"""
    uom_mapping = {
        "stuk": "Nos",
        "stuks": "Nos",
        "uur": "Hour",
        "uren": "Hour",
        "dag": "Day",
        "dagen": "Day",
        "week": "Week",
        "maand": "Month",
        "jaar": "Year",
        "kg": "Kg",
        "gram": "Gram",
        "liter": "Litre",
        "meter": "Meter",
        "m2": "Square Meter",
        "m3": "Cubic Meter",
    }

    return uom_mapping.get(dutch_unit.lower(), "Nos") if dutch_unit else "Nos"


# ==========================================
# WHITELISTED FUNCTIONS FOR TESTING
# ==========================================


@frappe.whitelist()
def test_new_invoice_creation(mutation_id: int):
    """Test the new invoice creation with full data"""
    from verenigingen.utils.eboekhouden.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

    company = frappe.get_single("E-Boekhouden Settings").default_company
    cost_center = frappe.db.get_value("Company", company, "cost_center")

    iterator = EBoekhoudenRESTIterator()

    # CRITICAL: Get full mutation details
    mutation_detail = iterator.fetch_mutation_detail(int(mutation_id))

    if not mutation_detail:
        return {"success": False, "error": f"Mutation {mutation_id} not found"}

    mutation_type = mutation_detail.get("type", 0)

    if mutation_type == 1:  # Purchase Invoice
        return create_purchase_invoice_with_full_data(mutation_detail, company, cost_center)
    elif mutation_type == 2:  # Sales Invoice
        return create_sales_invoice_with_full_data(mutation_detail, company, cost_center)
    else:
        return {"success": False, "error": f"Unsupported mutation type: {mutation_type}"}


@frappe.whitelist()
def compare_old_vs_new_import(mutation_id: int):
    """Compare current implementation vs new implementation"""
    from verenigingen.utils.eboekhouden.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

    iterator = EBoekhoudenRESTIterator()

    # Get summary data (what current implementation uses)
    mutation_summary = iterator.fetch_mutation_by_id(int(mutation_id))

    # Get full data (what new implementation uses)
    mutation_detail = iterator.fetch_mutation_detail(int(mutation_id))

    comparison = {
        "mutation_id": mutation_id,
        "summary_data": {
            "fields_available": len(mutation_summary.keys()) if mutation_summary else 0,
            "has_line_items": False,
            "sample_fields": list(mutation_summary.keys())[:10] if mutation_summary else [],
        },
        "detail_data": {
            "fields_available": len(mutation_detail.keys()) if mutation_detail else 0,
            "has_line_items": "Regels" in mutation_detail if mutation_detail else False,
            "line_item_count": len(mutation_detail.get("Regels", [])) if mutation_detail else 0,
            "sample_fields": list(mutation_detail.keys())[:10] if mutation_detail else [],
        },
    }

    if mutation_detail and "Regels" in mutation_detail:
        comparison["detail_data"]["line_items_sample"] = mutation_detail["Regels"][:2]

    return comparison
