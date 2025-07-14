# E-Boekhouden SINV/PINV Import - Revised Implementation Plan

## Executive Summary

The current implementation wastes ~80% of available data from the e-boekhouden REST API. This plan focuses on properly fetching, mapping, and saving all available invoice data.

## Current State Analysis

### What's Currently Happening:
1. **Only fetching summary data** - Not calling `fetch_mutation_detail()` for full data
2. **No VAT/BTW handling** - Completely ignoring tax information
3. **Single generic line item** - Everything becomes "Service Item"
4. **Poor party management** - Using relation IDs as names
5. **Missing metadata** - No payment terms, due dates, or references

### Available Data Being Ignored:
- `Regels` array with line items including BTW codes
- `Betalingstermijn` (payment terms in days)
- `Referentie` (reference numbers)
- Line-level details: quantity, price, description, VAT code, GL account

## Phase 1: Core Data Capture (Week 1-2)

### 1.1 Fix Data Fetching

**File:** `vereinigingen/utils/eboekhouden/eboekhouden_rest_full_migration.py`

```python
def import_mutation_properly(mutation_id, company):
    """Import mutation with ALL available data"""
    iterator = EBoekhoudenRESTIterator()

    # CRITICAL: Get full details, not just summary!
    mutation_detail = iterator.fetch_mutation_detail(mutation_id)

    if not mutation_detail:
        return {"success": False, "error": f"Mutation {mutation_id} not found"}

    # Now we have access to:
    # - mutation_detail['Regels'] - Line items with VAT
    # - mutation_detail['Betalingstermijn'] - Payment terms
    # - mutation_detail['Referentie'] - References
    # - And much more...
```

### 1.2 Create Proper Field Mapping Structure

**New File:** `verenigingen/utils/eboekhouden/field_mapping.py`

```python
# E-Boekhouden to ERPNext field mapping
INVOICE_FIELD_MAP = {
    # Basic fields
    'date': 'posting_date',
    'invoiceNumber': 'custom_eboekhouden_invoice_number',
    'description': 'remarks',
    'Referentie': 'po_no',  # Customer reference
    'Betalingstermijn': 'payment_days',  # For calculating due_date

    # Will need processing
    'relationId': 'party_lookup',  # Needs party resolution
    'amount': 'total_amount',  # Needs sign handling for returns
}

# BTW Code mapping
BTW_CODE_MAP = {
    'HOOG_VERK_21': {'rate': 21, 'type': 'Output VAT', 'account_suffix': 'BTW te betalen hoog'},
    'LAAG_VERK_9': {'rate': 9, 'type': 'Output VAT', 'account_suffix': 'BTW te betalen laag'},
    'HOOG_INK_21': {'rate': 21, 'type': 'Input VAT', 'account_suffix': 'Voorbelasting hoog'},
    'LAAG_INK_9': {'rate': 9, 'type': 'Input VAT', 'account_suffix': 'Voorbelasting laag'},
    'GEEN': {'rate': 0, 'type': None, 'account_suffix': None},
}
```

### 1.3 Update Invoice Creation Functions

**Modify:** `_create_sales_invoice()` and `_create_purchase_invoice()`

```python
def _create_sales_invoice(mutation_detail, company, cost_center, debug_info):
    """Create Sales Invoice with ALL available fields"""

    si = frappe.new_doc("Sales Invoice")

    # Basic fields
    si.company = company
    si.posting_date = mutation_detail.get("date")
    si.set_posting_time = 1

    # Customer - properly resolved
    customer = resolve_customer(mutation_detail.get("relationId"))
    si.customer = customer

    # Currency
    si.currency = "EUR"
    si.conversion_rate = 1.0

    # Payment terms and due date
    payment_days = mutation_detail.get("Betalingstermijn", 30)
    if payment_days:
        si.payment_terms_template = get_or_create_payment_terms(payment_days)
        si.due_date = add_days(si.posting_date, payment_days)

    # References
    if mutation_detail.get("Referentie"):
        si.po_no = mutation_detail.get("Referentie")

    # Description
    si.remarks = mutation_detail.get("description", "")

    # Check for credit notes
    total_amount = flt(mutation_detail.get("amount", 0))
    si.is_return = total_amount < 0

    # Custom tracking fields
    si.custom_eboekhouden_mutation_nr = str(mutation_detail.get("id"))
    si.custom_eboekhouden_invoice_number = mutation_detail.get("invoiceNumber")
    si.custom_eboekhouden_import_date = now()

    # CRITICAL: Process line items
    if "Regels" in mutation_detail:
        process_line_items(si, mutation_detail["Regels"], "sales")
        add_tax_lines(si, mutation_detail["Regels"], "sales")
    else:
        # Fallback only if no line items
        create_single_line_fallback(si, mutation_detail)

    si.save()
    si.submit()

    return si
```

