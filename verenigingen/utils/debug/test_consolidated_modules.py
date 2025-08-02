#!/usr/bin/env python3
"""
Test consolidated E-Boekhouden modules
"""

import frappe


@frappe.whitelist()
def test_consolidated_modules():
    """Test the consolidated E-Boekhouden modules"""

    results = {"tests_passed": 0, "tests_failed": 0, "details": []}

    # Test 1: Party Manager
    try:
        from verenigingen.e_boekhouden.utils.consolidated import EBoekhoudenPartyManager

        manager = EBoekhoudenPartyManager()

        # Test simple customer creation
        customer = manager.get_or_create_customer_simple("test_relation_123")

        if customer:
            results["details"].append(f"Party Manager: Created customer {customer}")
            results["tests_passed"] += 1

            # Clean up
            if frappe.db.exists("Customer", customer):
                frappe.delete_doc("Customer", customer)
        else:
            results["details"].append("Party Manager: Failed to create customer")
            results["tests_failed"] += 1

    except Exception as e:
        results["details"].append(f"Party Manager test failed: {str(e)}")
        results["tests_failed"] += 1

    # Test 2: Account Manager
    try:
        from verenigingen.e_boekhouden.utils.consolidated import EBoekhoudenAccountManager

        company = frappe.get_single(
            "E-Boekhouden Settings"
        ).default_company or frappe.defaults.get_user_default("company")
        manager = EBoekhoudenAccountManager(company)

        # Test smart account type detection
        account_type, root_type = manager._get_smart_account_type_by_code("13000", "handelsdebiteuren")

        if account_type == "Receivable" and root_type == "Asset":
            results["details"].append(f"Account Manager: Smart typing works - {account_type}/{root_type}")
            results["tests_passed"] += 1
        else:
            results["details"].append(f"Account Manager: Smart typing failed - {account_type}/{root_type}")
            results["tests_failed"] += 1

    except Exception as e:
        results["details"].append(f"Account Manager test failed: {str(e)}")
        results["tests_failed"] += 1

    # Test 3: Migration Coordinator
    try:
        from verenigingen.e_boekhouden.utils.consolidated import EBoekhoudenMigrationCoordinator

        company = frappe.get_single(
            "E-Boekhouden Settings"
        ).default_company or frappe.defaults.get_user_default("company")
        coordinator = EBoekhoudenMigrationCoordinator(company)

        # Test prerequisites validation (without running full migration)
        config = {
            "migrate_accounts": False,  # Don't actually migrate
            "migrate_parties": False,
            "migrate_transactions": False,
        }

        prereq_results = coordinator.validate_prerequisites(config)

        if "checks" in prereq_results and len(prereq_results["checks"]) > 0:
            results["details"].append(
                f"Migration Coordinator: Prerequisites check completed with {len(prereq_results['checks'])} checks"
            )
            results["tests_passed"] += 1
        else:
            results["details"].append("Migration Coordinator: Prerequisites check failed")
            results["tests_failed"] += 1

    except Exception as e:
        results["details"].append(f"Migration Coordinator test failed: {str(e)}")
        results["tests_failed"] += 1

    # Test 4: Backward compatibility
    try:
        from verenigingen.e_boekhouden.utils.consolidated import get_or_create_customer_simple

        # Test backward compatibility wrapper
        customer = get_or_create_customer_simple("test_compat_456")

        if customer:
            results["details"].append(f"Backward Compatibility: Wrapper works - {customer}")
            results["tests_passed"] += 1

            # Clean up
            if frappe.db.exists("Customer", customer):
                frappe.delete_doc("Customer", customer)
        else:
            results["details"].append("Backward Compatibility: Wrapper failed")
            results["tests_failed"] += 1

    except Exception as e:
        results["details"].append(f"Backward Compatibility test failed: {str(e)}")
        results["tests_failed"] += 1

    results["summary"] = f"Passed: {results['tests_passed']}, Failed: {results['tests_failed']}"

    return results
