# Recent Updates - January 2025

## Overview
This document summarizes the recent updates made to the Verenigingen system in January 2025, focusing on eBoekhouden integration improvements and test suite enhancements.

## eBoekhouden Integration Improvements

### 1. Fixed Missing Field Error
**Issue**: `Field 'use_enhanced_payment_processing' does not exist on E-Boekhouden Settings`
**Solution**: Added the missing field to the E-Boekhouden Settings DocType
- Location: `verenigingen/doctype/e_boekhouden_settings/e_boekhouden_settings.json`
- Field type: Check (boolean)
- Default value: 1 (enabled)
- Description: "Enable enhanced payment processing with better naming and party resolution"

### 2. Fixed Duplicate Detection Logic
**Issue**: Confusing messages showing "already imported, skipping" followed by "Successfully imported"
**Root Cause**: When duplicate invoice numbers were detected, the function returned the existing document but still logged it as successfully imported
**Solution**:
- Changed duplicate detection to return `None` instead of the existing document
- Updated batch processing to properly count skipped items
- Fixed in: `eboekhouden_rest_full_migration.py` lines 2273-2282 and 3364-3367

### 3. Zero-Amount Invoice Handling
**Issue**: Many zero-amount invoices were being created from eBoekhouden tracking entries
**Analysis**: ERPNext DOES support zero-amount invoices - no framework limitation
**Solution**:
- Removed aggressive skipping of zero-amount invoices
- Only skip clear automated system imports (WooCommerce automatic imports)
- All other zero-amount invoices are now imported normally
- Updated in: `should_skip_mutation()` function

### 4. Enhanced Party Naming
**Issue**: Generic names like "E-Boekhouden Relation 12345" despite party resolver integration
**Root Cause**: API returning empty name fields for some relations
**Solution**:
- Added comprehensive logging to understand API responses
- Enhanced party resolver to log when relations have no name data
- Added fallback to extract names from transaction descriptions
- Updated files: `party_resolver.py` lines 95-111, 140-158, 212-230

### 5. Dynamic Cash Account Resolution
**Issue**: Hardcoded cash account references "10000 - Kas - NVV"
**Solution**:
- Created `get_appropriate_cash_account()` function with intelligent fallbacks:
  1. Company's default cash account
  2. Cash account with "Kas" in name
  3. Any cash account for the company
  4. Bank account as fallback
  5. Create new cash account if none exists
- Replaced all hardcoded references
- Added in: `eboekhouden_rest_full_migration.py` lines 62-143

## Test Suite Enhancements

### Customer Cleanup Gap Fixed
**Issue**: Customers created during membership application approval were not being cleaned up by test suite
**Impact**: Leftover customer records causing test conflicts and database pollution

### Solution 1: Enhanced Base Test Case
Updated `VereningingenTestCase` in `tests/utils/base.py`:
- Added automatic customer cleanup in `tearDown()`
- Tracks customers linked to Members and Membership Applications
- Cleans up customer dependencies (invoices, payments, SEPA mandates) before deleting customers
- Cleanup happens automatically - no code changes needed in individual tests

### Solution 2: Enhanced Test Cleanup Utility
Created `tests/fixtures/enhanced_test_cleanup.py`:
- Standalone cleanup utility for complex scenarios
- Can clean up orphaned test customers
- Provides pattern-based cleanup (e.g., all customers matching "TEST-*")
- Useful for manual cleanup of legacy test data

### Usage Example
```python
from verenigingen.tests.utils.base import VereningingenTestCase

class TestMembershipApplication(VereningingenTestCase):
    def test_application_approval(self):
        # Create application
        app = create_test_application()
        self.track_doc("Membership Application", app.name)

        # Approve (creates member AND customer automatically)
        member = approve_application(app)
        self.track_doc("Member", member.name)

        # Customer cleanup happens automatically in tearDown()!
```

## Active Code Files Modified

### Core Integration Files
1. **`vereinigingen/utils/eboekhouden/eboekhouden_rest_full_migration.py`**
   - Added `get_appropriate_cash_account()` function
   - Fixed duplicate detection logic
   - Updated zero-amount invoice handling
   - Removed hardcoded account references

2. **`verenigingen/utils/eboekhouden/party_resolver.py`**
   - Enhanced logging for empty relation data
   - Added description-based name extraction fallback
   - Improved error reporting

3. **`verenigingen/verenigingen/doctype/e_boekhouden_settings/e_boekhouden_settings.json`**
   - Added `use_enhanced_payment_processing` field

### Test Infrastructure Files
1. **`verenigingen/tests/utils/base.py`**
   - Added `_cleanup_member_customers()` method
   - Added `_cleanup_customer_dependencies()` method
   - Enhanced `tearDown()` to include customer cleanup

2. **`verenigingen/tests/fixtures/enhanced_test_cleanup.py`** (NEW)
   - Complete test cleanup utility
   - Pattern-based customer cleanup
   - Orphaned customer detection

## Migration Notes

### For Developers
1. Run `bench migrate` after pulling these changes to add the new field
2. Monitor logs for "E-Boekhouden Empty Relation" errors to understand API data quality
3. Use `VereningingenTestCase` as base class for all new tests

### For System Administrators
1. The `use_enhanced_payment_processing` field defaults to enabled (checked)
2. Zero-amount invoices will now be imported - review if this matches business requirements
3. Cash account selection is now dynamic - ensure at least one cash account exists per company

## Known Issues Remaining
1. Some eBoekhouden relations return empty name data from API - needs investigation
2. Generic party names still created when API returns no data (but now logged)
3. Consider implementing batch party enrichment for provisional entries

## Performance Impact
- Minimal performance impact from dynamic account lookups (cached after first use)
- Test cleanup may be slightly slower due to customer dependency checks
- Overall migration performance unchanged

## Next Steps
1. Monitor party naming improvements in production
2. Consider implementing party merge UI using existing merge functionality
3. Investigate why some eBoekhouden relations have no name data
4. Add automated tests for the new cleanup functionality
