# E-Boekhouden to ERPNext Field Mapping Issues - Summary

## Critical Field Mapping Problems

### 1. **Party Creation - Using IDs Instead of Names** ❌
```python
# CURRENT (WRONG):
si.customer = relation_id or "Guest Customer"  # Creates customer like "REL123"

# SHOULD BE:
customer = get_or_create_customer_with_proper_name(relation_id)
si.customer = customer.name  # "Acme Corporation B.V."
```

### 2. **No VAT/BTW Handling At All** ❌
```python
# CURRENT:
# No tax lines, no tax template, no BTW processing

# SHOULD BE:
# 1. Fetch full mutation details to get line items
mutation_detail = iterator.fetch_mutation_detail(mutation_id)

# 2. Process BTW codes from line items
for regel in mutation_detail.get("Regels", []):
    btw_code = regel.get("BTWCode")  # e.g., "HOOG_VERK_21"
    # Add appropriate tax lines
```

### 3. **Single Generic Line Item Only** ❌
```python
# CURRENT:
si.append("items", {
    "item_code": "Service Item",  # Everything is "Service Item"!
    "description": "Some description",
    "qty": 1,
    "rate": total_amount
})

# SHOULD BE:
# Process actual line items from Regels
for regel in mutation_detail.get("Regels", []):
    si.append("items", {
        "item_code": get_or_create_item(regel.get("Omschrijving")),
        "description": regel.get("Omschrijving"),
        "qty": regel.get("Aantal"),
        "rate": regel.get("Prijs"),
        "income_account": map_grootboek_to_account(regel.get("GrootboekNummer"))
    })
```

### 4. **Missing Invoice Metadata** ❌
```python
# CURRENT - Missing fields:
- due_date (can calculate from date + Betalingstermijn)
- payment_terms_template
- po_no (customer reference)
- remarks (proper description)
- currency (assuming EUR)

# SHOULD MAP:
si.due_date = add_days(si.posting_date, mutation.get("Betalingstermijn", 30))
si.po_no = mutation.get("Referentie")
si.remarks = mutation.get("description")
si.currency = "EUR"
```

### 5. **Hardcoded Accounts** ❌
```python
# CURRENT:
pe.paid_to = "10000 - Kas - NVV"  # Hardcoded!

# SHOULD BE:
pe.paid_to = get_bank_account_from_mutation(mutation)
```

### 6. **Wrong Field Usage** ❌
```python
# CURRENT:
si.name = invoice_number  # WRONG! This overrides ERPNext naming

# SHOULD BE:
# Let ERPNext handle naming, store reference in custom field
si.custom_eboekhouden_invoice_number = invoice_number
```

## Data Not Being Used From API

The REST API provides these fields that are IGNORED:
- `Regels` (line items) - Contains item details and BTW codes
- `Betalingstermijn` - Payment terms in days
- `Referentie` - Reference number
- `BTWCode` per line - VAT rates and types
- `GrootboekNummer` per line - GL account mapping
- `KostenplaatsId` - Cost center
- `Aantal` and `Prijs` per line - Quantity and price

## Quick Fix Priority List

1. **Fetch full mutation details** - Use `fetch_mutation_detail()` not just the summary
2. **Process line items** - Loop through `Regels` array
3. **Add BTW/VAT handling** - Map BTW codes to tax accounts
4. **Fix party names** - Create proper customer/supplier names
5. **Calculate due dates** - Use Betalingstermijn field
6. **Map accounts properly** - Use GrootboekNummer for GL mapping

## Implementation Path

1. **Phase 1**: Fix the data fetching to get full details
2. **Phase 2**: Add VAT processing from line items
3. **Phase 3**: Improve party and account mapping
4. **Phase 4**: Add all missing metadata fields

The current implementation is using maybe 20% of the available data from the API!
