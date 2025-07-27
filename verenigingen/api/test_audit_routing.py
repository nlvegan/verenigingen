"""
API endpoint to test audit logging routing between SEPA and API audit tables
"""

import frappe
from frappe import _

from verenigingen.utils.security.audit_logging import get_audit_logger


@frappe.whitelist()
def test_audit_routing():
    """Test that events are routed to the correct audit tables"""
    if not frappe.has_permission("System Manager"):
        frappe.throw(_("Only System Managers can run audit tests"), frappe.PermissionError)

    results = {"success": True, "tests": [], "summary": {}}

    try:
        logger = get_audit_logger()

        # Test SEPA events (should go to SEPA Audit Log)
        sepa_events = [
            ("mandate_creation", "info", {"test": "sepa_mandate_test"}),
            ("sepa_batch_created", "info", {"batch_id": "TEST_BATCH_001"}),
            ("batch_generation", "warning", {"warning": "test_warning"}),
            ("payment_processing", "error", {"error": "test_error"}),
        ]

        sepa_event_ids = []
        for event_type, severity, details in sepa_events:
            try:
                event_id = logger.log_event(event_type, severity, details=details)
                sepa_event_ids.append(event_id)
                results["tests"].append(
                    {"test": f"SEPA Event: {event_type}", "status": "PASS", "event_id": event_id}
                )
            except Exception as e:
                results["tests"].append(
                    {"test": f"SEPA Event: {event_type}", "status": "FAIL", "error": str(e)}
                )
                results["success"] = False

        # Test API events (should go to API Audit Log)
        api_events = [
            ("api_call_success", "info", {"endpoint": "/api/test", "method": "GET"}),
            ("csrf_validation_failed", "warning", {"csrf_token": "invalid"}),
            ("rate_limit_exceeded", "error", {"limit": 100, "attempts": 150}),
            ("unauthorized_access_attempt", "critical", {"resource": "/admin/config"}),
        ]

        api_event_ids = []
        for event_type, severity, details in api_events:
            try:
                event_id = logger.log_event(event_type, severity, details=details)
                api_event_ids.append(event_id)
                results["tests"].append(
                    {"test": f"API Event: {event_type}", "status": "PASS", "event_id": event_id}
                )
            except Exception as e:
                results["tests"].append(
                    {"test": f"API Event: {event_type}", "status": "FAIL", "error": str(e)}
                )
                results["success"] = False

        # Verify events were stored in correct tables
        sepa_count = frappe.db.count("SEPA Audit Log", {"event_id": ["in", sepa_event_ids]})
        api_count = frappe.db.count("API Audit Log", {"event_id": ["in", api_event_ids]})

        # Verify no cross-contamination
        sepa_in_api = frappe.db.count("API Audit Log", {"event_id": ["in", sepa_event_ids]})
        api_in_sepa = frappe.db.count("SEPA Audit Log", {"event_id": ["in", api_event_ids]})

        results["tests"].append(
            {
                "test": "SEPA Events in Correct Table",
                "status": "PASS" if sepa_count == len(sepa_event_ids) else "FAIL",
                "details": f"{sepa_count}/{len(sepa_event_ids)} events in SEPA Audit Log",
            }
        )

        results["tests"].append(
            {
                "test": "API Events in Correct Table",
                "status": "PASS" if api_count == len(api_event_ids) else "FAIL",
                "details": f"{api_count}/{len(api_event_ids)} events in API Audit Log",
            }
        )

        results["tests"].append(
            {
                "test": "No Cross-Contamination",
                "status": "PASS" if sepa_in_api == 0 and api_in_sepa == 0 else "FAIL",
                "details": f"{sepa_in_api} SEPA events in API table, {api_in_sepa} API events in SEPA table",
            }
        )

        # Test search functionality
        try:
            sepa_search_results = logger.search_audit_logs(
                event_types=["mandate_creation", "sepa_batch_created"], limit=10
            )
            api_search_results = logger.search_audit_logs(
                event_types=["api_call_success", "csrf_validation_failed"], limit=10
            )
            all_search_results = logger.search_audit_logs(limit=20)

            results["tests"].append(
                {
                    "test": "Search Functionality",
                    "status": "PASS",
                    "details": f"SEPA: {len(sepa_search_results)}, API: {len(api_search_results)}, All: {len(all_search_results)}",
                }
            )
        except Exception as e:
            results["tests"].append({"test": "Search Functionality", "status": "FAIL", "error": str(e)})
            results["success"] = False

        # Cleanup test events
        cleanup_count = 0
        for event_id in sepa_event_ids + api_event_ids:
            try:
                # Try to delete from SEPA Audit Log
                if frappe.db.exists("SEPA Audit Log", {"event_id": event_id}):
                    doc_name = frappe.db.get_value("SEPA Audit Log", {"event_id": event_id}, "name")
                    frappe.delete_doc("SEPA Audit Log", doc_name, ignore_permissions=True)
                    cleanup_count += 1

                # Try to delete from API Audit Log
                if frappe.db.exists("API Audit Log", {"event_id": event_id}):
                    doc_name = frappe.db.get_value("API Audit Log", {"event_id": event_id}, "name")
                    frappe.delete_doc("API Audit Log", doc_name, ignore_permissions=True)
                    cleanup_count += 1

            except Exception as e:
                frappe.log_error(f"Failed to cleanup test event {event_id}: {str(e)}", "Audit Test Cleanup")

        frappe.db.commit()

        # Summary
        total_tests = len(results["tests"])
        passed_tests = len([t for t in results["tests"] if t["status"] == "PASS"])

        results["summary"] = {
            "total_tests": total_tests,
            "passed_tests": passed_tests,
            "success_rate": f"{(passed_tests/total_tests)*100:.1f}%",
            "sepa_events_created": len(sepa_event_ids),
            "api_events_created": len(api_event_ids),
            "events_cleaned_up": cleanup_count,
            "cross_contamination": sepa_in_api + api_in_sepa == 0,
        }

        if passed_tests != total_tests:
            results["success"] = False

    except Exception as e:
        results["success"] = False
        results["error"] = str(e)
        frappe.log_error(f"Audit routing test failed: {str(e)}", "Audit Test Error")

    return results


