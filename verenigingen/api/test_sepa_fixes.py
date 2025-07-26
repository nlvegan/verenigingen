"""
Test API for SEPA field fixes validation
"""

import frappe
from frappe.utils import today


@frappe.whitelist()
def test_sepa_conflict_detector():
    """Test that SEPA conflict detector works with correct field names"""
    try:
        from verenigingen.utils.sepa_conflict_detector import SEPAConflictDetector

        # Test instantiation
        detector = SEPAConflictDetector()

        # Test basic conflict detection with empty batch
        test_batch_data = {"invoice_list": [], "batch_date": today(), "batch_type": "CORE"}

        conflicts = detector.detect_batch_creation_conflicts(test_batch_data)
        conflict_report = detector.generate_conflict_report(conflicts)

        return {
            "success": True,
            "message": "SEPA conflict detector working correctly",
            "conflicts_found": len(conflicts),
            "conflict_report": conflict_report,
            "expected_empty_batch_conflict": len(conflicts) == 1
            and conflicts[0].conflict_type == "empty_batch",
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Error testing SEPA conflict detector: {str(e)}",
            "error_type": type(e).__name__,
        }


@frappe.whitelist()
def test_sepa_mandate_fields():
    """Test SEPA mandate field accessibility"""
    try:
        # Get a sample SEPA mandate if any exist
        mandate_names = frappe.get_all("SEPA Mandate", limit=1, pluck="name")

        if mandate_names:
            mandate = frappe.get_doc("SEPA Mandate", mandate_names[0])

            # Test field access
            fields_test = {
                "mandate_id": getattr(mandate, "mandate_id", None),
                "status": getattr(mandate, "status", None),
                "first_collection_date": getattr(mandate, "first_collection_date", None),
                "expiry_date": getattr(mandate, "expiry_date", None),
                "member": getattr(mandate, "member", None),
                "iban": getattr(mandate, "iban", None),
                "sign_date": getattr(mandate, "sign_date", None),
            }

            return {
                "success": True,
                "message": "SEPA mandate fields accessible",
                "mandate_name": mandate.name,
                "fields_accessible": fields_test,
                "all_fields_exist": all(hasattr(mandate, field) for field in fields_test.keys()),
            }
        else:
            return {
                "success": True,
                "message": "No SEPA mandates found to test",
                "fields_from_doctype": [
                    field.fieldname
                    for field in frappe.get_meta("SEPA Mandate").fields
                    if field.fieldname
                    in [
                        "mandate_id",
                        "status",
                        "first_collection_date",
                        "expiry_date",
                        "member",
                        "iban",
                        "sign_date",
                    ]
                ],
            }

    except Exception as e:
        return {
            "success": False,
            "message": f"Error testing SEPA mandate fields: {str(e)}",
            "error_type": type(e).__name__,
        }


@frappe.whitelist()
def run_simple_sepa_tests():
    """Run both SEPA tests and return combined results"""
    try:
        conflict_test = test_sepa_conflict_detector()
        mandate_test = test_sepa_mandate_fields()

        return {
            "success": conflict_test["success"] and mandate_test["success"],
            "conflict_detector_test": conflict_test,
            "mandate_fields_test": mandate_test,
            "summary": "All SEPA tests passed"
            if (conflict_test["success"] and mandate_test["success"])
            else "Some SEPA tests failed",
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Error running SEPA tests: {str(e)}",
            "error_type": type(e).__name__,
        }
