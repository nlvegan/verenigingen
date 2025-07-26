#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script for SEPA Audit Log functionality
"""

import frappe

from verenigingen.doctype.sepa_audit_log.sepa_audit_log import SEPAAuditLog


@frappe.whitelist()
def test_sepa_audit_logging():
    """Test SEPA audit logging functionality"""
    try:
        # Create a test member document (don't save to DB)
        test_doc = frappe.new_doc("Member")
        test_doc.name = "TEST-MEMBER-001"
        test_doc.doctype = "Member"

        # Test the audit logging
        result = SEPAAuditLog.log_sepa_event(
            process_type="Mandate Creation",
            reference_doc=test_doc,
            action="test_action",
            details={"test": True, "compliance_status": "Compliant", "test_timestamp": frappe.utils.now()},
        )

        if result:
            return {
                "status": "success",
                "message": f"SEPA audit log created successfully: {result.name}",
                "audit_log_id": result.name,
            }
        else:
            return {"status": "error", "message": "Failed to create SEPA audit log"}

    except Exception as e:
        frappe.log_error(f"SEPA audit test failed: {str(e)}")
        return {"status": "error", "message": f"Test failed: {str(e)}"}


@frappe.whitelist()
def test_mandate_creation_logging():
    """Test mandate creation specific logging"""
    try:
        # Create test member data
        test_member = frappe._dict(
            {"name": "TEST-MEMBER-002", "doctype": "Member", "first_name": "Test", "last_name": "User"}
        )

        # Test mandate creation logging
        result = SEPAAuditLog.log_mandate_creation(
            member=test_member,
            mandate=None,  # No mandate created for test
            iban="NL91ABNA0417164300",
            bic="ABNANL2A",
            success=True,
            error_msg=None,
        )

        if result:
            return {
                "status": "success",
                "message": f"Mandate creation audit log created: {result.name}",
                "audit_log_id": result.name,
            }
        else:
            return {"status": "error", "message": "Failed to create mandate creation audit log"}

    except Exception as e:
        frappe.log_error(f"Mandate creation audit test failed: {str(e)}")
        return {"status": "error", "message": f"Test failed: {str(e)}"}


@frappe.whitelist()
def get_recent_audit_logs():
    """Get recent SEPA audit logs for verification"""
    try:
        logs = frappe.get_all(
            "SEPA Audit Log",
            fields=["name", "process_type", "action", "compliance_status", "timestamp"],
            order_by="creation desc",
            limit=10,
        )

        return {"status": "success", "count": len(logs), "logs": logs}

    except Exception as e:
        frappe.log_error(f"Failed to get recent audit logs: {str(e)}")
        return {"status": "error", "message": f"Failed to retrieve logs: {str(e)}"}
