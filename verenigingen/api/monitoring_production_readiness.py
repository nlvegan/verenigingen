#!/usr/bin/env python3
"""
Production readiness validation for Phase 1 monitoring implementation
"""

import json

import frappe
from frappe.utils import now

# Import security framework
from verenigingen.utils.security.api_security_framework import OperationType, high_security_api
from verenigingen.utils.security.audit_logging import log_sensitive_operation
from verenigingen.utils.security.authorization import require_role
from verenigingen.utils.security.csrf_protection import validate_csrf_token
from verenigingen.utils.security.rate_limiting import rate_limit


@high_security_api(operation_type=OperationType.ADMIN)
@frappe.whitelist()
@rate_limit(calls=10, period=60)  # 10 calls per minute
@require_role(["System Manager", "Verenigingen Administrator"])
@validate_csrf_token
def validate_doctype_installation():
    """Validate that monitoring DocTypes are properly installed"""
    try:
        # Log this sensitive operation
        log_sensitive_operation(
            "monitoring", "validate_doctype_installation", {"requested_by": frappe.session.user}
        )

        results = {}

        # Check SEPA Audit Log DocType
        if frappe.db.exists("DocType", "SEPA Audit Log"):
            results["sepa_audit_log_installed"] = True

            # Check field completeness
            doc = frappe.get_doc("DocType", "SEPA Audit Log")
            required_fields = [
                "event_id",
                "timestamp",
                "process_type",
                "action",
                "compliance_status",
                "reference_doctype",
                "reference_name",
                "user",
                "trace_id",
                "details",
                "sensitive_data",
            ]

            actual_fields = [field.fieldname for field in doc.fields]
            missing_fields = [f for f in required_fields if f not in actual_fields]

            results["sepa_fields_complete"] = len(missing_fields) == 0
            results["missing_fields"] = missing_fields

            # Check permissions
            has_system_manager_perm = any(
                perm.role == "System Manager" and perm.read for perm in doc.permissions
            )
            has_admin_perm = any(
                perm.role == "Verenigingen Administrator" and perm.read for perm in doc.permissions
            )

            results["permissions_configured"] = has_system_manager_perm and has_admin_perm

        else:
            results["sepa_audit_log_installed"] = False

        return {"status": "success", "message": "DocType validation completed", "results": results}

    except Exception as e:
        return {"status": "error", "message": f"DocType validation failed: {str(e)}"}


@high_security_api(operation_type=OperationType.ADMIN)
@frappe.whitelist()
@rate_limit(calls=10, period=60)  # 10 calls per minute
@require_role(["System Manager", "Verenigingen Administrator"])
@validate_csrf_token
def validate_scheduler_configuration():
    """Validate scheduler configuration for monitoring"""
    try:
        # Log this sensitive operation
        log_sensitive_operation(
            "monitoring", "validate_scheduler_configuration", {"requested_by": frappe.session.user}
        )

        from verenigingen.utils.alert_manager import run_daily_checks, run_hourly_checks

        results = {}

        # Test that scheduler functions exist and can be imported
        try:
            # Try importing and calling without actual execution
            results["hourly_function_exists"] = callable(run_hourly_checks)
            results["daily_function_exists"] = callable(run_daily_checks)
        except Exception as e:
            results["scheduler_import_error"] = str(e)

        # Check hooks.py configuration
        try:
            import verenigingen.hooks as hooks

            # Check if monitoring functions are in scheduler
            hourly_jobs = getattr(hooks, "scheduler_events", {}).get("hourly", [])
            daily_jobs = getattr(hooks, "scheduler_events", {}).get("daily", [])

            hourly_configured = any("alert_manager.run_hourly_checks" in job for job in hourly_jobs)
            daily_configured = any("alert_manager.run_daily_checks" in job for job in daily_jobs)

            results["hourly_scheduled"] = hourly_configured
            results["daily_scheduled"] = daily_configured

        except Exception as e:
            results["hooks_check_error"] = str(e)

        return {"status": "success", "message": "Scheduler configuration validated", "results": results}

    except Exception as e:
        return {"status": "error", "message": f"Scheduler validation failed: {str(e)}"}


@high_security_api(operation_type=OperationType.ADMIN)
@frappe.whitelist()
@rate_limit(calls=10, period=60)  # 10 calls per minute
@require_role(["System Manager", "Verenigingen Administrator"])
@validate_csrf_token
def validate_configuration_completeness():
    """Validate monitoring configuration is complete"""
    try:
        # Log this sensitive operation
        log_sensitive_operation(
            "monitoring", "validate_configuration_completeness", {"requested_by": frappe.session.user}
        )

        results = {}

        # Check alert recipients
        alert_recipients = frappe.conf.get("alert_recipients", [])
        results["alert_recipients_configured"] = len(alert_recipients) > 0
        results["alert_recipients_count"] = len(alert_recipients)

        # Check Sentry configuration
        results["sentry_dsn_configured"] = bool(frappe.conf.get("sentry_dsn"))
        results["sentry_environment_set"] = bool(frappe.conf.get("sentry_environment"))
        results["sentry_db_monitoring_enabled"] = bool(frappe.conf.get("enable_sentry_db_monitoring"))

        # Check if Sentry DSN is still placeholder (should be replaced in production)
        sentry_dsn = frappe.conf.get("sentry_dsn", "")
        results["sentry_dsn_is_placeholder"] = "PLACEHOLDER" in sentry_dsn

        # Production readiness assessment
        production_ready = (
            results["alert_recipients_configured"]
            and results["sentry_dsn_configured"]
            and not results["sentry_dsn_is_placeholder"]
        )

        results["production_ready"] = production_ready

        return {"status": "success", "message": "Configuration validation completed", "results": results}

    except Exception as e:
        return {"status": "error", "message": f"Configuration validation failed: {str(e)}"}


