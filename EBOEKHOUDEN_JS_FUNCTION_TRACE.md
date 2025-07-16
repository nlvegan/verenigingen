# E-Boekhouden JavaScript Function Call Trace

## Complete Function Call Analysis from e_boekhouden_migration.js

### ✅ WORKING API CALLS (10 functions)

1. **`analyze_eboekhouden_data`** (Line 304)
   - Path: `verenigingen.api.update_prepare_system_button.analyze_eboekhouden_data`
   - Status: ✅ EXISTS and WHITELISTED
   - Purpose: Analyzes E-Boekhouden data structure

2. **`start_migration`** (Lines 587, 1045, 1314)
   - Path: `verenigingen.verenigingen.doctype.e_boekhouden_migration.e_boekhouden_migration.start_migration`
   - Status: ✅ EXISTS and WHITELISTED
   - Purpose: Main migration entry point

3. **`test_connection`** (Line 614)
   - Path: `verenigingen.utils.eboekhouden_soap_api.test_connection`
   - Status: ✅ EXISTS and WHITELISTED
   - Purpose: Tests SOAP API connection
   - NOTE: This is the ONLY SOAP API call from the UI

4. **`check_migration_data_quality`** (Lines 787, 1668)
   - Path: `verenigingen.verenigingen.doctype.e_boekhouden_migration.e_boekhouden_migration.check_migration_data_quality`
   - Status: ✅ EXISTS and WHITELISTED
   - Purpose: Validates migration data quality

5. **`cleanup_chart_of_accounts`** (Line 1003)
   - Path: `verenigingen.verenigingen.doctype.e_boekhouden_migration.e_boekhouden_migration.cleanup_chart_of_accounts`
   - Status: ✅ EXISTS and WHITELISTED
   - Purpose: Cleans up chart of accounts

6. **`check_rest_api_status`** (Line 1340)
   - Path: `verenigingen.verenigingen.doctype.e_boekhouden_migration.e_boekhouden_migration.check_rest_api_status`
   - Status: ✅ EXISTS and WHITELISTED
   - Purpose: Checks if REST API is configured

7. **`test_mutation_zero`** (Line 1375)
   - Path: `verenigingen.utils.eboekhouden_rest_iterator.test_mutation_zero`
   - Status: ✅ EXISTS and WHITELISTED
   - Purpose: Tests REST API by fetching mutation ID 0

8. **`start_transaction_import`** (Line 1405)
   - Path: `verenigingen.verenigingen.doctype.e_boekhouden_migration.e_boekhouden_migration.start_transaction_import`
   - Status: ✅ EXISTS and WHITELISTED
   - Purpose: Starts transaction import via REST API

9. **`import_opening_balances_only`** (Line 1575)
   - Path: `verenigingen.verenigingen.doctype.e_boekhouden_migration.e_boekhouden_migration.import_opening_balances_only`
   - Status: ✅ EXISTS and WHITELISTED
   - Purpose: Imports only opening balances

10. **`import_single_mutation`** (Line 1900)
    - Path: `verenigingen.verenigingen.doctype.e_boekhouden_migration.e_boekhouden_migration.import_single_mutation`
    - Status: ✅ EXISTS and WHITELISTED
    - Purpose: Imports a single mutation by ID

### ❌ MISSING API CALLS (6 functions)

1. **`get_migration_statistics`** (Line 635)
   - Path: `verenigingen.api.eboekhouden_migration_redesign.get_migration_statistics`
   - Status: ❌ FILE DOES NOT EXIST
   - Impact: Statistics display may fail

2. **`review_account_types`** (Line 810)
   - Path: `verenigingen.api.check_account_types.review_account_types`
   - Status: ❌ FILE DOES NOT EXIST
   - Impact: Account type review functionality broken

3. **`fix_account_type_issues`** (Line 872)
   - Path: `verenigingen.api.check_account_types.fix_account_type_issues`
   - Status: ❌ FILE DOES NOT EXIST
   - Impact: Cannot fix account type issues

4. **`update_account_type_mapping`** (Lines 1117, 1171)
   - Path: `verenigingen.verenigingen.doctype.e_boekhouden_migration.e_boekhouden_migration.update_account_type_mapping`
   - Status: ❌ FUNCTION DOES NOT EXIST
   - Impact: Cannot update account type mappings

5. **`test_eboekhouden_connection`** (Line 1639)
   - Path: `vereiningen.api.test_eboekhouden_connection` (NOTE: typo "vereiningen")
   - Status: ❌ PATH TYPO + FILE DOES NOT EXIST
   - Impact: Connection test button fails

6. **`test_rest_mutation_fetch`** (Line 1727)
   - Path: `verenigingen.utils.test_rest_migration.test_rest_mutation_fetch`
   - Status: ❌ FILE DOES NOT EXIST
   - Impact: REST API mutation fetch test fails

### 🔄 FRAPPE FRAMEWORK CALLS (2 standard calls)

1. **`frappe.client.get`** (Line 1080) - Standard Frappe API
2. **`frappe.client.get_count`** (Lines 1204, 1503) - Standard Frappe API

## Key Findings

1. **SOAP vs REST Usage**:
   - Only ONE SOAP API call: `test_connection` for testing connectivity
   - All transaction imports use REST API methods
   - Migration has successfully transitioned to REST for data operations

2. **Critical Missing Functions**:
   - Account type management (3 functions)
   - Migration statistics display
   - Test/debug utilities

3. **UI Impact**:
   - 10 core functions work properly
   - 6 UI buttons/features will fail due to missing backend functions

4. **Typo Issue**:
   - Line 1639: `vereiningen` should be `verenigingen`

## Recommended Actions

1. **Phase 0 (Immediate)**:
   - Implement the 6 missing functions or remove their UI triggers
   - Fix the typo on line 1639

2. **Phase 1 (Cleanup)**:
   - Remove UI elements for non-existent functionality
   - OR implement the missing backend functions

3. **Documentation**:
   - Update comments about SOAP limitations (they're outdated)
   - Document which features are actually REST-based
