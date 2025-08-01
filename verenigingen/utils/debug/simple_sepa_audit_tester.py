#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SEPA Audit Log Testing Utilities
Provides tools for testing and validating SEPA audit log functionality.
"""

import json

import frappe


@frappe.whitelist()
def test_sepa_audit_creation(process_type=None, action=None, test_details=None):
    """Test SEPA audit log creation with configurable parameters

    Args:
        process_type: Type of SEPA process (default: "Mandate Creation")
        action: Action being audited (default: "test_action")
        test_details: Dictionary of test details (default: {"test": True})
    """
    try:
        # Set defaults
        if not process_type:
            process_type = "Mandate Creation"
        if not action:
            action = "test_action"
        if not test_details:
            test_details = {"test": True, "timestamp": frappe.utils.now()}

        # Create a test audit log entry
        doc = frappe.new_doc("SEPA Audit Log")
        doc.update(
            {
                "event_id": frappe.generate_hash(length=12),
                "timestamp": frappe.utils.now(),
                "process_type": process_type,
                "action": action,
                "compliance_status": "Compliant",
                "details": json.dumps(test_details),
                "sensitive_data": False,
            }
        )

        # Insert the document
        doc.insert(ignore_permissions=True)

        return {
            "status": "success",
            "message": f"SEPA audit log created: {doc.name}",
            "event_id": doc.event_id,
            "process_type": process_type,
            "action": action,
        }

    except Exception as e:
        return {"status": "error", "message": f"Failed to create audit log: {str(e)}"}


@frappe.whitelist()
def check_sepa_audit_table():
    """Check if SEPA Audit Log table exists and get its structure"""
    try:
        tables = frappe.db.sql("SHOW TABLES LIKE 'tabSEPA Audit Log'", as_list=True)

        if tables:
            # Get table structure
            structure = frappe.db.sql("DESCRIBE `tabSEPA Audit Log`", as_dict=True)

            # Get recent entries count
            recent_count = frappe.db.count(
                "SEPA Audit Log", {"creation": [">", frappe.utils.add_days(frappe.utils.today(), -7)]}
            )
            total_count = frappe.db.count("SEPA Audit Log")

            return {
                "status": "success",
                "table_exists": True,
                "structure": structure,
                "total_entries": total_count,
                "recent_entries_7_days": recent_count,
            }
        else:
            return {
                "status": "error",
                "table_exists": False,
                "message": "SEPA Audit Log table does not exist",
            }

    except Exception as e:
        return {"status": "error", "message": f"Error checking table: {str(e)}"}


@frappe.whitelist()
def validate_sepa_audit_functionality():
    """Run comprehensive validation of SEPA audit log functionality"""
    results = {"timestamp": frappe.utils.now(), "tests": {}}

    # Test 1: Check table existence
    table_check = check_sepa_audit_table()
    results["tests"]["table_check"] = table_check

    if not table_check.get("table_exists"):
        results["overall_status"] = "failed"
        results["message"] = "SEPA Audit Log table does not exist"
        return results

    # Test 2: Test audit log creation
    creation_test = test_sepa_audit_creation(
        process_type="System Test",
        action="validation_test",
        test_details={"validation": True, "test_id": frappe.generate_hash(length=8)},
    )
    results["tests"]["creation_test"] = creation_test

    # Test 3: Test different process types
    process_types = ["Mandate Creation", "Payment Processing", "Batch Export", "Error Handling"]
    for process_type in process_types:
        test_result = test_sepa_audit_creation(
            process_type=process_type,
            action=f"test_{process_type.lower().replace(' ', '_')}",
            test_details={"process_type_test": True},
        )
        results["tests"][f"process_type_{process_type.lower().replace(' ', '_')}"] = test_result

    # Determine overall status
    failed_tests = [k for k, v in results["tests"].items() if v.get("status") != "success"]
    if failed_tests:
        results["overall_status"] = "partial_success"
        results["message"] = f"Some tests failed: {failed_tests}"
    else:
        results["overall_status"] = "success"
        results["message"] = "All SEPA audit log tests passed"

    return results


# Legacy function name for backward compatibility
@frappe.whitelist()
def simple_audit_test():
    """Legacy function - use test_sepa_audit_creation instead"""
    return test_sepa_audit_creation()


@frappe.whitelist()
def check_table_exists():
    """Legacy function - use check_sepa_audit_table instead"""
    return check_sepa_audit_table()
