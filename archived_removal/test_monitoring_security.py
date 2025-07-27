#!/usr/bin/env python3
"""
Security testing for Phase 1 monitoring implementation
"""

import json

import frappe
from frappe.utils import add_to_date, now


@frappe.whitelist()
def test_audit_log_permissions():
    """Test SEPA Audit Log permissions and access control"""
    try:
        results = {}

        # Test 1: Check if ordinary users can access audit logs
        try:
            # Get count of audit logs as current user
            count = frappe.db.count("SEPA Audit Log")
            results["audit_log_count"] = count
            results["can_read_count"] = True
        except frappe.PermissionError:
            results["can_read_count"] = False
            results["audit_log_count"] = "Permission denied"
        except Exception as e:
            results["can_read_count"] = f"ERROR: {str(e)}"

        # Test 2: Check field-level security
        try:
            # Try to read one audit log if any exist
            audit_logs = frappe.get_all("SEPA Audit Log", limit=1)
            if audit_logs:
                log_doc = frappe.get_doc("SEPA Audit Log", audit_logs[0].name)
                # Check if sensitive data flag is accessible
                results["can_read_sensitive_flag"] = hasattr(log_doc, "sensitive_data")
                results["can_read_details"] = hasattr(log_doc, "details")
            else:
                results["no_audit_logs"] = "No audit logs to test"
        except frappe.PermissionError as e:
            results["field_access"] = f"Permission denied: {str(e)}"
        except Exception as e:
            results["field_access"] = f"ERROR: {str(e)}"

        # Test 3: Check if user can create audit logs directly
        try:
            doc = frappe.new_doc("SEPA Audit Log")
            doc.update(
                {
                    "event_id": frappe.generate_hash(length=12),
                    "timestamp": now(),
                    "process_type": "Mandate Creation",
                    "action": "test_direct_creation",
                    "compliance_status": "Compliant",
                }
            )
            doc.insert()
            results["can_create_directly"] = True
            results["created_doc"] = doc.name
        except frappe.PermissionError:
            results["can_create_directly"] = False
        except Exception as e:
            results["direct_creation_error"] = str(e)

        return {
            "status": "success",
            "message": "Audit log permission tests completed",
            "current_user": frappe.session.user,
            "user_roles": frappe.get_roles(),
            "results": results,
        }

    except Exception as e:
        return {"status": "error", "message": f"Permission test failed: {str(e)}"}


@frappe.whitelist()
def test_alert_manager_security():
    """Test Alert Manager security features"""
    try:
        from verenigingen.utils.alert_manager import AlertManager

        results = {}

        # Test 1: Check if alert manager can be instantiated
        try:
            alert_manager = AlertManager()
            results["can_instantiate"] = True
            results["alert_thresholds"] = alert_manager.alert_thresholds
        except Exception as e:
            results["instantiation_error"] = str(e)

        # Test 2: Test error rate checking without triggering alerts
        try:
            alert_manager = AlertManager()

            # Check current error count (this should be safe)
            error_count = frappe.db.count("Error Log", {"creation": (">=", add_to_date(now(), hours=-1))})

            results["current_errors"] = error_count
            results["error_check_safe"] = True

        except Exception as e:
            results["error_check_error"] = str(e)

        # Test 3: Test SEPA compliance check without triggering alerts
        try:
            alert_manager = AlertManager()

            # This should be safe to check
            failed_sepa = frappe.db.count(
                "SEPA Audit Log",
                {"compliance_status": "Failed", "timestamp": (">=", add_to_date(now(), hours=-1))},
            )

            results["current_failed_sepa"] = failed_sepa
            results["sepa_check_safe"] = True

        except Exception as e:
            results["sepa_check_error"] = str(e)

        return {"status": "success", "message": "Alert Manager security tests completed", "results": results}

    except Exception as e:
        return {"status": "error", "message": f"Alert Manager security test failed: {str(e)}"}


