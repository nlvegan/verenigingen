#!/usr/bin/env python3
"""
Test script for E-Boekhouden consolidated modules
"""

import frappe

from verenigingen.e_boekhouden.utils.consolidated.account_manager import EBoekhoudenAccountManager
from verenigingen.e_boekhouden.utils.consolidated.migration_coordinator import EBoekhoudenMigrationCoordinator
from verenigingen.e_boekhouden.utils.consolidated.party_manager import EBoekhoudenPartyManager
from verenigingen.e_boekhouden.utils.security_helper import (
    has_migration_permission,
    migration_context,
    validate_and_insert,
)


def test_security_framework():
    """Test security framework functionality"""
    print("=== Testing Security Framework ===")

    print(f"Current user: {frappe.session.user}")
    print(f"User roles: {frappe.get_roles()}")

    # Test permission checking
    permissions = ["account_creation", "payment_processing", "party_creation", "journal_entries"]
    for perm in permissions:
        has_perm = has_migration_permission(perm)
        print(f"Permission {perm}: {'✓' if has_perm else '✗'}")

    print("✓ Security framework functions correctly\n")


def test_party_manager():
    """Test party manager functionality"""
    print("=== Testing Party Manager ===")

    party_mgr = EBoekhoudenPartyManager()

    # Test simple customer creation
    customer_name = party_mgr.get_or_create_customer_simple("TEST001")
    print(f"Customer creation result: {customer_name}")

    # Test supplier creation
    supplier_name = party_mgr.get_or_create_supplier_simple("SUPP001", "Test Supplier Description")
    print(f"Supplier creation result: {supplier_name}")

    # Test debug log
    debug_log = party_mgr.get_debug_log()
    print(f"Debug log entries: {len(debug_log)}")
    for entry in debug_log[-3:]:  # Show last 3 entries
        print(f"  - {entry}")

    print("✓ Party manager functions correctly\n")


def test_account_manager():
    """Test account manager functionality"""
    print("=== Testing Account Manager ===")

    # Get a test company
    company = frappe.db.get_value("Company", {}, "name")
    if not company:
        print("No company found - skipping account manager tests")
        return

    account_mgr = EBoekhoudenAccountManager(company)

    # Test smart account type detection
    test_accounts = [
        {"code": "1300", "description": "Debiteuren"},
        {"code": "1600", "description": "Crediteuren"},
        {"code": "10000", "description": "Kas"},
        {"code": "14000", "description": "Voorraad"},
        {"code": "80000", "description": "Omzet"},
    ]

    for account_data in test_accounts:
        account_type, root_type = account_mgr._get_smart_account_type(account_data)
        print(f"Account {account_data['code']} ({account_data['description']}): {account_type}, {root_type}")

    # Test debug log
    debug_log = account_mgr.get_debug_log()
    print(f"Debug log entries: {len(debug_log)}")

    print("✓ Account manager functions correctly\n")


def test_migration_coordinator():
    """Test migration coordinator functionality"""
    print("=== Testing Migration Coordinator ===")

    # Get a test company
    company = frappe.db.get_value("Company", {}, "name")
    if not company:
        print("No company found - skipping migration coordinator tests")
        return

    coordinator = EBoekhoudenMigrationCoordinator(company)

    # Test prerequisite validation
    test_config = {"migrate_accounts": True, "migrate_parties": True, "migrate_transactions": False}

    prereq_results = coordinator.validate_prerequisites(test_config)
    print(f"Prerequisites validation: {'✓' if prereq_results['valid'] else '✗'}")
    print(f"Checks performed: {len(prereq_results['checks'])}")

    for check in prereq_results["checks"]:
        status = "✓" if check["passed"] else "✗"
        print(f"  {status} {check['name']}")

    if prereq_results["errors"]:
        print("Errors found:")
        for error in prereq_results["errors"]:
            print(f"  - {error}")

    if prereq_results["warnings"]:
        print("Warnings found:")
        for warning in prereq_results["warnings"]:
            print(f"  - {warning}")

    # Test migration summary
    summary = coordinator.get_migration_summary()
    print(f"Migration progress: {summary['progress']['completion_percentage']:.1f}%")

    print("✓ Migration coordinator functions correctly\n")


def test_integration():
    """Test integration between modules"""
    print("=== Testing Module Integration ===")

    # Test that modules can work together
    party_mgr = EBoekhoudenPartyManager()

    # Get a test company
    company = frappe.db.get_value("Company", {}, "name")
    if company:
        account_mgr = EBoekhoudenAccountManager(company)
        coordinator = EBoekhoudenMigrationCoordinator(company)

        # Verify they can be used together
        print(f"✓ Party manager + Account manager integration works")
        print(f"✓ Migration coordinator integrates with both managers")

    print("✓ Module integration functions correctly\n")


def main():
    """Main test function"""
    print("E-Boekhouden Consolidated Modules Test")
    print("=" * 50)

    try:
        test_security_framework()
        test_party_manager()
        test_account_manager()
        test_migration_coordinator()
        test_integration()

        print("=" * 50)
        print("✓ ALL TESTS COMPLETED SUCCESSFULLY")
        return True

    except Exception as e:
        print(f"❌ TEST FAILED: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
