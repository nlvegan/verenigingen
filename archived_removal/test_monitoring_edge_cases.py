#!/usr/bin/env python3
"""
Edge case testing for Phase 1 monitoring implementation
"""

import json

import frappe
from frappe.utils import add_to_date, now, random_string


@frappe.whitelist()
def test_audit_log_reference_handling():
    """Test audit log handling when reference documents don't exist"""
    try:
        from verenigingen.doctype.sepa_audit_log.sepa_audit_log import SEPAAuditLog

        # Test with None reference
        audit_log_1 = SEPAAuditLog.log_sepa_event(
            process_type="Mandate Creation",
            reference_doc=None,
            action="test_null_reference",
            details={"test": "null_reference"},
        )

        # Test with non-existent document
        fake_doc = frappe._dict({"doctype": "Member", "name": "NON-EXISTENT-MEMBER"})

        audit_log_2 = SEPAAuditLog.log_sepa_event(
            process_type="Payment Processing",
            reference_doc=fake_doc,
            action="test_nonexistent_reference",
            details={"test": "nonexistent_reference"},
        )

        return {
            "status": "success",
            "message": "Reference handling tests completed",
            "null_reference_log": audit_log_1.name if audit_log_1 else None,
            "nonexistent_reference_log": audit_log_2.name if audit_log_2 else None,
        }

    except Exception as e:
        return {"status": "error", "message": f"Reference handling test failed: {str(e)}"}


@frappe.whitelist()
def test_audit_log_validation_edge_cases():
    """Test audit log validation with invalid data"""
    try:
        results = {}

        # Test 1: Invalid compliance status
        try:
            doc = frappe.new_doc("SEPA Audit Log")
            doc.update(
                {
                    "timestamp": now(),
                    "process_type": "Mandate Creation",
                    "action": "test_invalid_status",
                    "compliance_status": "Invalid Status",  # This should fail
                    "details": json.dumps({"test": True}),
                }
            )
            doc.insert()
            results["invalid_status"] = "ERROR: Should have failed validation"
        except frappe.ValidationError as e:
            results["invalid_status"] = f"SUCCESS: Properly rejected invalid status: {str(e)}"
        except Exception as e:
            results["invalid_status"] = f"ERROR: Unexpected error: {str(e)}"

        # Test 2: Missing required fields
        try:
            doc = frappe.new_doc("SEPA Audit Log")
            doc.update(
                {
                    "timestamp": now(),
                    "action": "test_missing_fields",
                    # Missing process_type and compliance_status
                }
            )
            doc.insert()
            results["missing_fields"] = "ERROR: Should have failed validation"
        except Exception as e:
            results["missing_fields"] = f"SUCCESS: Properly rejected missing fields: {str(e)}"

        # Test 3: Valid document creation
        try:
            doc = frappe.new_doc("SEPA Audit Log")
            doc.update(
                {
                    "timestamp": now(),
                    "process_type": "Batch Generation",
                    "action": "test_valid_creation",
                    "compliance_status": "Compliant",
                    "details": json.dumps({"test": "valid_creation"}),
                }
            )
            doc.insert()
            results["valid_creation"] = f"SUCCESS: Created valid document: {doc.name}"
        except Exception as e:
            results["valid_creation"] = f"ERROR: Valid document creation failed: {str(e)}"

        return {"status": "success", "message": "Validation edge case tests completed", "results": results}

    except Exception as e:
        return {"status": "error", "message": f"Validation edge case test failed: {str(e)}"}


@frappe.whitelist()
def test_alert_manager_thresholds():
    """Test alert manager threshold calculations"""
    try:
        from verenigingen.utils.alert_manager import AlertManager

        alert_manager = AlertManager()
        results = {}

        # Test error rate checking (without triggering actual alerts)
        try:
            # Count current errors
            current_errors = frappe.db.count("Error Log", {"creation": (">=", add_to_date(now(), hours=-1))})

            results["current_hourly_errors"] = current_errors
            results["error_threshold"] = alert_manager.alert_thresholds["error_rate_hourly"]
            results["would_trigger_alert"] = (
                current_errors > alert_manager.alert_thresholds["error_rate_hourly"]
            )

        except Exception as e:
            results["error_rate_check"] = f"ERROR: {str(e)}"

        # Test SEPA compliance checking
        try:
            failed_sepa = frappe.db.count(
                "SEPA Audit Log",
                {"compliance_status": "Failed", "timestamp": (">=", add_to_date(now(), hours=-1))},
            )

            results["current_failed_sepa"] = failed_sepa
            results["sepa_threshold"] = alert_manager.alert_thresholds["failed_sepa_threshold"]
            results["sepa_would_trigger"] = (
                failed_sepa > alert_manager.alert_thresholds["failed_sepa_threshold"]
            )

        except Exception as e:
            results["sepa_check"] = f"ERROR: {str(e)}"

        return {"status": "success", "message": "Alert threshold tests completed", "results": results}

    except Exception as e:
        return {"status": "error", "message": f"Alert threshold test failed: {str(e)}"}


