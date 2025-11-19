#!/usr/bin/env python3
"""
Remove debug/test API functions from eBoekhouden integration
Part of Phase 3: API Surface Reduction (77 → 20 endpoints)
"""

import os
import re
import shutil
from pathlib import Path

def remove_debug_functions_from_file(file_path, functions_to_remove):
    """Remove specified debug functions from a Python file"""
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return False
    
    # Create backup
    backup_path = f"{file_path}.backup"
    shutil.copy2(file_path, backup_path)
    
    with open(file_path, 'r') as f:
        content = f.read()
    
    original_content = content
    functions_removed = []
    
    for func_name in functions_to_remove:
        # Pattern to match the function from @frappe.whitelist() to the next function or EOF
        pattern = rf'@frappe\.whitelist\(\)\s*\ndef {re.escape(func_name)}\([^)]*\):.*?(?=\n@frappe\.whitelist\(\)|def \w+\(|\nclass \w+|\n# \w+|\Z)'
        matches = re.findall(pattern, content, re.DOTALL)
        
        if matches:
            content = re.sub(pattern, '', content, flags=re.DOTALL)
            functions_removed.append(func_name)
            print(f"  ✅ Removed {func_name}")
    
    if functions_removed:
        # Clean up multiple empty lines
        content = re.sub(r'\n\s*\n\s*\n', '\n\n', content)
        
        with open(file_path, 'w') as f:
            f.write(content)
        
        print(f"  📝 Updated {file_path} ({len(functions_removed)} functions removed)")
        return True
    else:
        # No changes made, remove backup
        os.remove(backup_path)
        return False

def main():
    """Main cleanup execution"""
    base_path = Path("/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/eboekhouden")
    
    # Define debug/test functions to remove by file
    cleanup_targets = {
        "eboekhouden_api.py": [
            "debug_settings",
            "test_session_token_only", 
            "discover_api_structure",
            "test_raw_request",
            "test_correct_endpoints",
            "test_chart_of_accounts_migration",
            "test_cost_center_migration",
            "debug_rest_relations_raw",
            "debug_rest_vs_soap_same_relations",
            "test_individual_relation_endpoint",
            "test_customer_migration",
            "test_supplier_migration", 
            "test_simple_migration",
            "create_test_migration",
            "test_dashboard_data",
            "debug_transaction_data",
            "test_ledger_id_mapping",
            "test_document_retrieval",
            "test_token_issue_debug",
            "test_mutation_zero",
            "test_iterator_starting_point",
            "debug_mutation_1319",
            "analyze_equity_mutations",
            "test_enhanced_memorial_logic",
            "analyze_memorial_bookings",
            "analyze_payment_mutations"
        ],
        "eboekhouden_account_analyzer.py": [
            "analyze_accounts_for_mapping"
        ],
        "eboekhouden_migration_config.py": [
            "test_payment_identification"
        ],
        "eboekhouden_enhanced_coa_import.py": [
            "test_iban_extraction",
            "test_enhanced_bank_detection"
        ],
        "eboekhouden_rest_full_migration.py": [
            "test_single_mutation_import",
            "debug_start_full_rest_import",
            "debug_payment_terms_issue", 
            "debug_specific_mutation_processing"
        ],
        "enhanced_payment_import.py": [
            "test_enhanced_payment_processing"
        ],
        "eboekhouden_transaction_type_mapper.py": [
            "test_transaction_type_detection"
        ],
        "check_settings.py": [
            "test_payment_without_settings"
        ],
        "eboekhouden_date_analyzer.py": [
            "analyze_date_distribution"
        ],
        "eboekhouden_rest_iterator.py": [
            "test_rest_iterator",
            "test_mutation_zero",
            "debug_rest_import_issues",
            "test_mutation_range",
            "analyze_migration_issues",
            "test_mutation_type_filtering",
            "test_mutation_pagination_and_filtering",
            "test_optimized_import_approach"
        ],
        "eboekhouden_rest_client.py": [
            "test_rest_mutations"
        ],
        "eboekhouden_payment_naming.py": [
            "analyze_payment_classification"
        ],
        "eboekhouden_smart_account_typing.py": [
            "test_account_type_detection"
        ],
        "cleanup_utils.py": [
            "debug_gl_entries_comprehensive_analysis",
            "debug_gl_entries_analysis", 
            "debug_nuclear_gl_cleanup",
            "debug_test_gl_deletion",
            "debug_cleanup_remaining_gl_entries",
            "debug_cleanup_all_imported_data"
        ]
    }
    
    total_functions_removed = 0
    files_modified = 0
    
    print("🧹 Starting eBoekhouden API cleanup...")
    print("=" * 60)
    
    for filename, functions in cleanup_targets.items():
        file_path = base_path / filename
        print(f"\n📁 Processing {filename}...")
        
        if remove_debug_functions_from_file(str(file_path), functions):
            files_modified += 1
            total_functions_removed += len(functions)
    
    print("\n" + "=" * 60)
    print(f"✅ Cleanup complete!")
    print(f"📊 Files modified: {files_modified}")
    print(f"🔧 Functions removed: {total_functions_removed}")
    print(f"📈 API reduction: ~{total_functions_removed} debug/test endpoints eliminated")
    
    # Note about what to keep
    print("\n🔒 Production APIs preserved:")
    print("  • preview_chart_of_accounts (used in JavaScript)")
    print("  • test_api_connection (used in JavaScript)")
    print("  • Import manager APIs (clean_import_all, get_import_status)")
    print("  • Core migration APIs (full_rest_migration_all_mutations)")
    print("  • Account management APIs")
    
    print(f"\n💾 Backups created with .backup extension")

if __name__ == "__main__":
    main()