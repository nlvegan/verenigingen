#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simple SEPA Audit Log test
"""

import json

import frappe


@frappe.whitelist()
def simple_audit_test():
    """Simple test to create a SEPA audit log entry"""
    try:
        # Create a simple audit log entry
        doc = frappe.new_doc("SEPA Audit Log")
        doc.update(
            {
                "event_id": frappe.generate_hash(length=12),
                "timestamp": frappe.utils.now(),
                "process_type": "Mandate Creation",
                "action": "test_action",
                "compliance_status": "Compliant",
                "details": json.dumps({"test": True}),
                "sensitive_data": False,
            }
        )

        # Insert the document
        doc.insert(ignore_permissions=True)

        return {
            "status": "success",
            "message": f"SEPA audit log created: {doc.name}",
            "event_id": doc.event_id,
        }

    except Exception as e:
        return {"status": "error", "message": f"Failed to create audit log: {str(e)}"}


@frappe.whitelist()
def check_table_exists():
    """Check if SEPA Audit Log table exists"""
    try:
        tables = frappe.db.sql("SHOW TABLES LIKE 'tabSEPA Audit Log'", as_list=True)

        if tables:
            # Get table structure
            structure = frappe.db.sql("DESCRIBE `tabSEPA Audit Log`", as_dict=True)
            return {"status": "success", "table_exists": True, "structure": structure}
        else:
            return {"status": "error", "table_exists": False, "message": "Table does not exist"}

    except Exception as e:
        return {"status": "error", "message": f"Error checking table: {str(e)}"}
