# eBoekhouden API Analysis & Cleanup Recommendations

## Executive Summary

After analyzing all `@frappe.whitelist()` decorated functions across the eBoekhouden integration, I've identified **77+ API endpoints** that can be reduced to approximately **20 focused, production-ready endpoints**.

## Current API Categorization

### 🟢 Core Production APIs (MUST KEEP - 20 endpoints)

#### Import Manager APIs (`import_manager.py`)
1. `clean_import_all()` - Core production import function
2. `update_existing_imports()` - Update existing imports
3. `get_import_status()` - Status monitoring

#### Primary Migration APIs (`eboekhouden_rest_full_migration.py`)
4. `full_rest_migration_all_mutations()` - Main migration function
5. `migration_status_summary()` - Migration monitoring
6. `get_progress_info()` - Real-time progress tracking
7. `import_opening_balances_only()` - Opening balance import

#### Essential Connection & Preview APIs (`eboekhouden_api.py`)
8. `test_api_connection()` - Connection testing (used in JS)
9. `preview_chart_of_accounts()` - Preview CoA (used in JS)
10. `get_dashboard_data_api()` - Dashboard data
11. `fix_account_types()` - Account type correction

#### Account Management APIs (`eboekhouden_account_manager.py`)
12. `get_eboekhouden_accounts_summary()` - Account overview
13. `cleanup_eboekhouden_accounts_with_confirmation()` - Account cleanup
14. `get_account_cleanup_status()` - Cleanup monitoring

#### Item Mapping APIs (`eboekhouden_item_mapping_tool.py`)
15. `get_unmapped_accounts()` - Mapping management
16. `create_mapping()` - Create new mappings

#### Clean Import APIs (`eboekhouden_clean_reimport.py`)
17. `preview_clean_import()` - Preview clean import
18. `execute_clean_import()` - Execute clean import
19. `setup_enhanced_infrastructure()` - Setup infrastructure

#### Configuration APIs
20. `setup_date_range_fields()` - Date field setup

### 🟡 Legacy/Backup APIs (CONSIDER REMOVING - 35 endpoints)

#### Backup File APIs (`eboekhouden_rest_full_migration_backup_20250117.py`)
- `export_unprocessed_mutations_csv()` - CSV export (duplicate)
- `export_unprocessed_mutations()` - JSON export (duplicate)
- `migration_status_summary()` - Status summary (duplicate)
- `full_rest_migration_all_mutations()` - Migration function (duplicate)
- `get_progress_info()` - Progress info (duplicate)
- `test_single_mutation_import()` - Single mutation test (duplicate)
- `get_mutation_gap_report()` - Gap report (duplicate)
- `import_opening_balances_only()` - Opening balance import (duplicate)
- `debug_start_full_rest_import()` - Debug function (duplicate)
- `debug_payment_terms_issue()` - Debug function (duplicate)
- `debug_specific_mutation_processing()` - Debug function (duplicate)

**Recommendation:** Remove entire backup file - contains 13 duplicate functions.

### 🔴 Debug/Test APIs (REMOVE - 42 endpoints)

#### Debug APIs (`eboekhouden_api.py`)
- `debug_settings()` - Debug E-Boekhouden Settings
- `test_session_token_only()` - Token testing
- `discover_api_structure()` - API discovery
- `test_raw_request()` - Raw request testing
- `test_correct_endpoints()` - Endpoint testing
- `test_chart_of_accounts_migration()` - CoA migration test
- `test_cost_center_migration()` - Cost center test
- `preview_customers()` - Customer preview
- `debug_rest_relations_raw()` - Raw relations debug
- `debug_rest_vs_soap_same_relations()` - SOAP vs REST comparison
- `test_individual_relation_endpoint()` - Individual endpoint test
- `preview_suppliers()` - Supplier preview
- `test_customer_migration()` - Customer migration test
- `test_supplier_migration()` - Supplier migration test
- `test_simple_migration()` - Simple migration test
- `create_test_migration()` - Test migration creation
- `test_dashboard_data()` - Dashboard testing
- `debug_transaction_data()` - Transaction debug
- `test_ledger_id_mapping()` - Ledger mapping test
- `test_document_retrieval()` - Document retrieval test
- `test_token_issue_debug()` - Token debug
- `test_mutation_zero()` - Mutation zero test
- `test_iterator_starting_point()` - Iterator testing
- `explore_invoice_fields()` - Field exploration
- `debug_mutation_1319()` - Specific mutation debug
- `check_equity_import_status()` - Equity import check
- `analyze_equity_mutations()` - Equity analysis
- `test_enhanced_memorial_logic()` - Memorial logic test
- `analyze_memorial_bookings()` - Memorial analysis
- `analyze_payment_mutations()` - Payment analysis
- `compare_api_relation_data()` - API comparison