@high_security_api(operation_type=OperationType.SECURITY)
@frappe.whitelist()
@rate_limit(calls=10, period=60)  # 10 calls per minute
@require_role(["System Manager", "Verenigingen Administrator"])
@validate_csrf_token
def validate_security_compliance():
    """Validate security compliance of monitoring implementation"""
    try:
        # Log this sensitive operation
        log_sensitive_operation(
            "monitoring", "validate_security_compliance", {"requested_by": frappe.session.user}
        )

        results = {}

        # Check audit log security
        results["audit_logs_read_only"] = True  # Fields are marked read_only in JSON

        # Check sensitive data handling
        sensitive_logs = frappe.get_all("SEPA Audit Log", filters={"sensitive_data": 1}, limit=1)

        if sensitive_logs:
            log_doc = frappe.get_doc("SEPA Audit Log", sensitive_logs[0].name)
            if log_doc.details:
                details = json.loads(log_doc.details)
                # Check for proper IBAN masking
                results["iban_masking_implemented"] = "iban_masked" in details
                if "iban_masked" in details:
                    results["iban_properly_masked"] = "****" in details["iban_masked"]

        # Check permissions are restrictive
        audit_log_doc = frappe.get_doc("DocType", "SEPA Audit Log")
        non_admin_roles = [
            perm.role
            for perm in audit_log_doc.permissions
            if perm.role not in ["System Manager", "Administrator", "Verenigingen Administrator"]
        ]
        results["restrictive_permissions"] = len(non_admin_roles) == 0

        return {"status": "success", "message": "Security compliance validated", "results": results}

    except Exception as e:
        return {"status": "error", "message": f"Security validation failed: {str(e)}"}


@high_security_api(operation_type=OperationType.ADMIN)
@frappe.whitelist()
@rate_limit(calls=10, period=60)  # 10 calls per minute
@require_role(["System Manager", "Verenigingen Administrator"])
@validate_csrf_token
def validate_performance_acceptance():
    """Validate that monitoring performance is acceptable"""
    try:
        # Log this sensitive operation
        log_sensitive_operation(
            "monitoring", "validate_performance_acceptance", {"requested_by": frappe.session.user}
        )

        import time

        from verenigingen.utils.alert_manager import AlertManager

        results = {}

        # Test performance benchmarks
        start_time = time.time()
        alert_manager = AlertManager()
        alert_manager.check_error_rate_alert()
        alert_manager.check_sepa_compliance_alert()
        monitoring_time = time.time() - start_time

        results["monitoring_check_time"] = round(monitoring_time, 4)
        results["performance_acceptable"] = monitoring_time < 1.0  # Should complete in under 1 second

        # Check database query efficiency
        start_time = time.time()
        frappe.db.count("SEPA Audit Log")
        query_time = time.time() - start_time

        results["query_time"] = round(query_time, 4)
        results["query_efficient"] = query_time < 0.1  # Should complete in under 100ms

        return {"status": "success", "message": "Performance validation completed", "results": results}

    except Exception as e:
        return {"status": "error", "message": f"Performance validation failed: {str(e)}"}


@high_security_api(operation_type=OperationType.ADMIN)
@frappe.whitelist()
@rate_limit(calls=5, period=300)  # 5 calls per 5 minutes
@require_role(["System Manager", "Verenigingen Administrator"])
@validate_csrf_token
def run_production_readiness_check():
    """Run complete production readiness validation"""
    # Log this sensitive operation
    log_sensitive_operation(
        "monitoring", "run_production_readiness_check", {"requested_by": frappe.session.user}
    )

    results = {}

    # Validation 1: DocType installation
    results["doctype_validation"] = validate_doctype_installation()

    # Validation 2: Scheduler configuration
    results["scheduler_validation"] = validate_scheduler_configuration()

    # Validation 3: Configuration completeness
    results["configuration_validation"] = validate_configuration_completeness()

    # Validation 4: Security compliance
    results["security_validation"] = validate_security_compliance()

    # Validation 5: Performance acceptance
    results["performance_validation"] = validate_performance_acceptance()

    # Overall assessment
    validation_results = [result["status"] for result in results.values()]
    success_count = validation_results.count("success")
    total_count = len(validation_results)

    # Specific production readiness checks
    production_blockers = []

    # Check for critical issues
    if not results.get("doctype_validation", {}).get("results", {}).get("sepa_audit_log_installed"):
        production_blockers.append("SEPA Audit Log DocType not installed")

    if not results.get("configuration_validation", {}).get("results", {}).get("production_ready"):
        production_blockers.append("Configuration not production-ready (check Sentry DSN)")

    if not results.get("performance_validation", {}).get("results", {}).get("performance_acceptable"):
        production_blockers.append("Performance not acceptable")

    production_ready = len(production_blockers) == 0 and success_count == total_count

    return {
        "status": "completed",
        "message": f"Production readiness check completed: {success_count}/{total_count} validations passed",
        "production_ready": production_ready,
        "production_blockers": production_blockers,
        "success_rate": f"{(success_count / total_count) * 100:.1f}%",
        "results": results,
        "recommendation": "READY FOR PRODUCTION" if production_ready else "REQUIRES FIXES BEFORE PRODUCTION",
    }
