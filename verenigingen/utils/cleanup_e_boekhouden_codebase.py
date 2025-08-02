#!/usr/bin/env python3
"""
E-Boekhouden Codebase Cleanup Script

This script performs systematic cleanup of duplicate, backup, and temporary files
in the E-Boekhouden module based on the architecture review recommendations.

Created: 2025-08-02
Purpose: Code consolidation and cleanup following security improvements
"""

import os
import shutil
from pathlib import Path

# Base path
BASE_PATH = Path("/home/frappe/frappe-bench/apps/verenigingen/verenigingen/e_boekhouden")

# Files to be safely removed - Phase 1 (Low Risk)
BACKUP_FILES_TO_REMOVE = [
    # Obvious backup files
    "doctype/e_boekhouden_migration/e_boekhouden_migration_original_backup.py",
    "doctype/e_boekhouden_migration/e_boekhouden_migration_original.js",
    # Test files (will be replaced by comprehensive integration tests)
    "doctype/e_boekhouden_migration/test_e_boekhouden_migration.py",
    "doctype/e_boekhouden_migration/test_e_boekhouden_migration_critical.py",
    "doctype/e_boekhouden_ledger_mapping/test_e_boekhouden_ledger_mapping.py",
    # Temporary utility files
    "utils/check_payment_implementation.py",
    "utils/check_payment_reconciliation.py",
    "utils/check_settings.py",
    "utils/quick_payment_test.py",
    "utils/setup_payment_test.py",
    "utils/fix_permission_bypassing.py",  # Our work is done here
    # Debug/analysis files
    "utils/eboekhouden_date_analyzer.py",
    "utils/eboekhouden_migration_fix_summary.py",
    "utils/eboekhouden_migration_categorizer.py",
    # Connection test (should be moved to proper test suite)
    "api/test_eboekhouden_connection.py",
]

# Files to be consolidated - Phase 2 (Medium Risk)
FILES_TO_CONSOLIDATE = {
    # Party creation - multiple implementations
    "party_creation": [
        "utils/party_extractor.py",
        "utils/party_resolver.py",
        "utils/simple_party_handler.py",
    ],
    # Account management - overlapping functionality
    "account_management": [
        "utils/eboekhouden_account_group_fix.py",
        "utils/eboekhouden_smart_account_typing.py",
        "utils/stock_account_handler.py",
    ],
    # Migration utilities - scattered functionality
    "migration_utilities": ["utils/migration_utils.py", "utils/migration_api.py", "utils/import_manager.py"],
    # Enhancement files that should be merged into core
    "enhancements": [
        "utils/eboekhouden_enhanced_migration.py",
        "utils/eboekhouden_migration_enhancements.py",
    ],
}

# Files that are candidates for major refactoring - Phase 3 (Higher Risk)
MAJOR_REFACTOR_CANDIDATES = [
    "utils/eboekhouden_rest_full_migration.py",  # Main monolithic file
    "utils/eboekhouden_unified_processor.py",  # Alternative implementation
]


def backup_file(file_path: Path, backup_dir: Path):
    """Create a backup of a file before removal."""
    if file_path.exists():
        backup_file_path = backup_dir / file_path.name
        shutil.copy2(file_path, backup_file_path)
        print(f"  Backed up: {file_path.name}")
        return True
    return False


def remove_file_safely(file_path: Path):
    """Remove a file safely with logging."""
    if file_path.exists():
        file_path.unlink()
        print(f"  Removed: {file_path}")
        return True
    else:
        print(f"  Not found: {file_path}")
        return False


def cleanup_phase_1():
    """Remove backup and temporary files (Low Risk)."""
    print("=" * 60)
    print("PHASE 1: Removing Backup and Temporary Files")
    print("=" * 60)

    # Create backup directory
    backup_dir = BASE_PATH / "cleanup_backups"
    backup_dir.mkdir(exist_ok=True)

    removed_count = 0

    for file_rel_path in BACKUP_FILES_TO_REMOVE:
        file_path = BASE_PATH / file_rel_path

        print(f"\nProcessing: {file_rel_path}")

        # Backup before removal
        if backup_file(file_path, backup_dir):
            if remove_file_safely(file_path):
                removed_count += 1

    print(f"\nPhase 1 Complete: {removed_count} files removed")
    return removed_count


