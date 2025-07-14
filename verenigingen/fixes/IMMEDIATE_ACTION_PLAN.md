# E-Boekhouden SINV/PINV Import - IMMEDIATE ACTION PLAN

## 🚨 CRITICAL ISSUES IDENTIFIED

The current e-boekhouden invoice import is **wasting ~80% of available data** and creating **incorrect invoices**:

1. **NO VAT/BTW handling** - Critical for Dutch compliance
2. **Single generic line items** - Loses all transaction detail
3. **Poor party management** - Using IDs instead of names
4. **Missing metadata** - No payment terms, due dates, references
5. **Not fetching full data** - Only using summary, not detailed API data

## 📋 IMMEDIATE NEXT STEPS (This Week)

### Step 1: Test Current vs New Implementation (30 minutes)

Run these commands to see the data quality difference:

```bash
# From bench directory
cd /home/frappe/frappe-bench

# Test what data we can actually get
bench --site dev.veganisme.net execute vereinigingen.fixes.test_new_implementation.test_data_comparison

# Compare old vs new invoice creation
bench --site dev.veganisme.net execute verenigingen.fixes.test_new_implementation.test_invoice_creation_comparison

# Validate API capabilities
bench --site dev.veganisme.net execute verenigingen.fixes.test_new_implementation.validate_api_capabilities
```

### Step 2: Create Required DocTypes (1 hour)

**New DocType:** `E-Boekhouden Account Map`
```json
{
  "fields": [
    {"fieldname": "eboekhouden_grootboek", "fieldtype": "Data", "label": "E-Boekhouden Grootboek", "unique": 1},
    {"fieldname": "erpnext_account", "fieldtype": "Link", "options": "Account", "label": "ERPNext Account"},
    {"fieldname": "account_type", "fieldtype": "Select", "options": "Income\nExpense\nAsset\nLiability", "label": "Account Type"},
    {"fieldname": "auto_created", "fieldtype": "Check", "label": "Auto Created"},
    {"fieldname": "company", "fieldtype": "Link", "options": "Company", "label": "Company"}
  ]
}
```

### Step 3: Add Custom Fields to Existing DocTypes (30 minutes)

**Customer:**
- `custom_eboekhouden_relation_id` (Data)
- `custom_needs_enrichment` (Check)

**Supplier:**
- `custom_eboekhouden_relation_id` (Data)
- `custom_needs_enrichment` (Check)

**Sales Invoice:**
- `custom_eboekhouden_invoice_number` (Data)
- `custom_eboekhouden_relation_id` (Data)
- `custom_eboekhouden_import_date` (Datetime)

**Purchase Invoice:**
- `custom_eboekhouden_relation_id` (Data)
- `custom_eboekhouden_import_date` (Datetime)

### Step 4: Replace Current Implementation (2 hours)

**Replace in:** `vereinigingen/utils/eboekhouden/eboekhouden_rest_full_migration.py`

**Current problematic functions:**
- `_create_sales_invoice()` - Line 2038
- `_create_purchase_invoice()` - Line 2079

**Replace with:**
- `create_sales_invoice_with_full_data()` from `step1_fix_data_fetching.py`
- `create_purchase_invoice_with_full_data()` from `step1_fix_data_fetching.py`

## 🔧 WEEK 1 IMPLEMENTATION TASKS

### Day 1-2: Data Fetching Fix
- [ ] Update mutation processing to use `fetch_mutation_detail()` instead of `fetch_mutation_by_id()`
- [ ] Modify `_create_sales_invoice()` to process `Regels` array
- [ ] Modify `_create_purchase_invoice()` to process `Regels` array
- [ ] Test with 5-10 sample invoices

### Day 3-4: VAT/BTW Implementation
- [ ] Add BTW code mapping to tax accounts
- [ ] Implement `add_vat_lines_to_invoice()` function
- [ ] Create tax accounts automatically if missing
- [ ] Test VAT calculations with Dutch tax rates

