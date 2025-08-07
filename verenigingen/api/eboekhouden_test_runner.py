"""
eBoekhouden Test Runner - Comprehensive Testing Suite

Test the eBoekhouden migration system functionality after cleanup.
"""

import frappe
from frappe import _


@frappe.whitelist()
def test_enhanced_migration_dry_run():
    """Test the enhanced migration dry run functionality"""

    try:
        # Create a temporary test migration for dry run
        test_migration_name = "TEST-CLEANUP-2025-001"

        # Check if test migration already exists and delete it
        if frappe.db.exists("E-Boekhouden Migration", test_migration_name):
            frappe.delete_doc("E-Boekhouden Migration", test_migration_name)
            frappe.db.commit()

        # Create new test migration
        test_migration = frappe.new_doc("E-Boekhouden Migration")
        test_migration.update(
            {
                "naming_series": "TEST-.YYYY.-",
                "migration_name": "Test Migration - Cleanup Validation",
                "company": "Ned Ver Vegan",  # Use the actual company from system
                "migration_status": "Draft",
                "dry_run": 1,
                "date_from": "2024-01-01",
                "date_to": "2024-01-31",
                "migrate_accounts": 1,
                "migrate_transactions": 1,
                "batch_size": 10,
                "skip_existing": 1,
            }
        )

        test_migration.insert()
        test_migration_name = test_migration.name  # Get auto-generated name
        frappe.db.commit()

        # Test the enhanced migration dry run
        from verenigingen.e_boekhouden.utils.eboekhouden_enhanced_migration import run_migration_dry_run

        dry_run_result = run_migration_dry_run(test_migration_name)

        # Clean up
        frappe.delete_doc("E-Boekhouden Migration", test_migration_name)
        frappe.db.commit()

        return {
            "success": True,
            "message": "Enhanced migration dry run test completed",
            "dry_run_result": dry_run_result,
            "test_migration_name": test_migration_name,
        }

    except Exception as e:
        # Clean up on error
        try:
            if frappe.db.exists("E-Boekhouden Migration", test_migration_name):
                frappe.delete_doc("E-Boekhouden Migration", test_migration_name)
                frappe.db.commit()
        except:
            pass

        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def test_migration_validation():
    """Test the enhanced migration validation functionality"""

    try:
        # Create a temporary test migration
        test_migration_name = "TEST-VALIDATION-2025-001"

        # Clean up if exists
        if frappe.db.exists("E-Boekhouden Migration", test_migration_name):
            frappe.delete_doc("E-Boekhouden Migration", test_migration_name)
            frappe.db.commit()

        # Create test migration
        test_migration = frappe.new_doc("E-Boekhouden Migration")
        test_migration.update(
            {
                "naming_series": "TEST-.YYYY.-",
                "migration_name": "Test Migration - Validation Check",
                "company": "Ned Ver Vegan",
                "migration_status": "Draft",
                "dry_run": 1,
                "date_from": "2024-01-01",
                "date_to": "2024-12-31",
                "migrate_accounts": 1,
                "migrate_customers": 1,
                "migrate_suppliers": 1,
                "migrate_transactions": 1,
                "batch_size": 100,
            }
        )

        test_migration.insert()
        test_migration_name = test_migration.name  # Get auto-generated name
        frappe.db.commit()

        # Test validation
        from verenigingen.e_boekhouden.utils.eboekhouden_enhanced_migration import validate_migration_data

        validation_result = validate_migration_data(test_migration_name)

        # Clean up
        frappe.delete_doc("E-Boekhouden Migration", test_migration_name)
        frappe.db.commit()

        return {
            "success": True,
            "message": "Migration validation test completed",
            "validation_result": validation_result,
            "test_migration_name": test_migration_name,
        }

    except Exception as e:
        # Clean up on error
        try:
            if frappe.db.exists("E-Boekhouden Migration", test_migration_name):
                frappe.delete_doc("E-Boekhouden Migration", test_migration_name)
                frappe.db.commit()
        except:
            pass

        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def comprehensive_eboekhouden_test():
    """Run comprehensive test suite for eBoekhouden system after cleanup"""

    results = {"overall_success": True, "tests_run": [], "system_status": "unknown"}

    # Test 1: API Connectivity
    try:
        from verenigingen.e_boekhouden.utils.eboekhouden_api import test_api_connection

        api_result = test_api_connection()

        results["tests_run"].append(
            {"test_name": "API Connectivity", "success": api_result["success"], "result": api_result}
        )
    except Exception as e:
        results["tests_run"].append({"test_name": "API Connectivity", "success": False, "error": str(e)})
        results["overall_success"] = False

    # Test 2: Enhanced Migration Initialization
    try:
        from verenigingen.api.migration_cleanup_test import test_migration_dry_run

        init_result = test_migration_dry_run()

        results["tests_run"].append(
            {
                "test_name": "Enhanced Migration Initialization",
                "success": init_result["success"],
                "result": init_result,
            }
        )
    except Exception as e:
        results["tests_run"].append(
            {"test_name": "Enhanced Migration Initialization", "success": False, "error": str(e)}
        )
        results["overall_success"] = False

    # Test 3: Dry Run Functionality
    try:
        dry_run_result = test_enhanced_migration_dry_run()

        results["tests_run"].append(
            {
                "test_name": "Dry Run Functionality",
                "success": dry_run_result["success"],
                "result": dry_run_result,
            }
        )

        if not dry_run_result["success"]:
            results["overall_success"] = False

    except Exception as e:
        results["tests_run"].append({"test_name": "Dry Run Functionality", "success": False, "error": str(e)})
        results["overall_success"] = False

    # Test 4: Migration Validation
    try:
        validation_result = test_migration_validation()

        results["tests_run"].append(
            {
                "test_name": "Migration Validation",
                "success": validation_result["success"],
                "result": validation_result,
            }
        )

        if not validation_result["success"]:
            results["overall_success"] = False

    except Exception as e:
        results["tests_run"].append({"test_name": "Migration Validation", "success": False, "error": str(e)})
        results["overall_success"] = False

    # Calculate summary
    passed_tests = sum(1 for test in results["tests_run"] if test["success"])
    total_tests = len(results["tests_run"])

    results["summary"] = {
        "tests_passed": passed_tests,
        "tests_total": total_tests,
        "success_rate": f"{(passed_tests/total_tests)*100:.1f}%",
        "production_ready": results["overall_success"],
    }

    if results["overall_success"]:
        results["system_status"] = "All tests passed - system ready for production"
    else:
        results["system_status"] = f"Issues found - {total_tests - passed_tests} tests failed"

    return results
