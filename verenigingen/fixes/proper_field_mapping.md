# Proper E-Boekhouden to ERPNext Field Mapping

## Current Poor Mapping Issues

### Sales Invoice - Current vs Proper Mapping

#### Currently Mapped (POORLY):
```python
si.posting_date = mutation.get("date")           # ✓ Correct
si.customer = relation_id or "Guest Customer"    # ❌ Using ID instead of name
si.eboekhouden_mutation_nr = str(mutation_id)    # ✓ Custom field
si.name = invoice_number                         # ❌ WRONG! Overriding system naming
```

#### Missing Critical Fields:
```python
# NOT MAPPED but should be:
si.due_date = None                               # Calculate from date + payment terms
si.payment_terms_template = None                 # Available in API
si.po_no = None                                  # Customer reference
si.currency = None                               # Assume EUR for Dutch
si.conversion_rate = None                        # Important for multi-currency
si.taxes_and_charges = None                      # NO VAT TEMPLATE!
si.remarks = None                                # Should use description
si.is_return = None                              # For credit notes
si.update_stock = None                           # For product invoices
```

### Correct Sales Invoice Mapping:

```python
def create_sales_invoice_properly(mutation_detail, company):
    """Create Sales Invoice with proper field mapping"""

    si = frappe.new_doc("Sales Invoice")

    # Basic Information
    si.company = company
    si.posting_date = mutation_detail.get("date")
    si.set_posting_time = 1  # Allow backdated entries

    # Customer - Fetch actual customer, not just ID
    customer = get_or_create_customer(mutation_detail.get("relationId"))
    si.customer = customer.name

    # Invoice Details
    si.is_return = mutation_detail.get("amount", 0) < 0  # Credit notes

    # Payment Terms
    payment_days = mutation_detail.get("Betalingstermijn", 30)
    si.payment_terms_template = get_payment_terms_template(payment_days)
    si.due_date = add_days(si.posting_date, payment_days)

    # References and Descriptions
    si.po_no = mutation_detail.get("Referentie")  # Customer reference
    si.remarks = mutation_detail.get("description")

    # Currency (Dutch companies use EUR)
    si.currency = "EUR"
    si.conversion_rate = 1.0

    # Tax Template - Based on line items
    if has_vat(mutation_detail):
        si.taxes_and_charges = get_sales_tax_template(company)

    # Custom fields for tracking
    si.custom_eboekhouden_mutation_nr = str(mutation_detail.get("id"))
    si.custom_eboekhouden_invoice_number = mutation_detail.get("invoiceNumber")
    si.custom_eboekhouden_import_date = now()

    # Process line items properly
    if "Regels" in mutation_detail:
        for regel in mutation_detail["Regels"]:
            si.append("items", map_line_item(regel, "sales"))

        # Add tax lines based on BTW codes
        add_tax_lines(si, mutation_detail["Regels"])
    else:
        # Fallback for mutations without line details
        si.append("items", create_single_line_item(mutation_detail))

    return si
```

### Purchase Invoice - Current vs Proper Mapping

#### Currently Mapped (POORLY):
```python
pi.posting_date = mutation.get("date")           # ✓ Correct
pi.supplier = relation_id or "Default Supplier"  # ❌ Using ID instead of name
pi.bill_no = invoice_number                      # ✓ Correct
pi.eboekhouden_mutation_nr = str(mutation_id)    # ✓ Custom field
```

#### Missing Critical Fields:
```python
# NOT MAPPED but should be:
pi.bill_date = None                              # Invoice date from supplier
pi.due_date = None                               # Payment due date
pi.supplier_invoice_no = None                    # Should be bill_no
pi.is_return = None                              # Debit notes
pi.taxes_and_charges = None                      # NO VAT HANDLING!
pi.tax_category = None                           # For reverse charge
pi.remarks = None                                # Description field
```

### Correct Purchase Invoice Mapping:

```python
def create_purchase_invoice_properly(mutation_detail, company):
    """Create Purchase Invoice with proper field mapping"""

    pi = frappe.new_doc("Purchase Invoice")

    # Basic Information
    pi.company = company
    pi.posting_date = mutation_detail.get("date")
    pi.bill_date = mutation_detail.get("date")  # Supplier invoice date
    pi.set_posting_time = 1

    # Supplier - Fetch actual supplier, not just ID
    supplier = get_or_create_supplier(mutation_detail.get("relationId"))
    pi.supplier = supplier.name

    # Invoice References
    pi.bill_no = mutation_detail.get("invoiceNumber")
    pi.supplier_invoice_no = mutation_detail.get("invoiceNumber")

    # Payment Terms
    payment_days = mutation_detail.get("Betalingstermijn", 30)
    pi.payment_terms_template = get_payment_terms_template(payment_days)
    pi.due_date = add_days(pi.bill_date, payment_days)

    # Tax Handling
    if has_vat(mutation_detail):
        pi.taxes_and_charges = get_purchase_tax_template(company)

    # Check for reverse charge scenarios
    if is_reverse_charge(mutation_detail):
        pi.tax_category = "Reverse Charge"

    # Descriptions
    pi.remarks = mutation_detail.get("description")

    # Debit notes
    pi.is_return = mutation_detail.get("amount", 0) < 0

    # Custom tracking fields
    pi.custom_eboekhouden_mutation_nr = str(mutation_detail.get("id"))
    pi.custom_eboekhouden_import_date = now()

    # Process line items
    if "Regels" in mutation_detail:
        for regel in mutation_detail["Regels"]:
            pi.append("items", map_line_item(regel, "purchase"))

        add_tax_lines(pi, mutation_detail["Regels"])

    return pi
```