### Day 5: Party and Metadata
- [ ] Implement proper customer/supplier resolution
- [ ] Add payment terms and due date calculation
- [ ] Capture all available metadata fields
- [ ] Test complete invoice workflow

## 🧪 TESTING STRATEGY

### Before Changes:
```bash
# Test current implementation
bench --site dev.veganisme.net execute verenigingen.fixes.test_new_implementation.test_invoice_creation_comparison --args '{"mutation_id": 7420}'
```

### After Each Change:
```bash
# Validate improvements
bench --site dev.veganisme.net execute vereinigingen.fixes.step1_fix_data_fetching.test_new_invoice_creation --args '{"mutation_id": 7420}'

# Compare data quality
bench --site dev.veganisme.net execute verenigingen.fixes.step1_fix_data_fetching.compare_old_vs_new_import --args '{"mutation_id": 7420}'
```

### Success Criteria:
- [ ] All invoices have actual line items (not just "Service Item")
- [ ] VAT lines are created for invoices with BTW codes
- [ ] Customers/suppliers have real names (not just IDs)
- [ ] Payment terms and due dates are calculated
- [ ] All available metadata is captured

## 📊 EXPECTED IMPROVEMENTS

| Current | Improved | Impact |
|---------|----------|---------|
| Single "Service Item" | Multiple actual items | ✅ Preserves transaction detail |
| No VAT handling | Proper BTW lines | ✅ Dutch tax compliance |
| Relation IDs as names | Resolved party names | ✅ Better party management |
| Missing payment terms | Calculated due dates | ✅ Payment tracking |
| ~20% data usage | ~95% data usage | ✅ Complete information |

## 🚦 RISK MITIGATION

### Backup Strategy:
1. **Keep existing functions** - Rename to `_create_sales_invoice_old()`
2. **Feature flag** - Add setting to switch between old/new implementation
3. **Gradual rollout** - Test with subset of mutations first

### Error Handling:
1. **Graceful fallbacks** - If full data unavailable, fall back to summary
2. **Validation** - Ensure all created invoices are valid
3. **Logging** - Comprehensive error logging for debugging

### Performance:
1. **Caching** - Cache account mappings and party resolutions
2. **Batch processing** - Process multiple mutations efficiently
3. **Monitoring** - Track import performance and error rates

## 🎯 SUCCESS METRICS

### Week 1 Goals:
- [ ] 100% of new invoices have proper line items
- [ ] 90%+ of invoices with VAT have correct tax lines
- [ ] 80%+ of parties have resolved names (not IDs)
- [ ] All invoices have payment terms when available in API
- [ ] Zero data loss compared to current implementation

### Technical Metrics:
- [ ] Import speed: <2 seconds per invoice
- [ ] Error rate: <5% for normal mutations
- [ ] Data completeness: >95% of available fields captured
- [ ] VAT accuracy: 100% compliance with Dutch rates

## 📞 IMMEDIATE ACTIONS

1. **RIGHT NOW**: Run the test commands above to see current data quality
2. **TODAY**: Create the required custom fields and DocTypes
3. **THIS WEEK**: Implement the improved data fetching and VAT handling
4. **NEXT WEEK**: Test with real data and validate improvements

## 🔗 FILES TO MODIFY

### Primary Implementation:
- `vereinigingen/utils/eboekhouden/eboekhouden_rest_full_migration.py` (main changes)
- `verenigingen/utils/eboekhouden/eboekhouden_rest_iterator.py` (ensure proper usage)

### New Supporting Files:
- `verenigingen/fixes/step1_fix_data_fetching.py` (new implementation)
- `verenigingen/fixes/eboekhouden_utils.py` (utility functions)
- `verenigingen/fixes/test_new_implementation.py` (testing)

### DocType Creation:
- `verenigingen/doctype/e_boekhouden_account_map/` (new)

This plan addresses the critical field mapping issues and ensures we capture and properly save all available data from the e-boekhouden REST API.