@frappe.whitelist()
def test_sensitive_data_protection():
    """Test that sensitive data is properly protected in audit logs"""
    try:
        # Look for audit logs with sensitive data
        sensitive_logs = frappe.get_all(
            "SEPA Audit Log",
            filters={"sensitive_data": 1},
            fields=["name", "action", "timestamp", "compliance_status"],
            limit=5,
        )

        results = {"sensitive_logs_count": len(sensitive_logs), "can_access_metadata": True}

        # Test access to sensitive log details
        if sensitive_logs:
            try:
                log_doc = frappe.get_doc("SEPA Audit Log", sensitive_logs[0].name)

                # Check if details field contains masked data
                if log_doc.details:
                    details = json.loads(log_doc.details)

                    # Check for proper IBAN masking
                    if "iban_masked" in details:
                        iban_masked = details["iban_masked"]
                        results["iban_properly_masked"] = "****" in iban_masked
                        results["iban_sample"] = iban_masked

                    # Check that full IBAN is not exposed
                    details_str = str(details)
                    full_iban_exposed = any(
                        iban_pattern in details_str
                        for iban_pattern in ["NL91ABNA0417164300", "ABNA0417164300"]
                    )
                    results["full_iban_exposed"] = full_iban_exposed

                results["can_read_sensitive_details"] = True

            except frappe.PermissionError:
                results["can_read_sensitive_details"] = False
            except Exception as e:
                results["sensitive_access_error"] = str(e)

        return {
            "status": "success",
            "message": "Sensitive data protection test completed",
            "results": results,
        }

    except Exception as e:
        return {"status": "error", "message": f"Sensitive data protection test failed: {str(e)}"}


@frappe.whitelist()
def test_configuration_security():
    """Test monitoring configuration security"""
    try:
        results = {}

        # Test 1: Check alert recipients configuration
        try:
            alert_recipients = frappe.conf.get("alert_recipients", [])
            results["alert_recipients_configured"] = len(alert_recipients) > 0
            results["alert_recipients_count"] = len(alert_recipients)
            # Don't expose actual email addresses in test results
            results["has_admin_recipient"] = any("admin" in recipient for recipient in alert_recipients)
        except Exception as e:
            results["alert_config_error"] = str(e)

        # Test 2: Check Sentry configuration (without exposing keys)
        try:
            sentry_configured = bool(frappe.conf.get("sentry_dsn"))
            results["sentry_configured"] = sentry_configured
            results["sentry_db_monitoring"] = bool(frappe.conf.get("enable_sentry_db_monitoring"))
            results["sentry_environment"] = frappe.conf.get("sentry_environment", "unknown")
        except Exception as e:
            results["sentry_config_error"] = str(e)

        # Test 3: Check if monitoring configuration is secure
        try:
            # Ensure Sentry DSN is not a placeholder in production
            sentry_dsn = frappe.conf.get("sentry_dsn", "")
            results["sentry_dsn_is_placeholder"] = "PLACEHOLDER" in sentry_dsn
            results["environment_properly_set"] = frappe.conf.get("sentry_environment") in [
                "development",
                "staging",
                "production",
            ]
        except Exception as e:
            results["config_security_error"] = str(e)

        return {"status": "success", "message": "Configuration security test completed", "results": results}

    except Exception as e:
        return {"status": "error", "message": f"Configuration security test failed: {str(e)}"}


@frappe.whitelist()
def run_all_security_tests():
    """Run all security tests for monitoring implementation"""
    results = {}

    # Test 1: Audit log permissions
    results["audit_log_permissions"] = test_audit_log_permissions()

    # Test 2: Alert Manager security
    results["alert_manager_security"] = test_alert_manager_security()

    # Test 3: Sensitive data protection
    results["sensitive_data_protection"] = test_sensitive_data_protection()

    # Test 4: Configuration security
    results["configuration_security"] = test_configuration_security()

    # Summary
    success_count = sum(1 for result in results.values() if result["status"] == "success")
    total_count = len(results)

    return {
        "status": "completed",
        "message": f"All security tests completed: {success_count}/{total_count} successful",
        "success_rate": f"{(success_count/total_count)*100:.1f}%",
        "results": results,
    }