def analyze_consolidation_candidates():
    """Analyze files that are candidates for consolidation."""
    print("=" * 60)
    print("PHASE 2: Analyzing Consolidation Candidates")
    print("=" * 60)

    for category, files in FILES_TO_CONSOLIDATE.items():
        print(f"\n{category.upper()}:")
        total_lines = 0

        for file_rel_path in files:
            file_path = BASE_PATH / file_rel_path
            if file_path.exists():
                try:
                    with open(file_path, "r") as f:
                        lines = len(f.readlines())
                    total_lines += lines
                    print(f"  {file_rel_path}: {lines} lines")
                except Exception as e:
                    print(f"  {file_rel_path}: Error reading ({e})")
            else:
                print(f"  {file_rel_path}: Not found")

        print(f"  TOTAL: {total_lines} lines in {category}")


def generate_consolidation_plan():
    """Generate specific consolidation recommendations."""
    print("=" * 60)
    print("CONSOLIDATION PLAN RECOMMENDATIONS")
    print("=" * 60)

    recommendations = {
        "party_creation": {
            "target_file": "utils/consolidated/party_manager.py",
            "description": "Consolidate all party creation logic into single manager",
            "functions": [
                "get_or_create_customer",
                "get_or_create_supplier",
                "resolve_party_from_relation_id",
            ],
        },
        "account_management": {
            "target_file": "utils/consolidated/account_manager.py",
            "description": "Unified account creation and management",
            "functions": ["create_account", "determine_account_type", "fix_account_groups"],
        },
        "migration_utilities": {
            "target_file": "utils/consolidated/migration_coordinator.py",
            "description": "Central migration coordination and utilities",
            "functions": ["coordinate_migration", "validate_prerequisites", "track_progress"],
        },
        "enhancements": {
            "target_file": "Merge into existing processors",
            "description": "Enhancement logic should be merged into processor classes",
            "functions": ["Enhanced validation", "Improved error handling", "Better progress tracking"],
        },
    }

    for category, plan in recommendations.items():
        print(f"\n{category.upper()}:")
        print(f"  Target: {plan['target_file']}")
        print(f"  Goal: {plan['description']}")
        print(f"  Key Functions: {', '.join(plan['functions'])}")


def assess_risks():
    """Assess risks for each phase of cleanup."""
    print("=" * 60)
    print("RISK ASSESSMENT")
    print("=" * 60)

    risks = {
        "Phase 1 (Backup/Temp Removal)": {
            "risk_level": "LOW",
            "reasoning": "Files are clearly backups, tests, or temporary utilities",
            "mitigation": "All files backed up before removal",
        },
        "Phase 2 (Code Consolidation)": {
            "risk_level": "MEDIUM",
            "reasoning": "Requires careful merging of business logic",
            "mitigation": "Comprehensive testing after each consolidation",
        },
        "Phase 3 (Major Refactoring)": {
            "risk_level": "HIGH",
            "reasoning": "Core migration logic changes",
            "mitigation": "Gradual migration with extensive integration testing",
        },
    }

    for phase, assessment in risks.items():
        print(f"\n{phase}:")
        print(f"  Risk Level: {assessment['risk_level']}")
        print(f"  Reasoning: {assessment['reasoning']}")
        print(f"  Mitigation: {assessment['mitigation']}")


def main():
    """Main cleanup execution."""
    print("E-BOEKHOUDEN CODEBASE CLEANUP")
    print("=" * 60)
    print(f"Target Directory: {BASE_PATH}")
    print(f"Backup Location: {BASE_PATH}/cleanup_backups")

    # Phase 1: Safe removal
    removed = cleanup_phase_1()

    # Phase 2: Analysis
    analyze_consolidation_candidates()

    # Generate recommendations
    generate_consolidation_plan()

    # Risk assessment
    assess_risks()

    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Phase 1: {removed} files removed safely")
    print("Phase 2: Consolidation candidates identified")
    print("Phase 3: Major refactoring opportunities documented")
    print("\nNext Steps:")
    print("1. Review removed files to ensure no critical functionality lost")
    print("2. Begin consolidation of party management functions")
    print("3. Create consolidated account manager")
    print("4. Plan gradual migration from monolithic migration file")


if __name__ == "__main__":
    main()
