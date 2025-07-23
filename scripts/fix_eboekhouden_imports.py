#!/usr/bin/env python3
"""
Fix incorrect import paths for eboekhouden utilities.
All eboekhouden utility files are in verenigingen.utils.eboekhouden subdirectory,
but many imports are trying to import them directly from verenigingen.utils.
"""

import os
import re
import subprocess

# Mapping of incorrect imports to correct imports
IMPORT_FIXES = {
    'from verenigingen.utils.eboekhouden_api': 'from verenigingen.utils.eboekhouden.eboekhouden_api',
    'from verenigingen.utils.eboekhouden_account_group_fix': 'from verenigingen.utils.eboekhouden.eboekhouden_account_group_fix',
    'from verenigingen.utils.eboekhouden_cost_center_fix': 'from verenigingen.utils.eboekhouden.eboekhouden_cost_center_fix',
    'from verenigingen.utils.eboekhouden_enhanced_migration': 'from verenigingen.utils.eboekhouden.eboekhouden_enhanced_migration',
    'from verenigingen.utils.eboekhouden_migration_enhancements': 'from verenigingen.utils.eboekhouden.eboekhouden_migration_enhancements',
    'from verenigingen.utils.eboekhouden_coa_import': 'from verenigingen.utils.eboekhouden.eboekhouden_coa_import',
    'from verenigingen.utils.eboekhouden_rest_iterator': 'from verenigingen.utils.eboekhouden.eboekhouden_rest_iterator',
}

# Files to fix based on grep results
FILES_TO_FIX = [
    'scripts/api_maintenance/analyze_tegenrekening_usage.py',
    'verenigingen/patches/fix_eboekhouden_cost_center.py',
    'verenigingen/e_boekhouden/api.py',
    'verenigingen/utils/fetch_mutation_4595.py',
    'verenigingen/utils/recalculate_opening_balance.py',
    'verenigingen/utils/eboekhouden/eboekhouden_grouped_migration.py',
    'verenigingen/utils/eboekhouden/eboekhouden_api.py',
    'verenigingen/utils/eboekhouden/eboekhouden_migration_config.py',
    'verenigingen/api/chapter_dashboard_api.py',
    'verenigingen/utils/eboekhouden/eboekhouden_cost_center_fix.py',
    'verenigingen/utils/eboekhouden/eboekhouden_rest_full_migration.py',
    'verenigingen/utils/eboekhouden/invoice_helpers.py',
    'verenigingen/utils/eboekhouden/eboekhouden_account_group_fix.py',
    'verenigingen/utils/eboekhouden/eboekhouden_smart_account_typing.py',
    'verenigingen/utils/eboekhouden/migration/transaction_processor.py',
    'verenigingen/utils/fetch_mutation_6353.py',
    'verenigingen/utils/debug/check_opening_balance_import.py',
    'verenigingen/utils/debug/check_opening_balance_type.py',
    'verenigingen/utils/debug/test_memorial_specific.py',
    'verenigingen/utils/debug/fix_balancing_account.py',
    'verenigingen/utils/debug/test_mutation_1345_reimport.py',
    'verenigingen/utils/debug/debug_mutation_1345_direct.py',
    'verenigingen/utils/debug/check_mutation_1345_status.py',
    'verenigingen/utils/migration/stock_migration_fixed.py',
    'verenigingen/utils/migration/stock_migration.py',
    'verenigingen/utils/migration/test_enhanced_migration_api.py',
    'verenigingen/utils/fetch_mutation_6316.py',
    'verenigingen/verenigingen/doctype/e_boekhouden_dashboard/e_boekhouden_dashboard.py',
    'verenigingen/verenigingen/doctype/e_boekhouden_migration/e_boekhouden_migration.py',
    'verenigingen/verenigingen/doctype/e_boekhouden_migration/e_boekhouden_migration_original_backup.py',
    'verenigingen/www/e-boekhouden-dashboard.py',
]

def fix_imports_in_file(filepath):
    """Fix imports in a single file."""
    base_path = '/home/frappe/frappe-bench/apps/verenigingen/'
    full_path = os.path.join(base_path, filepath)
    
    if not os.path.exists(full_path):
        print(f"  ⚠️  File not found: {filepath}")
        return False
    
    try:
        with open(full_path, 'r') as f:
            content = f.read()
        
        original_content = content
        changes_made = False
        
        # Apply all import fixes
        for incorrect, correct in IMPORT_FIXES.items():
            if incorrect in content:
                content = content.replace(incorrect, correct)
                changes_made = True
                print(f"  ✓ Fixed: {incorrect} → {correct}")
        
        if changes_made:
            with open(full_path, 'w') as f:
                f.write(content)
            print(f"  ✓ Updated {filepath}")
            return True
        else:
            print(f"  • No changes needed in {filepath}")
            return False
            
    except Exception as e:
        print(f"  ✗ Error processing {filepath}: {str(e)}")
        return False

def main():
    """Main function to fix all imports."""
    print("Fixing e-boekhouden import paths...")
    print("=" * 60)
    
    total_files = len(FILES_TO_FIX)
    fixed_files = 0
    
    for filepath in FILES_TO_FIX:
        print(f"\nProcessing: {filepath}")
        if fix_imports_in_file(filepath):
            fixed_files += 1
    
    print("\n" + "=" * 60)
    print(f"Summary: Fixed {fixed_files} out of {total_files} files")
    
    # Also check for any remaining incorrect imports
    print("\nChecking for any remaining incorrect imports...")
    base_path = '/home/frappe/frappe-bench/apps/verenigingen/'
    
    for incorrect_import in IMPORT_FIXES.keys():
        pattern = incorrect_import.replace('from ', '')
        cmd = ['grep', '-r', pattern, base_path, '--include=*.py']
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.stdout:
                print(f"\n⚠️  Still found instances of '{pattern}':")
                lines = result.stdout.strip().split('\n')
                for line in lines[:5]:  # Show first 5 occurrences
                    print(f"  {line}")
                if len(lines) > 5:
                    print(f"  ... and {len(lines) - 5} more")
        except Exception as e:
            print(f"Error checking for pattern '{pattern}': {str(e)}")

if __name__ == "__main__":
    main()