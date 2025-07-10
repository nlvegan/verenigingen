# eBoekhouden Import Fixes Summary

## Date: 2025-01-08

### Issues Fixed:

1. **Purchase Invoice Payable Account (FIXED ✓)**
   - **Problem**: All Purchase Invoices were using `18100 - Te betalen sociale lasten - NVV` (Social Security Payables)
   - **Solution**: Changed to use `19290 - Te betalen bedragen - NVV` (General Payables) as default
   - **Exception**: Tax authority invoices with acceptgiro patterns will still use 18100 (correct behavior)
   - **Impact**: 697 existing Purchase Invoices updated

2. **Cost Center Assignment (FIXED ✓)**
   - **Problem**: All items were assigned to `magazine - NVV` cost center
   - **Solution**: Changed to use `Main - NVV` as default cost center
   - **Impact**: 1,291 Purchase Invoice Items updated

3. **Sales Invoice Customer Names (PARTIALLY FIXED ✓)**
   - **Problem**: All Sales Invoices showed "E-Boekhouden Import" as customer
   - **Solution**: Enhanced customer extraction logic to:
     - Use relationId from API to fetch/create proper customers
     - Extract customer names from mutation descriptions
     - Skip WooCommerce orders (no customer data available)
   - **Limitation**: Existing submitted invoices cannot be updated (ERPNext restriction)
   - **Future Impact**: New imports will have proper customer names

### Code Changes Made:

1. **`_get_payable_account()` function**:
   - Now prioritizes "Te betalen bedragen" account
   - Excludes social security accounts unless specifically needed
   - Updated fallback to correct account

2. **`_get_main_cost_center()` function**:
   - New helper function to get Main cost center
   - Fallback to any non-group cost center if Main not found

3. **Purchase/Sales Invoice creation**:
   - Added cost center assignment to all item lines
   - Enhanced customer extraction for Sales Invoices
   - Pass mutation data to customer creation function

4. **`_get_or_create_customer()` function**:
   - Enhanced to accept mutation data parameter
   - Extracts customer names from descriptions
   - Creates proper customer records instead of generic imports

### Next Steps:

1. **Projects and Mappings**: Create project mappings as mentioned by user
2. **Monitor New Imports**: Verify that new imports use correct accounts and customer names
3. **WooCommerce Integration**: Consider enhancing to capture actual customer names from WooCommerce orders

### Important Notes:

- Bench restart was required and completed
- Existing submitted documents remain unchanged (only draft/cancelled can be modified)
- Future imports will use the corrected logic