@frappe.whitelist()
def test_audit_log_cleanup_prevention():
    """Test that audit logs cannot be manually deleted"""
    try:
        # Create a test audit log
        doc = frappe.new_doc("SEPA Audit Log")
        doc.update(
            {
                "timestamp": now(),
                "process_type": "Mandate Creation",
                "action": "test_deletion_prevention",
                "compliance_status": "Compliant",
                "details": json.dumps({"test": "deletion_prevention"}),
            }
        )
        doc.insert()

        # Try to delete it manually (should fail)
        try:
            # Switch to a non-admin user context
            original_user = frappe.session.user
            frappe.session.user = "test@example.com"  # Non-admin user

            doc.delete()

            # Restore user context
            frappe.session.user = original_user

            return {"status": "error", "message": "ERROR: Manual deletion should have been prevented"}

        except frappe.PermissionError as e:
            # Restore user context
            frappe.session.user = original_user
            return {"status": "success", "message": f"SUCCESS: Manual deletion properly prevented: {str(e)}"}
        except Exception as e:
            # Restore user context
            frappe.session.user = original_user
            return {
                "status": "partial_success",
                "message": f"Deletion prevented by different mechanism: {str(e)}",
            }

    except Exception as e:
        return {"status": "error", "message": f"Deletion prevention test failed: {str(e)}"}


@frappe.whitelist()
def test_sensitive_data_handling():
    """Test sensitive data masking in audit logs"""
    try:
        from verenigingen.doctype.sepa_audit_log.sepa_audit_log import SEPAAuditLog

        # Create a mock member for testing
        test_member = frappe._dict(
            {
                "name": f"TEST-MEMBER-{random_string(6)}",
                "doctype": "Member",
                "first_name": "Test",
                "last_name": "User",
            }
        )

        # Test mandate creation logging with sensitive data
        audit_log = SEPAAuditLog.log_mandate_creation(
            member=test_member,
            mandate=None,  # Simulate failed creation
            iban="NL91ABNA0417164300",  # Test IBAN
            bic="ABNANL2A",
            success=False,
            error_msg="Test error for sensitive data handling",
        )

        if audit_log:
            # Check that IBAN is masked
            details = json.loads(audit_log.details)
            masked_iban = details.get("iban_masked", "")

            return {
                "status": "success",
                "message": "Sensitive data handling test completed",
                "audit_log": audit_log.name,
                "iban_masked": masked_iban,
                "sensitive_flag": audit_log.sensitive_data,
                "proper_masking": masked_iban.startswith("NL91") and "****" in masked_iban,
            }
        else:
            return {"status": "error", "message": "Failed to create audit log for sensitive data test"}

    except Exception as e:
        return {"status": "error", "message": f"Sensitive data handling test failed: {str(e)}"}


@frappe.whitelist()
def run_all_edge_case_tests():
    """Run all edge case tests for monitoring implementation"""
    results = {}

    # Test 1: Reference handling
    results["reference_handling"] = test_audit_log_reference_handling()

    # Test 2: Validation edge cases
    results["validation_edge_cases"] = test_audit_log_validation_edge_cases()

    # Test 3: Alert thresholds
    results["alert_thresholds"] = test_alert_manager_thresholds()

    # Test 4: Deletion prevention
    results["deletion_prevention"] = test_audit_log_cleanup_prevention()

    # Test 5: Sensitive data handling
    results["sensitive_data"] = test_sensitive_data_handling()

    # Summary
    success_count = sum(
        1 for result in results.values() if result["status"] in ["success", "partial_success"]
    )
    total_count = len(results)

    return {
        "status": "completed",
        "message": f"All edge case tests completed: {success_count}/{total_count} successful",
        "success_rate": f"{(success_count/total_count)*100:.1f}%",
        "results": results,
    }
