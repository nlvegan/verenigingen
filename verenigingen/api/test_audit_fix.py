"""
Test API functions to verify audit logging fix
"""

import frappe

from verenigingen.utils.security.api_security_framework import OperationType, standard_api


@standard_api(operation_type=OperationType.UTILITY)
@frappe.whitelist()
def test_member_form_audit():
    """
    Test that Member form API calls don't create inappropriate audit entries
    """
    try:
        # Get a test member
        test_member = frappe.db.get_value("Member", {"status": "Active"}, ["name", "full_name"], as_dict=True)

        if not test_member:
            return {"success": False, "message": "No active members found for testing"}

        # Count audit entries before
        audit_count_before = frappe.db.count("API Audit Log")

        # Simulate common Member form API calls
        from verenigingen.api.suspension_api import can_suspend_member, get_suspension_status
        from verenigingen.verenigingen.doctype.member.member import check_donor_exists

        # These calls should not create audit entries with the new fix
        can_suspend_member(test_member.name)
        get_suspension_status(test_member.name)
        check_donor_exists(test_member.name)

        # Check audit entries after
        audit_count_after = frappe.db.count("API Audit Log")
        audit_entries_created = audit_count_after - audit_count_before

        return {
            "success": True,
            "message": f"Test completed for member {test_member.full_name}",
            "audit_entries_before": audit_count_before,
            "audit_entries_after": audit_count_after,
            "audit_entries_created": audit_entries_created,
            "fix_working": audit_entries_created == 0,
        }

    except Exception as e:
        frappe.log_error(f"Error in test_member_form_audit: {str(e)}", "Audit Fix Test")
        return {"success": False, "error": str(e)}


@standard_api(operation_type=OperationType.UTILITY)
@frappe.whitelist()
def test_audit_immutability():
    """
    Test that API Audit Log immutability works correctly
    """
    try:
        # Create a test audit entry
        audit_doc = frappe.new_doc("API Audit Log")
        audit_doc.event_type = "api_call_success"
        audit_doc.severity = "info"
        audit_doc.user = frappe.session.user
        audit_doc.insert(ignore_permissions=True)
        frappe.db.commit()

        audit_name = audit_doc.name

        # Test that we can't update it through normal means
        try:
            audit_doc.reload()
            audit_doc.severity = "warning"
            audit_doc.save()

            # If we get here, the immutability check failed
            frappe.delete_doc("API Audit Log", audit_name, ignore_permissions=True)
            frappe.db.commit()

            return {"success": False, "message": "Immutability check failed - was able to update audit entry"}

        except frappe.ValidationError as e:
            if "cannot be modified after creation" in str(e):
                # Cleanup
                frappe.delete_doc("API Audit Log", audit_name, ignore_permissions=True)
                frappe.db.commit()

                return {"success": True, "message": "Immutability check works correctly"}
            else:
                # Cleanup
                frappe.delete_doc("API Audit Log", audit_name, ignore_permissions=True)
                frappe.db.commit()

                return {"success": False, "message": f"Unexpected validation error: {str(e)}"}

    except Exception as e:
        frappe.log_error(f"Error in test_audit_immutability: {str(e)}", "Audit Fix Test")
        return {"success": False, "error": str(e)}


@standard_api(operation_type=OperationType.UTILITY)
@frappe.whitelist()
def run_audit_fix_tests():
    """
    Run all audit fix tests and return combined results
    """
    results = {"member_form_test": test_member_form_audit(), "immutability_test": test_audit_immutability()}

    # Summary
    all_passed = all(result.get("success", False) for result in results.values())

    results["summary"] = {
        "all_tests_passed": all_passed,
        "message": "All audit fix tests passed!" if all_passed else "Some audit fix tests failed",
    }

    return results
