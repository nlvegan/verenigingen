# eBoekhouden Single Source of Truth (SSoT) Violations Report

## Executive Summary
Investigation revealed **CRITICAL** SSoT violations in the eBoekhouden import logic where ERPNext account selection is used instead of eBoekhouden's ledgerID data. The Quality-Control-Enforcer correctly identified the unified processor as the most severe violator.

## Issues Found and Status

### 1. 🔴 CRITICAL - Unified Processor (UNFIXED)
**File**: `/home/frappe/frappe-bench/apps/verenigingen/verenigingen/e_boekhouden/utils/eboekhouden_unified_processor.py`

#### Sales Invoice Processing (Lines 9-41)
- **Issue**: Uses `get_correct_receivable_account(company)` instead of `mutation.get("ledgerId")`
- **Impact**: Completely ignores eBoekhouden's specified receivable account
- **Current Behavior**: Always uses "Te ontvangen bedragen" (13900) regardless of eBoekhouden data
- **SSoT Violation**: SEVERE - mutation data contains ledgerID but is completely ignored

#### Purchase Invoice Processing (Lines 44-87)
- **Issue**: Uses `get_creditors_account(company)` instead of `mutation.get("ledgerId")`
- **Impact**: Ignores eBoekhouden's specified payable account
- **Current Behavior**: Uses first available payable account from ERPNext
- **SSoT Violation**: SEVERE - mutation data contains ledgerID but is completely ignored

#### Expense Account Selection (Lines 64-66)
- **Issue**: Queries for expense accounts instead of using eBoekhouden account mapping
- **Impact**: May use wrong expense account for line items
- **SSoT Violation**: MODERATE - doesn't use proper account mapping system

### 2. ✅ FIXED - Main REST Migration File
**File**: `/home/frappe/frappe-bench/apps/verenigingen/verenigingen/e_boekhouden/utils/eboekhouden_rest_full_migration.py`

#### Sales Invoice Creation (`_create_sales_invoice` - Lines 2233-2269)
- **Status**: ✅ **FIXED** - Now uses `mutation_detail.get("ledgerId")` with proper mapping
- **Enhancement**: Added WooCommerce/FactuurSturen special handling
- **Code Quality**: Good error handling and debug logging

#### Purchase Invoice Creation (`_create_purchase_invoice` - Lines 2429-2439)
- **Status**: ✅ **FIXED** - Now uses `mutation_detail.get("ledgerId")` with proper mapping
- **Code Quality**: Consistent with sales invoice approach

### 3. ✅ CORRECT - Journal Entry Creation
**File**: Same file, `_create_journal_entry` function (Lines 2883-2888)

- **Status**: ✅ **CORRECT** - Properly uses ledgerID for account mapping
- **Implementation**: Uses SQL query to `E-Boekhouden Ledger Mapping` table
- **Code Quality**: Good SSoT compliance

## Code Quality Review of Recent Fixes

### Strengths
1. **Proper SSoT Implementation**: Uses `_resolve_account_mapping()` function correctly
2. **Special Business Logic**: WooCommerce/FactuurSturen handling is well-implemented
3. **Error Handling**: Good warning messages when ledgerID or mapping is missing
4. **Debug Logging**: Comprehensive logging for troubleshooting
5. **Consistent Pattern**: Both sales and purchase invoices use same approach

### Areas for Improvement
1. **Performance**: Multiple database queries per invoice could be optimized with caching
2. **Account Lookup**: The "Te Ontvangen Bedragen" lookup uses LIKE query which could be more precise
3. **Error Recovery**: Missing fallback when "Te Ontvangen Bedragen" account not found

## Priority Action Items

### 🔴 URGENT - Fix Unified Processor
The unified processor in `eboekhouden_unified_processor.py` needs immediate fixes:

1. **Sales Invoice Processing**:
   ```python
   # CURRENT (WRONG):
   correct_receivable_account = get_correct_receivable_account(company)
   if correct_receivable_account:
       si.debit_to = correct_receivable_account

   # SHOULD BE:
   ledger_id = mut.get("ledgerId")
   if ledger_id:
       account_mapping = _resolve_account_mapping(ledger_id, debug_info)
       if account_mapping and account_mapping.get("erpnext_account"):
           si.debit_to = account_mapping["erpnext_account"]
   ```

2. **Purchase Invoice Processing**:
   ```python
   # CURRENT (WRONG):
   creditors_account = get_creditors_account(company)
   if creditors_account:
       pi.credit_to = creditors_account

   # SHOULD BE:
   ledger_id = mut.get("ledgerId")
   if ledger_id:
       account_mapping = _resolve_account_mapping(ledger_id, debug_info)
       if account_mapping and account_mapping.get("erpnext_account"):
           pi.credit_to = account_mapping["erpnext_account"]
   ```

### 🟡 MEDIUM - Additional Investigations Needed

1. **Payment Entry Creation**: Check if `_create_payment_entry` and `_create_money_transfer_payment_entry` use proper account mapping
2. **Opening Balance Processing**: Verify opening balance imports use correct account mapping
3. **Other Processor Files**: Check `verenigingen/e_boekhouden/utils/processors/` directory for similar issues

## Implementation Recommendations

### For Unified Processor Fix
1. Import the `_resolve_account_mapping` function from the main migration file
2. Add the same WooCommerce/FactuurSturen logic for consistency
3. Add proper error handling for missing ledgerID or mappings
4. Add debug logging similar to the main migration file
5. Consider deprecating the unified processor if the main migration file is preferred

### General Improvements
1. **Centralize Account Mapping**: Create a shared utility function for all import logic
2. **Add Validation**: Ensure all import functions validate required eBoekhouden fields are present
3. **Performance Optimization**: Consider caching account mappings during bulk imports
4. **Documentation**: Add comments explaining SSoT principles in all import functions

## Risk Assessment

- **High Risk**: Any imports using the unified processor will have incorrect account assignments
- **Data Integrity**: Existing imports using unified processor may need correction
- **Business Impact**: Financial reports may be inaccurate due to wrong account classifications

## Recommendation
Fix the unified processor immediately as it represents the most severe SSoT violation and could cause widespread data corruption in imports that use it instead of the main migration file.