## Phase 2: VAT/BTW Implementation (Week 2-3)

### 2.1 Line Item Processing with VAT

```python
def process_line_items(invoice, regels, invoice_type):
    """Process e-boekhouden line items with proper VAT handling"""

    for regel in regels:
        # Get or create item
        item_code = get_or_create_item_from_description(
            regel.get("Omschrijving", "Service"),
            regel.get("Eenheid", "Nos")
        )

        # Map GL account
        gl_account = map_grootboek_to_erpnext_account(
            regel.get("GrootboekNummer"),
            invoice_type
        )

        line_item = {
            "item_code": item_code,
            "item_name": regel.get("Omschrijving", "Service"),
            "description": regel.get("Omschrijving", ""),
            "qty": flt(regel.get("Aantal", 1)),
            "uom": map_unit_of_measure(regel.get("Eenheid", "Nos")),
            "rate": flt(regel.get("Prijs", 0)),
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
```

### 2.2 Tax Line Creation

```python
def add_tax_lines(invoice, regels, invoice_type):
    """Add tax lines based on BTW codes"""

    # Group by BTW code
    btw_summary = {}

    for regel in regels:
        btw_code = regel.get("BTWCode", "").upper()

        if btw_code and btw_code != "GEEN":
            if btw_code not in btw_summary:
                btw_info = BTW_CODE_MAP.get(btw_code, {})
                btw_summary[btw_code] = {
                    "taxable_amount": 0,
                    "rate": btw_info.get("rate", 0)
                }

            # Calculate taxable amount
            line_total = flt(regel.get("Aantal", 1)) * flt(regel.get("Prijs", 0))
            btw_summary[btw_code]["taxable_amount"] += line_total

    # Create tax lines
    for btw_code, data in btw_summary.items():
        if data["rate"] > 0:
            tax_amount = data["taxable_amount"] * data["rate"] / 100
            tax_account = get_tax_account(btw_code, invoice_type, invoice.company)

            invoice.append("taxes", {
                "charge_type": "Actual",
                "account_head": tax_account,
                "tax_amount": tax_amount,
                "description": f"BTW {data['rate']}%",
                "rate": 0,  # Using actual amount
                "base_tax_amount": tax_amount
            })
```

## Phase 3: Party Management (Week 3)

### 3.1 Intelligent Party Resolution

**New File:** `verenigingen/utils/eboekhouden/party_resolver.py`

```python
def resolve_customer(relation_id):
    """Resolve relation ID to proper customer"""
    if not relation_id:
        return get_default_customer()

    # Check existing mapping
    existing = frappe.db.get_value(
        "Customer",
        {"custom_eboekhouden_relation_id": relation_id},
        "name"
    )

    if existing:
        return existing

    # Try to get relation details from e-boekhouden
    relation_details = fetch_relation_details(relation_id)

    if relation_details:
        return create_customer_from_relation(relation_details)
    else:
        # Create with ID but mark for review
        return create_provisional_customer(relation_id)

def create_customer_from_relation(relation_details):
    """Create customer with proper details"""
    customer = frappe.new_doc("Customer")

    # Use actual name if available
    customer.customer_name = relation_details.get("name", f"E-Boekhouden {relation_details['id']}")
    customer.customer_group = "All Customer Groups"
    customer.territory = "All Territories"

    # Store relation ID for future matching
    customer.custom_eboekhouden_relation_id = relation_details["id"]

    # Add contact info if available
    if relation_details.get("email"):
        add_contact(customer, relation_details)

    customer.insert()
    return customer.name
```

### 3.2 Provisional Party Management

```python
def create_provisional_customer(relation_id):
    """Create provisional customer for later enrichment"""
    customer = frappe.new_doc("Customer")
    customer.customer_name = f"Provisional - {relation_id}"
    customer.customer_group = "All Customer Groups"
    customer.territory = "All Territories"
    customer.custom_eboekhouden_relation_id = relation_id
    customer.custom_needs_enrichment = 1
    customer.insert()

    # Add to enrichment queue
    add_to_enrichment_queue("Customer", customer.name, relation_id)

    return customer.name
```

## Phase 4: Supporting Infrastructure (Week 4)

### 4.1 Account Mapping Enhancement

**New DocType:** `E-Boekhouden Account Map`
- `eboekhouden_grootboek` (Data)
- `erpnext_account` (Link to Account)
- `account_type` (Select: Income/Expense/Asset/Liability)
- `auto_created` (Check)