@frappe.whitelist()
def test_field_mapping():
    """Test that field mappings work correctly for both tables"""
    if not frappe.has_permission("System Manager"):
        frappe.throw(_("Only System Managers can run audit tests"), frappe.PermissionError)

    results = {"success": True, "tests": []}

    try:
        logger = get_audit_logger()

        # Test SEPA field mapping
        try:
            event_id = logger.log_event(
                "mandate_creation", "warning", details={"test_field": "test_value"}, sensitive_data=True
            )

            # Retrieve and check fields
            sepa_doc = frappe.get_doc("SEPA Audit Log", {"event_id": event_id})

            sepa_test = {
                "test": "SEPA Field Mapping",
                "status": "PASS",
                "fields": {
                    "event_id": sepa_doc.event_id,
                    "process_type": sepa_doc.process_type,
                    "action": sepa_doc.action,
                    "compliance_status": sepa_doc.compliance_status,
                    "sensitive_data": sepa_doc.sensitive_data,
                },
            }

            # Validate mappings
            if sepa_doc.process_type != "Mandate Creation":
                sepa_test["status"] = "FAIL"
                sepa_test[
                    "error"
                ] = f"Expected process_type 'Mandate Creation', got '{sepa_doc.process_type}'"
            elif sepa_doc.compliance_status != "Exception":
                sepa_test["status"] = "FAIL"
                sepa_test[
                    "error"
                ] = f"Expected compliance_status 'Exception', got '{sepa_doc.compliance_status}'"

            results["tests"].append(sepa_test)

            # Cleanup
            frappe.delete_doc("SEPA Audit Log", sepa_doc.name, ignore_permissions=True)

        except Exception as e:
            results["tests"].append({"test": "SEPA Field Mapping", "status": "FAIL", "error": str(e)})
            results["success"] = False

        # Test API field mapping
        try:
            event_id = logger.log_event(
                "api_call_success",
                "info",
                details={"endpoint": "/api/test", "response_time": 150},
                sensitive_data=False,
            )

            # Retrieve and check fields
            api_doc = frappe.get_doc("API Audit Log", {"event_id": event_id})

            api_test = {
                "test": "API Field Mapping",
                "status": "PASS",
                "fields": {
                    "event_id": api_doc.event_id,
                    "event_type": api_doc.event_type,
                    "severity": api_doc.severity,
                    "user": api_doc.user,
                    "sensitive_data": api_doc.sensitive_data,
                },
            }

            # Validate mappings
            if api_doc.event_type != "api_call_success":
                api_test["status"] = "FAIL"
                api_test["error"] = f"Expected event_type 'api_call_success', got '{api_doc.event_type}'"
            elif api_doc.severity != "info":
                api_test["status"] = "FAIL"
                api_test["error"] = f"Expected severity 'info', got '{api_doc.severity}'"

            results["tests"].append(api_test)

            # Cleanup
            frappe.delete_doc("API Audit Log", api_doc.name, ignore_permissions=True)

        except Exception as e:
            results["tests"].append({"test": "API Field Mapping", "status": "FAIL", "error": str(e)})
            results["success"] = False

        frappe.db.commit()

    except Exception as e:
        results["success"] = False
        results["error"] = str(e)
        frappe.log_error(f"Field mapping test failed: {str(e)}", "Audit Field Test Error")

    return results
