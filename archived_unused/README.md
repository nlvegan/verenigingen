# Archived Unused Code

This directory contains code files that were moved as part of the eBoekhouden cleanup effort (July 2025).

## Directory Structure

### `/root_test_scripts/`
Root-level test scripts that are no longer needed:
- `console_test_quality.py` - Console test quality checker
- `test_enhanced_item_management.py` - Enhanced item management tests
- `test_no_fallback_accounts.py` - Fallback account tests
- `test_payment_console.py` - Payment console tests
- `test_payment_manually.py` - Manual payment tests

### `/debug_scripts/`
Debug and fix scripts that were one-off solutions:

#### `/debug_scripts/account_fixes/`
- Account-specific fix scripts (9999 account, balancing, company expenses, etc.)

#### `/debug_scripts/mutation_specific/`
- Scripts specific to mutation 1345 debugging and fixes

#### `/debug_scripts/memorial_fixes/`
- Memorial booking test and fix scripts

#### `/debug_scripts/payment_fixes/`
- Payment vs journal logic fixes and duplicate handling

#### `/debug_scripts/stock_fixes/`
- Stock account balancing and purchase invoice stock account fixes

#### `/debug_scripts/opening_balance_fixes/`
- Opening balance approach and logic fix scripts (moved earlier)

### `/one_off_scripts/`
Utility scripts that were created for specific one-time tasks:
- `fetch_mutation_*.py` - Scripts to fetch specific mutations
- `trigger_mutation_1345_reimport.py` - Specific mutation reimport
- `verify_mutation_1345_fix.py` - Mutation fix verification
- `create_2018_fiscal_year.py` - One-time fiscal year creation
- `create_verrekeningen_mapping_correct.py` - Verrekeningen mapping setup
- `setup_account_group_mappings.py` - Account group mapping setup
- `error_log_fix.py` - Error log fixes
- `implement_proper_opening_balance.py` - Opening balance implementation
- `revert_to_simple_opening_balance.py` - Opening balance reversion
- `update_mapping_for_verrekeningen.py` - Verrekeningen mapping updates
- eBoekhouden test scripts (test_single_mutation.py, test_migration_fix.py, etc.)

### `/api_backups/` (Pre-existing)
- Contains API backups from previous cleanup efforts

### `/expense-frontend/` (Pre-existing)
- Vue.js frontend application (archived)

### `/membership_amendment_request/` (Pre-existing)
- Archived membership amendment request doctype

## Valuable Debug Tools Kept

The following debug tools were **NOT** moved and remain active for ongoing troubleshooting:
- `analyze_payment_api.py` - Payment API analysis
- `analyze_payment_mutations.py` - Payment structure debugging
- `check_opening_balance_import.py` - Balance validation
- `check_memorial_import_logic.py` - Memorial debugging
- `check_ledger_mapping.py` - Ledger mapping validation
- Other check/analysis scripts in `verenigingen/utils/debug/`

## Restoration

If any of these files are needed in the future, they can be restored from this archive. However, most of these were one-off fixes or test scripts that are no longer relevant to the current codebase.

## Impact

This cleanup effort removed approximately 35+ orphaned debug files, 5 root directory test scripts, and 15+ one-off utility scripts, totaling around 55+ files moved to archive, achieving approximately 25% file count reduction in the debug/test categories as outlined in the eBoekhouden cleanup plan.