### 4.2 Tax Template Management

```python
def get_or_create_payment_terms(days):
    """Get or create payment terms template"""
    template_name = f"Netto {days} dagen"

    if not frappe.db.exists("Payment Terms Template", template_name):
        template = frappe.new_doc("Payment Terms Template")
        template.template_name = template_name
        template.append("terms", {
            "due_date_based_on": "Day(s) after invoice date",
            "credit_days": days,
            "invoice_portion": 100.0
        })
        template.insert()

    return template_name
```

### 4.3 Item Management

```python
def get_or_create_item_from_description(description, unit="Nos"):
    """Smart item creation based on description"""

    # Check for existing item
    existing = find_item_by_description(description)
    if existing:
        return existing

    # Create new item
    item = frappe.new_doc("Item")
    item.item_code = generate_item_code(description)
    item.item_name = description[:140]  # Limit length
    item.description = description
    item.item_group = determine_item_group(description)
    item.stock_uom = map_unit_of_measure(unit)
    item.is_stock_item = 0
    item.is_sales_item = 1
    item.is_purchase_item = 1

    # Add Dutch description as well
    item.custom_dutch_description = description

    item.insert()
    return item.name
```

## Phase 5: Migration and Cleanup (Week 5)

### 5.1 Migration Script for Existing Data

```python
@frappe.whitelist()
def enrich_existing_invoices():
    """Re-process existing invoices to capture missing data"""

    # Get all invoices imported from e-boekhouden
    invoices = frappe.get_all(
        "Sales Invoice",
        filters={"custom_eboekhouden_mutation_nr": ["!=", ""]},
        fields=["name", "custom_eboekhouden_mutation_nr"]
    )

    enriched = 0
    failed = 0

    for inv in invoices:
        try:
            # Fetch full mutation details
            mutation_detail = fetch_mutation_detail(inv.custom_eboekhouden_mutation_nr)

            if mutation_detail:
                enrich_invoice(inv.name, mutation_detail)
                enriched += 1
        except Exception as e:
            failed += 1
            log_enrichment_failure(inv.name, str(e))

    return {"enriched": enriched, "failed": failed}
```

### 5.2 Data Quality Dashboard

**New Page:** `e-boekhouden-import-quality`
- Shows percentage of invoices with complete data
- Lists provisional parties needing enrichment
- Displays unmapped GL accounts
- Shows missing VAT configurations

## Implementation Checklist

### Week 1-2: Core Data Capture
- [ ] Update `_create_sales_invoice()` to fetch full mutation details
- [ ] Update `_create_purchase_invoice()` to fetch full mutation details
- [ ] Create field mapping configuration
- [ ] Add all available fields to invoice creation
- [ ] Test with sample invoices

### Week 2-3: VAT Implementation
- [ ] Implement line item processing
- [ ] Create BTW code mapping
- [ ] Add tax line creation
- [ ] Create tax accounts if missing
- [ ] Test VAT calculations

### Week 3: Party Management
- [ ] Implement party resolver
- [ ] Create provisional party system
- [ ] Add enrichment queue
- [ ] Test party deduplication

### Week 4: Supporting Infrastructure
- [ ] Create account mapping DocType
- [ ] Implement payment terms creation
- [ ] Enhance item creation logic
- [ ] Add unit of measure mapping

### Week 5: Migration and Cleanup
- [ ] Create enrichment script
- [ ] Build data quality dashboard
- [ ] Run enrichment on existing data
- [ ] Document new features

## Success Metrics

1. **Data Completeness**
   - 100% of new invoices have line items (not just "Service Item")
   - 95%+ of invoices have proper VAT lines
   - 90%+ of parties have real names (not IDs)
   - All invoices have payment terms and due dates

2. **Technical Metrics**
   - Zero hardcoded accounts
   - All available API fields mapped
   - Proper error handling for missing data
   - Performance: <2s per invoice import

3. **Business Value**
   - Accurate VAT reporting
   - Proper payment term tracking
   - Better party management
   - Complete audit trail

## Risk Mitigation

1. **API Changes**: Monitor e-boekhouden API for updates
2. **Data Quality**: Handle missing/incomplete data gracefully
3. **Performance**: Implement caching for frequently used lookups
4. **Backward Compatibility**: Ensure existing imports continue to work

## Next Steps

1. **Immediate**: Start with fixing data fetching (Phase 1.1)
2. **This Week**: Implement core field mapping (Phase 1.2-1.3)
3. **Next Week**: Add VAT handling (Phase 2)
4. **Ongoing**: Monitor import quality and iterate