#### Test APIs in Other Files
- `test_single_mutation_import()` (migration files)
- `debug_opening_balance_import()` (migration redesign)
- `test_single_mutation()` (migration)
- `test_eboekhouden_connection()` (connection test)

## JavaScript Usage Analysis

### Active JavaScript Usage Found:
```javascript
// e_boekhouden_settings.js
method: 'verenigingen.utils.eboekhouden.eboekhouden_api.preview_chart_of_accounts'

// e_boekhouden_migration_original.js
method: 'verenigingen.utils.eboekhouden.eboekhouden_api.test_api_connection'
```

### Inactive APIs (No JS References):
- All debug/test functions
- Most preview functions (except preview_chart_of_accounts)
- All backup file functions

## Cleanup Recommendations

### Phase 1: Remove Debug/Test APIs (42 endpoints)
```python
# Files to clean up:
# 1. eboekhouden_api.py - Remove all debug_* and test_* functions
# 2. Remove test-specific API files
# 3. Clean up mutation-specific debug functions
```

### Phase 2: Remove Legacy/Backup APIs (35 endpoints)
```python
# Files to remove:
# 1. eboekhouden_rest_full_migration_backup_20250117.py (entire file)
# 2. Consolidate duplicate functions in other files
```

### Phase 3: Consolidate Similar Functions
```python
# Consolidate these patterns:
# - Multiple "preview_*" functions → single preview API with type parameter
# - Multiple "test_*_migration" → single test API with migration_type parameter
# - Multiple status/summary functions → unified status API
```

## Proposed Final API Structure (20 endpoints)

### 1. Import & Migration (7 APIs)
- `clean_import_all()` - Primary import function
- `update_existing_imports()` - Update imports
- `get_import_status()` - Status monitoring
- `full_rest_migration()` - Complete migration
- `get_migration_progress()` - Progress tracking
- `import_opening_balances()` - Opening balances
- `preview_migration()` - Migration preview

### 2. Connection & Testing (3 APIs)
- `test_connection()` - Connection testing
- `preview_data()` - Data preview (with type parameter)
- `validate_settings()` - Settings validation

### 3. Account Management (4 APIs)
- `get_accounts_summary()` - Account overview
- `cleanup_accounts()` - Account cleanup
- `get_cleanup_status()` - Cleanup monitoring
- `fix_account_types()` - Type correction

### 4. Mapping Management (3 APIs)
- `get_unmapped_accounts()` - Mapping overview
- `create_mapping()` - Create mappings
- `validate_mappings()` - Mapping validation

### 5. Configuration & Setup (3 APIs)
- `setup_infrastructure()` - Infrastructure setup
- `configure_date_fields()` - Date configuration
- `get_configuration_status()` - Config status

## Implementation Steps

1. **Backup Current State**
   ```bash
   cp -r verenigingen/utils/eboekhouden verenigingen/utils/eboekhouden_backup_$(date +%Y%m%d)
   ```

2. **Remove Debug APIs**
   - Edit `eboekhouden_api.py` to remove all `debug_*` and `test_*` functions
   - Keep only production functions

3. **Remove Backup File**
   ```bash
   rm verenigingen/utils/eboekhouden/eboekhouden_rest_full_migration_backup_20250117.py
   ```

4. **Consolidate Duplicate Functions**
   - Merge similar functions with parameters
   - Update JavaScript calls to use consolidated APIs

5. **Update Documentation**
   - Update API documentation
   - Update JavaScript references
   - Test all remaining endpoints

## Risk Assessment

- **Low Risk**: Removing debug/test functions (no production impact)
- **Medium Risk**: Removing backup file (ensure no active references)
- **High Risk**: Consolidating active APIs (requires careful JavaScript updates)

## Expected Results

- **Reduction**: From 77+ endpoints to 20 focused endpoints (74% reduction)
- **Maintainability**: Cleaner, more focused API surface
- **Performance**: Reduced memory footprint and faster imports
- **Security**: Fewer attack vectors through debug endpoints

## Files Requiring Changes

### Files to Modify:
1. `verenigingen/utils/eboekhouden/eboekhouden_api.py` - Remove debug functions
2. `verenigingen/utils/eboekhouden/import_manager.py` - Keep as-is (production ready)
3. `verenigingen/api/eboekhouden_*.py` - Review and consolidate
4. JavaScript files using eBoekhouden APIs - Update references

### Files to Remove:
1. `verenigingen/utils/eboekhouden/eboekhouden_rest_full_migration_backup_20250117.py`
2. Any other test-specific files identified

This cleanup will result in a much more maintainable and secure eBoekhouden integration with clear separation between production and development functionality.
