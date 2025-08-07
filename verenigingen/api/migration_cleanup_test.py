"""
eBoekhouden Migration Cleanup Testing API

Testing functions for validating the eBoekhouden migration system after cleanup.
"""

import frappe
from frappe import _


@frappe.whitelist()
def test_migration_system_integrity():
    """Test the integrity of the eBoekhouden migration system after cleanup"""

    results = {"success": True, "components_tested": [], "issues_found": [], "recommendations": []}

    try:
        # Test 1: Check Enhanced Migration class structure
        results["components_tested"].append("Enhanced Migration Class")
        from verenigingen.e_boekhouden.utils.eboekhouden_enhanced_migration import (
            EnhancedEBoekhoudenMigration,
        )

        # Test 2: Check API client
        results["components_tested"].append("API Client")
        from verenigingen.e_boekhouden.utils.eboekhouden_api import EBoekhoudenAPI

        # Test 3: Check core migration function
        results["components_tested"].append("Core Migration Function")
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import start_full_rest_import

        # Test 4: Check if settings exist and are configured
        results["components_tested"].append("Settings Configuration")
        settings = frappe.get_single("E-Boekhouden Settings")

        if not settings.api_url:
            results["issues_found"].append("E-Boekhouden Settings: API URL not configured")

        if not settings.get_password("api_token"):
            results["issues_found"].append("E-Boekhouden Settings: API token not configured")

        # Test 5: Check DocType structure after field removal
        results["components_tested"].append("DocType Structure")
        migration_meta = frappe.get_meta("E-Boekhouden Migration")

        # Verify the use_enhanced_migration field was removed
        enhanced_field = None
        for field in migration_meta.fields:
            if field.fieldname == "use_enhanced_migration":
                enhanced_field = field
                break

        if enhanced_field:
            results["issues_found"].append(
                "DocType still contains use_enhanced_migration field - removal incomplete"
            )
        else:
            results["recommendations"].append(
                "✓ use_enhanced_migration field successfully removed from DocType"
            )

        # Test 6: Verify whitelist functions are accessible
        results["components_tested"].append("Whitelist Functions")
        from verenigingen.e_boekhouden.utils.eboekhouden_enhanced_migration import (
            execute_enhanced_migration,
            run_migration_dry_run,
            validate_migration_data,
        )

        # Test 7: Check if SOAP references were properly removed
        results["components_tested"].append("SOAP Reference Cleanup")

        # Read the enhanced migration file to check for SOAP remnants
        enhanced_migration_path = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/e_boekhouden/utils/eboekhouden_enhanced_migration.py"
        try:
            with open(enhanced_migration_path, "r") as f:
                content = f.read()

            soap_references = []
            if "soap" in content.lower():
                lines = content.split("\n")
                for i, line in enumerate(lines):
                    if "soap" in line.lower():
                        soap_references.append(f"Line {i+1}: {line.strip()}")

            if soap_references:
                results["issues_found"].append(
                    f"Found {len(soap_references)} SOAP references still in enhanced migration"
                )
                results["soap_references"] = soap_references[:5]  # First 5 only
            else:
                results["recommendations"].append("✓ SOAP references successfully cleaned up")
        except Exception as e:
            results["issues_found"].append(f"Could not read enhanced migration file: {str(e)}")

        # Test 8: Check dependency imports
        results["components_tested"].append("Import Dependencies")
        try:
            from verenigingen.utils.migration.migration_audit_trail import (
                AuditedMigrationOperation,
                MigrationAuditTrail,
            )
            from verenigingen.utils.migration.migration_error_recovery import MigrationErrorRecovery

            results["recommendations"].append("✓ All enhancement dependencies successfully imported")
        except ImportError as e:
            results["issues_found"].append(f"Missing enhancement dependencies: {str(e)}")

    except Exception as e:
        results["success"] = False
        results["critical_error"] = str(e)

    return results


@frappe.whitelist()
def test_api_connectivity():
    """Test if API connectivity works after cleanup"""

    try:
        from verenigingen.e_boekhouden.utils.eboekhouden_api import test_api_connection

        return test_api_connection()

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_migration_dry_run():
    """Test dry run functionality after cleanup"""

    try:
        # Create a test migration document
        test_migration = frappe.new_doc("E-Boekhouden Migration")
        test_migration.update(
            {
                "migration_name": "Test Migration - Cleanup Validation",
                "company": frappe.defaults.get_defaults().get("company") or "Test Company",
                "migration_status": "Draft",
                "dry_run": 1,
                "date_from": "2024-01-01",
                "date_to": "2024-01-31",
                "migrate_accounts": 1,
                "migrate_transactions": 1,
                "batch_size": 10,
            }
        )

        # Don't save - just use for validation
        settings = frappe.get_single("E-Boekhouden Settings")

        from verenigingen.e_boekhouden.utils.eboekhouden_enhanced_migration import (
            EnhancedEBoekhoudenMigration,
        )

        enhanced_migration = EnhancedEBoekhoudenMigration(test_migration, settings)

        # Test initialization
        return {
            "success": True,
            "message": "Enhanced migration system initialized successfully",
            "dry_run_enabled": enhanced_migration.dry_run,
            "batch_size": enhanced_migration.batch_size,
            "company": enhanced_migration.company,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def comprehensive_cleanup_test():
    """Run comprehensive test of migration system after cleanup"""

    results = {"overall_success": True, "tests_run": [], "summary": {}}

    # Test 1: System Integrity
    integrity_result = test_migration_system_integrity()
    results["tests_run"].append(
        {"test_name": "System Integrity", "result": integrity_result, "passed": integrity_result["success"]}
    )

    # Test 2: API Connectivity
    api_result = test_api_connectivity()
    results["tests_run"].append(
        {"test_name": "API Connectivity", "result": api_result, "passed": api_result["success"]}
    )

    # Test 3: Dry Run
    dry_run_result = test_migration_dry_run()
    results["tests_run"].append(
        {"test_name": "Dry Run Functionality", "result": dry_run_result, "passed": dry_run_result["success"]}
    )

    # Calculate summary
    passed_tests = sum(1 for test in results["tests_run"] if test["passed"])
    total_tests = len(results["tests_run"])

    results["summary"] = {
        "tests_passed": passed_tests,
        "tests_total": total_tests,
        "success_rate": f"{(passed_tests/total_tests)*100:.1f}%",
        "ready_for_production": passed_tests == total_tests,
    }

    results["overall_success"] = passed_tests == total_tests

    return results
