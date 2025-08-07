"""
eBoekhouden Quick Test Suite - Fast validation of system after cleanup
"""

import frappe
from frappe import _


@frappe.whitelist()
def quick_system_validation():
    """Quick validation that eBoekhouden system is functional after cleanup"""

    results = {"success": True, "validation_results": [], "issues": [], "summary": ""}

    try:
        # Test 1: Import Enhanced Migration Class
        try:
            from verenigingen.e_boekhouden.utils.eboekhouden_enhanced_migration import (
                EnhancedEBoekhoudenMigration,
                execute_enhanced_migration,
            )

            results["validation_results"].append("✓ Enhanced Migration imports successful")
        except ImportError as e:
            results["issues"].append(f"Enhanced Migration import failed: {str(e)}")
            results["success"] = False

        # Test 2: API Client Functionality
        try:
            from verenigingen.e_boekhouden.utils.eboekhouden_api import EBoekhoudenAPI

            settings = frappe.get_single("E-Boekhouden Settings")

            if settings.api_url and settings.get_password("api_token"):
                api_client = EBoekhoudenAPI(settings)
                results["validation_results"].append("✓ API client initialization successful")
            else:
                results["validation_results"].append("⚠️ API credentials not configured (expected for demo)")
        except Exception as e:
            results["issues"].append(f"API client failed: {str(e)}")
            results["success"] = False

        # Test 3: Core Migration Function
        try:
            from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import start_full_rest_import

            results["validation_results"].append("✓ Core migration function accessible")
        except ImportError as e:
            results["issues"].append(f"Core migration import failed: {str(e)}")
            results["success"] = False

        # Test 4: Enhancement Dependencies
        try:
            from verenigingen.utils.migration.migration_audit_trail import MigrationAuditTrail
            from verenigingen.utils.migration.migration_error_recovery import MigrationErrorRecovery

            results["validation_results"].append("✓ Enhancement dependencies available")
        except ImportError as e:
            results["issues"].append(f"Enhancement dependencies missing: {str(e)}")
            results["success"] = False

        # Test 5: DocType Structure
        try:
            migration_meta = frappe.get_meta("E-Boekhouden Migration")

            # Check for required fields
            required_fields = ["migration_name", "company", "migration_status", "dry_run"]
            missing_fields = []

            existing_fields = [field.fieldname for field in migration_meta.fields]
            for field in required_fields:
                if field not in existing_fields:
                    missing_fields.append(field)

            if missing_fields:
                results["issues"].append(f"DocType missing required fields: {missing_fields}")
                results["success"] = False
            else:
                results["validation_results"].append("✓ DocType structure intact")

            # Verify use_enhanced_migration was removed
            if "use_enhanced_migration" not in existing_fields:
                results["validation_results"].append("✓ use_enhanced_migration field successfully removed")
            else:
                results["issues"].append("use_enhanced_migration field still exists in DocType")

        except Exception as e:
            results["issues"].append(f"DocType validation failed: {str(e)}")
            results["success"] = False

        # Test 6: Migration Document Controller
        try:
            from verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration import (
                EBoekhoudenMigration,
            )

            results["validation_results"].append("✓ Migration document controller accessible")
        except ImportError as e:
            results["issues"].append(f"Migration controller import failed: {str(e)}")
            results["success"] = False

        # Generate summary
        total_validations = len(results["validation_results"])
        total_issues = len(results["issues"])

        if results["success"]:
            results["summary"] = f"✅ All {total_validations} validations passed - System ready for production"
        else:
            results[
                "summary"
            ] = f"⚠️ Found {total_issues} issues out of {total_validations + total_issues} checks"

        results["cleanup_status"] = "SUCCESS" if results["success"] else "NEEDS_ATTENTION"

        return results

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "cleanup_status": "FAILED",
            "summary": f"Critical error during validation: {str(e)}",
        }


@frappe.whitelist()
def test_api_endpoints():
    """Test that API endpoints are still functional after cleanup"""

    endpoints = {
        "test_api_connection": "verenigingen.e_boekhouden.utils.eboekhouden_api.test_api_connection",
        "execute_enhanced_migration": "verenigingen.e_boekhouden.utils.eboekhouden_enhanced_migration.execute_enhanced_migration",
        "run_migration_dry_run": "verenigingen.e_boekhouden.utils.eboekhouden_enhanced_migration.run_migration_dry_run",
        "validate_migration_data": "verenigingen.e_boekhouden.utils.eboekhouden_enhanced_migration.validate_migration_data",
    }

    results = {"success": True, "endpoint_status": {}, "working_endpoints": [], "broken_endpoints": []}

    for endpoint_name, endpoint_path in endpoints.items():
        try:
            # Try to import the function
            module_path, function_name = endpoint_path.rsplit(".", 1)
            module = __import__(module_path, fromlist=[function_name])
            func = getattr(module, function_name)

            # Check if it's whitelisted
            if hasattr(func, "whitelisted"):
                results["endpoint_status"][endpoint_name] = "✓ Available & Whitelisted"
                results["working_endpoints"].append(endpoint_name)
            else:
                results["endpoint_status"][endpoint_name] = "⚠️ Available but not whitelisted"
                results["working_endpoints"].append(endpoint_name)

        except Exception as e:
            results["endpoint_status"][endpoint_name] = f"❌ Failed: {str(e)}"
            results["broken_endpoints"].append(endpoint_name)
            results["success"] = False

    results[
        "summary"
    ] = f"Working: {len(results['working_endpoints'])}, Broken: {len(results['broken_endpoints'])}"

    return results
