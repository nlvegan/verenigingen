"""
API endpoint to test SEPA mandate field fixes
"""

import frappe

from verenigingen.utils.sepa_mandate_lifecycle_manager import SEPAMandateLifecycleManager


@frappe.whitelist()
def test_sepa_mandate_field_fixes():
    """Test that SEPA mandate lifecycle manager works with real database fields"""

    results = {"success": False, "message": "", "details": {}, "errors": []}

    try:
        # Find an existing SEPA mandate
        existing_mandates = frappe.get_all("SEPA Mandate", limit=1, fields=["name", "mandate_id"])

        if not existing_mandates:
            results["message"] = "No SEPA mandates found for testing"
            return results

        mandate_id = existing_mandates[0].mandate_id
        results["details"]["test_mandate_id"] = mandate_id

        # Test the _get_mandate_info method
        manager = SEPAMandateLifecycleManager()
        mandate_info = manager._get_mandate_info(mandate_id)

        if mandate_info:
            results["details"]["mandate_info_fields"] = list(mandate_info.keys())

            # Check for correct vs incorrect fields
            correct_fields = ["first_collection_date", "expiry_date", "mandate_type"]
            incorrect_fields = ["valid_from", "valid_until", "usage_count", "last_used_date"]

            results["details"]["correct_fields_found"] = []
            results["details"]["incorrect_fields_found"] = []

            for field in correct_fields:
                if field in mandate_info:
                    results["details"]["correct_fields_found"].append(field)

            for field in incorrect_fields:
                if field in mandate_info:
                    results["details"]["incorrect_fields_found"].append(field)

            # Test determine_sequence_type
            seq_result = manager.determine_sequence_type(mandate_id)
            results["details"]["sequence_type_test"] = {
                "is_valid": seq_result.is_valid,
                "usage_type": str(seq_result.usage_type),
                "warnings_count": len(seq_result.warnings),
                "errors_count": len(seq_result.errors),
                "errors": seq_result.errors,
            }

            if len(results["details"]["incorrect_fields_found"]) == 0:
                results["success"] = True
                results["message"] = "All field fixes verified successfully"
            else:
                results[
                    "message"
                ] = f"Found {len(results['details']['incorrect_fields_found'])} incorrect fields still present"
        else:
            results["message"] = "Could not retrieve mandate info"

    except Exception as e:
        results["errors"].append(str(e))
        results["message"] = f"Test failed: {str(e)}"

    return results