### Payment Entry - Current vs Proper Mapping

#### Currently Mapped (POORLY):
```python
pe.posting_date = mutation.get("date")           # ✓ Correct
pe.paid_to = "10000 - Kas - NVV"                # ❌ Hardcoded account!
pe.party = relation_id                           # ❌ Using ID instead of name
pe.reference_no = invoice_number or "EB-{id}"   # ⚠️ f-string not used
```

#### Missing Fields:
```python
# NOT MAPPED:
pe.reference_date = None                         # Available
pe.project = None                                # If using projects
pe.cost_center = None                            # Available
pe.remarks = None                                # Description
```

### Line Item Mapping

#### Current (TERRIBLE):
```python
# Everything becomes "Service Item" with no details!
{
    "item_code": "Service Item",
    "description": line_dict["description"],
    "qty": line_dict["qty"],
    "rate": line_dict["rate"],
}
```

#### Proper Line Item Mapping:
```python
def map_line_item(regel, transaction_type):
    """Map e-boekhouden line item to ERPNext format"""

    # Get or create appropriate item
    item_code = get_or_create_item(
        description=regel.get("Omschrijving"),
        unit=regel.get("Eenheid"),
        item_group=determine_item_group(regel)
    )

    line_item = {
        "item_code": item_code,
        "item_name": regel.get("Omschrijving"),
        "description": regel.get("Omschrijving"),
        "qty": flt(regel.get("Aantal", 1)),
        "uom": map_unit_of_measure(regel.get("Eenheid", "Nos")),
        "rate": flt(regel.get("Prijs", 0)),
        "amount": flt(regel.get("Aantal", 1)) * flt(regel.get("Prijs", 0)),
    }

    # Account mapping based on ledger number
    account = get_account_from_grootboek(regel.get("GrootboekNummer"))

    if transaction_type == "sales":
        line_item["income_account"] = account
    else:
        line_item["expense_account"] = account

    # Cost center if specified
    if regel.get("KostenplaatsId"):
        line_item["cost_center"] = get_cost_center(regel.get("KostenplaatsId"))

    return line_item
```

### VAT/Tax Line Mapping (COMPLETELY MISSING):

```python
def add_tax_lines(invoice, regels):
    """Add tax lines based on BTW codes in line items"""

    # Group by BTW code
    btw_summary = {}
    for regel in regels:
        btw_code = regel.get("BTWCode")
        if btw_code and btw_code != "GEEN":
            if btw_code not in btw_summary:
                btw_summary[btw_code] = 0
            # Calculate tax amount
            line_total = flt(regel.get("Aantal", 1)) * flt(regel.get("Prijs", 0))
            tax_rate = get_btw_rate(btw_code)
            btw_summary[btw_code] += line_total * tax_rate / 100

    # Add tax lines
    for btw_code, tax_amount in btw_summary.items():
        tax_account = get_tax_account(btw_code, invoice.company)
        invoice.append("taxes", {
            "charge_type": "Actual",
            "account_head": tax_account,
            "tax_amount": tax_amount,
            "description": get_btw_description(btw_code),
            "rate": 0  # Using actual amount
        })
```

## BTW Code Mapping

```python
BTW_CODE_MAP = {
    # Sales VAT codes
    "HOOG_VERK_21": {
        "rate": 21,
        "description": "BTW verkoop hoog tarief 21%",
        "account_type": "Output VAT"
    },
    "LAAG_VERK_9": {
        "rate": 9,
        "description": "BTW verkoop laag tarief 9%",
        "account_type": "Output VAT"
    },
    "VERL_VERK_L9": {
        "rate": 9,
        "description": "BTW verlegd laag tarief 9%",
        "account_type": "Reverse Charge"
    },

    # Purchase VAT codes
    "HOOG_INK_21": {
        "rate": 21,
        "description": "BTW inkoop hoog tarief 21%",
        "account_type": "Input VAT"
    },
    "LAAG_INK_9": {
        "rate": 9,
        "description": "BTW inkoop laag tarief 9%",
        "account_type": "Input VAT"
    },

    # Special codes
    "GEEN": {
        "rate": 0,
        "description": "Geen BTW",
        "account_type": None
    },
    "BU_EU_VERK": {
        "rate": 0,
        "description": "Buiten EU verkoop",
        "account_type": "Export"
    }
}
```

## Summary of Critical Mapping Fixes Needed

1. **Stop using relation IDs as party names** - Fetch actual party details
2. **Add VAT/BTW handling** - Process BTW codes from line items
3. **Process actual line items** - Stop using generic "Service Item"
4. **Map all available metadata** - Payment terms, references, dates
5. **Use proper account mapping** - Not hardcoded accounts
6. **Add cost center support** - Available in API
7. **Handle credit notes/returns** - Check negative amounts
8. **Support multi-currency** - Default EUR but allow others
9. **Preserve original references** - Don't override system fields
10. **Calculate due dates** - From invoice date + payment terms
