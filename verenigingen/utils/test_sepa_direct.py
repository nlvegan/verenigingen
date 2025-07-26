#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Direct test of SEPA Audit Log methods
"""

import frappe

from verenigingen.doctype.sepa_audit_log.sepa_audit_log import SEPAAuditLog


@frappe.whitelist()
def test_direct_sepa_logging():
    """Test SEPAAuditLog methods directly"""
    try:
        # Create a mock document for testing
        mock_doc = frappe._dict({"name": "TEST-DOC-001", "doctype": "Member"})

        # Test the log_sepa_event method
        result = SEPAAuditLog.log_sepa_event(
            process_type="Mandate Creation",
            reference_doc=None,  # Don't use reference for test
            action="test_mandate_creation",
            details={"test": True, "compliance_status": "Compliant", "sensitive_data": False},
        )

        if result:
            return {
                "status": "success",
                "message": f"SEPA event logged successfully: {result.name}",
                "event_id": result.event_id,
            }
        else:
            return {"status": "error", "message": "log_sepa_event returned None"}

    except Exception as e:
        return {"status": "error", "message": f"Direct test failed: {str(e)}"}


@frappe.whitelist()
def test_mandate_creation_method():
    """Test the log_mandate_creation method"""
    try:
        # Create mock member data
        mock_member = frappe._dict(
            {"name": "TEST-MEMBER-003", "doctype": "Member", "first_name": "Test", "last_name": "User"}
        )

        # Test successful mandate creation logging
        result = SEPAAuditLog.log_mandate_creation(
            member=mock_member,
            mandate=None,  # No actual mandate for test
            iban="NL91ABNA0417164300",
            bic="ABNANL2A",
            success=True,
            error_msg=None,
        )

        if result:
            return {
                "status": "success",
                "message": f"Mandate creation logged: {result.name}",
                "event_id": result.event_id,
            }
        else:
            return {"status": "error", "message": "log_mandate_creation returned None"}

    except Exception as e:
        return {"status": "error", "message": f"Mandate creation test failed: {str(e)}"}


@frappe.whitelist()
def get_all_audit_logs():
    """Get all SEPA audit logs for verification"""
    try:
        logs = frappe.get_all(
            "SEPA Audit Log",
            fields=[
                "name",
                "event_id",
                "process_type",
                "action",
                "compliance_status",
                "timestamp",
                "details",
            ],
            order_by="creation desc",
        )

        return {"status": "success", "count": len(logs), "logs": logs[:10]}  # Return latest 10

    except Exception as e:
        return {"status": "error", "message": f"Failed to get audit logs: {str(e)}"}
