#!/usr/bin/env python3
"""
Security Monitor Diagnostics

Provides diagnostic functions to analyze and troubleshoot security monitor initialization.
"""

import frappe
from frappe import _


@frappe.whitelist()
def diagnose_security_monitor_initialization():
    """Debug security monitor initialization issues"""
    try:
        debug_info = {"step_results": [], "final_result": None, "error_details": None}

        # Step 1: Try importing security monitoring
        try:
            from verenigingen.utils.security.security_monitoring import SecurityMonitor, get_security_monitor

            debug_info["step_results"].append({"step": "import_security_monitoring", "status": "SUCCESS"})
        except Exception as e:
            debug_info["step_results"].append(
                {"step": "import_security_monitoring", "status": "FAIL", "error": str(e)}
            )
            return debug_info

        # Step 2: Try importing dependencies
        try:
            from verenigingen.utils.security.audit_logging import get_audit_logger

            debug_info["step_results"].append({"step": "import_audit_logging", "status": "SUCCESS"})
        except Exception as e:
            debug_info["step_results"].append(
                {"step": "import_audit_logging", "status": "FAIL", "error": str(e)}
            )

        try:
            from verenigingen.utils.security.api_security_framework import get_security_framework

            debug_info["step_results"].append({"step": "import_security_framework", "status": "SUCCESS"})
        except Exception as e:
            debug_info["step_results"].append(
                {"step": "import_security_framework", "status": "FAIL", "error": str(e)}
            )

        # Step 3: Try initializing audit logger
        try:
            audit_logger = get_audit_logger()
            debug_info["step_results"].append(
                {"step": "initialize_audit_logger", "status": "SUCCESS", "type": str(type(audit_logger))}
            )
        except Exception as e:
            debug_info["step_results"].append(
                {"step": "initialize_audit_logger", "status": "FAIL", "error": str(e)}
            )

        # Step 4: Try initializing security framework
        try:
            security_framework = get_security_framework()
            debug_info["step_results"].append(
                {
                    "step": "initialize_security_framework",
                    "status": "SUCCESS",
                    "type": str(type(security_framework)),
                }
            )
        except Exception as e:
            debug_info["step_results"].append(
                {"step": "initialize_security_framework", "status": "FAIL", "error": str(e)}
            )

        # Step 5: Try creating SecurityMonitor directly
        try:
            monitor = SecurityMonitor()
            debug_info["step_results"].append(
                {"step": "create_security_monitor", "status": "SUCCESS", "type": str(type(monitor))}
            )
        except Exception as e:
            debug_info["step_results"].append(
                {"step": "create_security_monitor", "status": "FAIL", "error": str(e)}
            )
            return debug_info

        # Step 6: Try calling get_security_dashboard
        try:
            dashboard = monitor.get_security_dashboard()
            debug_info["step_results"].append(
                {
                    "step": "get_security_dashboard",
                    "status": "SUCCESS",
                    "has_current_metrics": dashboard.get("current_metrics") is not None,
                }
            )
        except Exception as e:
            debug_info["step_results"].append(
                {"step": "get_security_dashboard", "status": "FAIL", "error": str(e)}
            )

        # Step 7: Try using get_security_monitor function
        try:
            global_monitor = get_security_monitor()
            debug_info["step_results"].append(
                {
                    "step": "get_security_monitor_global",
                    "status": "SUCCESS",
                    "is_none": global_monitor is None,
                }
            )

            if global_monitor:
                global_dashboard = global_monitor.get_security_dashboard()
                debug_info["step_results"].append(
                    {
                        "step": "global_monitor_dashboard",
                        "status": "SUCCESS",
                        "has_current_metrics": global_dashboard.get("current_metrics") is not None,
                    }
                )
            else:
                debug_info["step_results"].append(
                    {"step": "global_monitor_dashboard", "status": "FAIL", "error": "Monitor is None"}
                )
        except Exception as e:
            debug_info["step_results"].append(
                {"step": "get_security_monitor_global", "status": "FAIL", "error": str(e)}
            )

        debug_info["final_result"] = "COMPLETED_ANALYSIS"
        return debug_info

    except Exception as e:
        return {
            "step_results": debug_info.get("step_results", []),
            "final_result": "ANALYSIS_FAILED",
            "error_details": str(e),
        }


@frappe.whitelist()
def test_security_monitor_basic_functionality():
    """Test basic security monitor functionality"""
    try:
        from verenigingen.utils.security.security_monitoring import get_security_monitor

        # Get monitor
        monitor = get_security_monitor()

        if monitor is None:
            return {
                "success": False,
                "error": "Security monitor is None",
                "debug": "get_security_monitor() returned None",
            }

        # Test basic functionality
        dashboard = monitor.get_security_dashboard()

        # Test recording an event
        from verenigingen.utils.security.security_monitoring import MonitoringMetric

        monitor.record_security_event(
            event_type=MonitoringMetric.AUTHENTICATION_FAILURES,
            user="test_user",
            endpoint="/api/test",
            details={"test": True},
            ip_address="127.0.0.1",
        )

        # Test metrics collection (call private method for testing)
        monitor._update_metrics_snapshot()

        # Get dashboard again
        updated_dashboard = monitor.get_security_dashboard()

        return {
            "success": True,
            "initial_dashboard": {
                "has_current_metrics": dashboard.get("current_metrics") is not None,
                "active_incidents_count": len(dashboard.get("active_incidents", [])),
                "recent_incidents_count": len(dashboard.get("recent_incidents", [])),
            },
            "updated_dashboard": {
                "has_current_metrics": updated_dashboard.get("current_metrics") is not None,
                "active_incidents_count": len(updated_dashboard.get("active_incidents", [])),
                "recent_incidents_count": len(updated_dashboard.get("recent_incidents", [])),
            },
        }

    except Exception as e:
        return {"success": False, "error": str(e), "debug": "Failed during basic functionality test"}


@frappe.whitelist()
def fix_security_monitor_initialization():
    """Attempt to fix security monitor initialization issues"""
    try:
        from verenigingen.utils.security.security_monitoring import setup_security_monitoring

        # Call setup function
        setup_security_monitoring()

        # Test if it works now
        test_result = test_security_monitor_basic_functionality()

        return {"success": True, "setup_completed": True, "basic_test_result": test_result}

    except Exception as e:
        return {"success": False, "error": str(e), "message": "Failed to fix security monitor initialization"}


if __name__ == "__main__":
    print("🔍 Debug Security Monitor API")
    print("Available functions:")
    print("- debug_security_monitor_initialization")
    print("- test_security_monitor_basic_functionality")
    print("- fix_security_monitor_initialization")
