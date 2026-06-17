"""
Mollie Integration Monitoring API

Health check and performance monitoring endpoints for Mollie integration.
"""

import frappe
from frappe import _

from verenigingen.utils.security.api_security_framework import (
    OperationType,
    development_only_api,
    high_security_api,
    standard_api,
)

from ..utils.error_recovery import RetryConfig, error_recovery
from ..utils.logging import MollieLogger
from ..utils.monitoring import get_mollie_health_status, health_checker, performance_monitor


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_integration_health():
    """
    Get comprehensive health status of Mollie integration.

    Returns:
        Dict with health check results and performance metrics
    """
    try:
        logger = MollieLogger("health_api")
        logger.info("Health status requested")

        health_status = get_mollie_health_status()

        logger.success(
            "Health status retrieved",
            {
                "overall_status": health_status.get("health_check", {}).get("overall_status"),
                "total_checks": health_status.get("health_check", {}).get("summary", {}).get("total_checks"),
            },
        )

        return health_status

    except Exception as e:
        logger = MollieLogger("health_api")
        logger.error("Failed to get health status", error=e)
        frappe.throw(_("Failed to retrieve integration health status"))


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_performance_metrics():
    """
    Get performance metrics for Mollie operations.

    Query Parameters:
    - hours: Number of hours to look back (default: 24)

    Returns:
        Dict with performance metrics
    """
    try:
        logger = MollieLogger("performance_api")
        hours = int(frappe.form_dict.get("hours", 24))

        logger.info("Performance metrics requested", {"hours": hours})

        # Get overall performance metrics
        performance_summary = performance_monitor.get_overall_health(hours=hours)

        # Get specific operation stats
        key_operations = ["webhook_processing", "payment_creation", "subscription_creation", "api_call"]

        operation_stats = {}
        for operation in key_operations:
            stats = performance_monitor.get_operation_stats(operation, hours=hours)
            if stats["total_calls"] > 0:
                operation_stats[operation] = stats

        result = {"summary": performance_summary, "operations": operation_stats, "period_hours": hours}

        logger.success(
            "Performance metrics retrieved",
            {
                "total_operations": performance_summary.get("total_operations", 0),
                "operation_types": len(operation_stats),
            },
        )

        return result

    except Exception as e:
        logger = MollieLogger("performance_api")
        logger.error("Failed to get performance metrics", error=e)
        frappe.throw(_("Failed to retrieve performance metrics"))


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def run_health_check():
    """
    Manually trigger a comprehensive health check (development only).

    Returns:
        Dict with health check results
    """
    try:
        logger = MollieLogger("manual_health_check")
        logger.info("Manual health check triggered")

        health_report = health_checker.run_comprehensive_health_check()

        logger.success(
            "Manual health check completed",
            {
                "overall_status": health_report.get("overall_status"),
                "total_checks": health_report.get("summary", {}).get("total_checks"),
            },
        )

        return health_report

    except Exception as e:
        logger = MollieLogger("manual_health_check")
        logger.error("Manual health check failed", error=e)
        frappe.throw(_("Health check failed"))


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def clear_performance_data():
    """
    Clear accumulated performance data (development only).

    Returns:
        Dict with confirmation
    """
    try:
        logger = MollieLogger("performance_management")
        logger.info("Clearing performance data")

        # Clear performance metrics
        performance_monitor.metrics.clear()

        logger.success("Performance data cleared")

        return {"status": "success", "message": "Performance data cleared successfully"}

    except Exception as e:
        logger = MollieLogger("performance_management")
        logger.error("Failed to clear performance data", error=e)
        frappe.throw(_("Failed to clear performance data"))


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_service_status():
    """
    Get status of individual Mollie service components.

    Returns:
        Dict with service status information
    """
    try:
        logger = MollieLogger("service_status_api")
        logger.info("Service status requested")

        # Check service layer health
        service_results = health_checker.check_service_layer_health()

        # Check API connectivity
        api_result = health_checker.check_mollie_api_connectivity()

        # Check webhook endpoints
        webhook_results = health_checker.check_webhook_endpoints()

        # Organize results by category
        result = {
            "api_connectivity": {
                "service": api_result.service,
                "status": api_result.status,
                "latency": api_result.latency,
                "error": api_result.error_message,
                "details": api_result.details,
            },
            "service_layer": [
                {
                    "service": r.service,
                    "status": r.status,
                    "latency": r.latency,
                    "error": r.error_message,
                    "details": r.details,
                }
                for r in service_results
            ],
            "webhook_endpoints": [
                {
                    "service": r.service,
                    "status": r.status,
                    "latency": r.latency,
                    "error": r.error_message,
                    "details": r.details,
                }
                for r in webhook_results
            ],
        }

        # Calculate overall status
        all_results = [api_result] + service_results + webhook_results
        healthy_count = len([r for r in all_results if r.status == "healthy"])
        total_count = len(all_results)

        if healthy_count == total_count:
            overall_status = "healthy"
        elif healthy_count >= total_count * 0.8:
            overall_status = "degraded"
        else:
            overall_status = "unhealthy"

        result["overall_status"] = overall_status
        result["summary"] = {
            "total_services": total_count,
            "healthy": healthy_count,
            "unhealthy": total_count - healthy_count,
        }

        logger.success(
            "Service status retrieved",
            {"overall_status": overall_status, "total_services": total_count, "healthy": healthy_count},
        )

        return result

    except Exception as e:
        logger = MollieLogger("service_status_api")
        logger.error("Failed to get service status", error=e)
        frappe.throw(_("Failed to retrieve service status"))


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_error_recovery_status():
    """
    Get comprehensive error recovery status including circuit breakers and recovery queues.

    Returns:
        Dict with error recovery status and metrics
    """
    try:
        logger = MollieLogger("error_recovery_api")
        logger.info("Error recovery status requested")

        # Get error recovery status
        recovery_status = error_recovery.get_error_recovery_status()

        # Add performance metrics for error recovery
        recovery_metrics = _get_recovery_performance_metrics()

        result = {
            "timestamp": frappe.utils.now_datetime(),
            "circuit_breakers": recovery_status.get("circuit_breakers", {}),
            "recovery_queues": recovery_status.get("recovery_queues", {}),
            "performance_metrics": recovery_metrics,
            "system_health": _calculate_recovery_system_health(recovery_status, recovery_metrics),
        }

        logger.success(
            "Error recovery status retrieved",
            {
                "circuit_breaker_count": len(result["circuit_breakers"]),
                "recovery_queue_count": len(result["recovery_queues"]),
                "system_health": result["system_health"],
            },
        )

        return result

    except Exception as e:
        logger = MollieLogger("error_recovery_api")
        logger.error("Failed to get error recovery status", error=e)
        frappe.throw(_("Failed to retrieve error recovery status"))


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def reset_circuit_breakers():
    """
    Reset all circuit breakers (administrative function).

    This is a high-security operation that requires admin privileges.
    Use with caution as it can affect system stability.

    Returns:
        Dict with reset operation results
    """
    try:
        logger = MollieLogger("circuit_breaker_admin")
        logger.info("Circuit breaker reset requested by admin", {"user": frappe.session.user})

        # Get current circuit breaker states before reset
        current_states = error_recovery.get_error_recovery_status()["circuit_breakers"]

        # Reset all circuit breakers
        reset_count = 0
        for circuit_name in current_states.keys():
            if circuit_name in error_recovery.circuit_breakers:
                circuit_state = error_recovery.circuit_breakers[circuit_name]
                circuit_state.is_open = False
                circuit_state.failure_count = 0
                circuit_state.success_count = 0
                circuit_state.last_failure_time = None
                circuit_state.half_open_test_time = None
                reset_count += 1

        result = {
            "status": "success",
            "message": f"Reset {reset_count} circuit breakers successfully",
            "reset_circuits": list(current_states.keys()),
            "previous_states": current_states,
            "reset_by": frappe.session.user,
            "reset_at": frappe.utils.now_datetime(),
        }

        logger.warning(
            "Circuit breakers reset by admin",
            {
                "user": frappe.session.user,
                "reset_count": reset_count,
                "circuit_names": list(current_states.keys()),
            },
        )

        return result

    except Exception as e:
        logger = MollieLogger("circuit_breaker_admin")
        logger.error("Circuit breaker reset failed", error=e)
        frappe.throw(_("Failed to reset circuit breakers"))


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def process_recovery_queues():
    """
    Manually trigger processing of recovery queues (administrative function).

    Query Parameters:
    - queue_name: Specific queue to process (optional, processes all if not specified)
    - max_items: Maximum items to process per queue (default: 20)

    Returns:
        Dict with processing results for recovery workflows
    """
    try:
        logger = MollieLogger("recovery_queue_admin")
        queue_name = frappe.form_dict.get("queue_name")
        max_items = int(frappe.form_dict.get("max_items", 20))

        logger.info(
            "Recovery queue processing requested by admin",
            {"user": frappe.session.user, "queue_name": queue_name, "max_items": max_items},
        )

        all_results = {}

        if queue_name:
            # Process specific queue
            if queue_name in error_recovery.recovery_queues:
                results = error_recovery.process_recovery_queue(queue_name, max_items)
                all_results[queue_name] = results
            else:
                frappe.throw(_(f"Recovery queue '{queue_name}' not found"))
        else:
            # Process all queues
            queue_names = list(error_recovery.recovery_queues.keys())
            for name in queue_names:
                results = error_recovery.process_recovery_queue(name, max_items)
                all_results[name] = results

        result = {
            "status": "success",
            "message": "Recovery queues processed successfully",
            "results": all_results,
            "summary": {
                "total_processed": sum(r["processed"] for r in all_results.values()),
                "total_succeeded": sum(r["succeeded"] for r in all_results.values()),
                "total_failed": sum(r["failed"] for r in all_results.values()),
                "total_skipped": sum(r["skipped"] for r in all_results.values()),
            },
            "processed_by": frappe.session.user,
            "processed_at": frappe.utils.now_datetime(),
        }

        logger.success(
            "Recovery queues processed by admin",
            {
                "user": frappe.session.user,
                "queues_processed": len(all_results),
                "total_items": result["summary"]["total_processed"],
            },
        )

        return result

    except Exception as e:
        logger = MollieLogger("recovery_queue_admin")
        logger.error("Recovery queue processing failed", error=e)
        frappe.throw(_("Failed to process recovery queues"))


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def test_error_recovery():
    """
    Test endpoint for error recovery mechanisms (development only).

    This endpoint allows testing the error recovery system in a controlled way.

    Returns:
        Dict with test results
    """
    try:
        logger = MollieLogger("error_recovery_test")
        logger.info("Error recovery test requested")

        test_results = {"timestamp": frappe.utils.now_datetime(), "tests_run": [], "all_passed": True}

        # Test 1: Retry mechanism
        try:
            attempt_count = 0

            def failing_operation():
                nonlocal attempt_count
                attempt_count += 1
                if attempt_count < 3:
                    raise Exception("Simulated failure")
                return {"success": True, "attempts": attempt_count}

            result = error_recovery.execute_with_retry(
                failing_operation, "test_retry_operation", RetryConfig(max_attempts=3)
            )

            test_results["tests_run"].append(
                {"test": "retry_mechanism", "status": "passed", "result": result}
            )
        except Exception as e:
            test_results["tests_run"].append({"test": "retry_mechanism", "status": "failed", "error": str(e)})
            test_results["all_passed"] = False

        # Test 2: Circuit breaker
        try:

            def successful_operation():
                return {"success": True}

            result = error_recovery.execute_with_circuit_breaker(successful_operation, "test_circuit_breaker")

            test_results["tests_run"].append(
                {"test": "circuit_breaker", "status": "passed", "result": result}
            )
        except Exception as e:
            test_results["tests_run"].append({"test": "circuit_breaker", "status": "failed", "error": str(e)})
            test_results["all_passed"] = False

        # Test 3: Recovery workflow creation
        try:
            workflow_id = error_recovery.create_recovery_workflow(
                "test_workflow",
                {"operation_type": "test", "test_data": "sample_data", "error_details": {"simulated": True}},
                "manual_review",
            )

            test_results["tests_run"].append(
                {"test": "recovery_workflow", "status": "passed", "workflow_id": workflow_id}
            )
        except Exception as e:
            test_results["tests_run"].append(
                {"test": "recovery_workflow", "status": "failed", "error": str(e)}
            )
            test_results["all_passed"] = False

        logger.success(
            "Error recovery test completed",
            {"total_tests": len(test_results["tests_run"]), "all_passed": test_results["all_passed"]},
        )

        return test_results

    except Exception as e:
        logger = MollieLogger("error_recovery_test")
        logger.error("Error recovery test failed", error=e)
        return {"status": "error", "message": str(e)}


def _get_recovery_performance_metrics():
    """Get recovery performance metrics from cache."""
    try:
        recovery_metrics = {}

        # Get recovery success counts
        operations = ["webhook_processing", "payment_creation", "refund_creation"]

        for operation in operations:
            recovery_data = _read_recovery_counter(f"mollie_recovery_success:{operation}")
            failure_data = _read_recovery_counter(f"mollie_operation_failure:{operation}")

            recovery_metrics[operation] = {
                "recovery_success": recovery_data,
                "operation_failures": failure_data,
                "recovery_rate": (recovery_data["count"] / max(failure_data["count"], 1)) * 100,
            }

        return recovery_metrics
    except Exception:
        return {}


def _read_recovery_counter(cache_key):
    """Read a recovery counter dict from cache.

    The producers in error_recovery.py store these counters as JSON strings, and
    frappe.cache().get() returns them as bytes/str — so the raw value must be
    deserialised before use. Without this, the very presence of recovery activity
    (which writes JSON to the cache) made the metrics aggregation raise on
    ``data["count"]`` and silently return {}.
    """
    default = {"count": 0, "total_attempts": 0}
    raw = frappe.cache().get(cache_key)
    if raw is None:
        return default
    if isinstance(raw, (str, bytes)):
        import json

        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
            return default
    if not isinstance(raw, dict) or "count" not in raw:
        return default
    return raw


def _calculate_recovery_system_health(recovery_status, recovery_metrics):
    """Calculate overall recovery system health."""
    try:
        # Check circuit breaker states
        circuit_breakers = recovery_status.get("circuit_breakers", {})
        open_circuits = [name for name, state in circuit_breakers.items() if state.get("is_open", False)]

        # Check recovery queue backlog
        recovery_queues = recovery_status.get("recovery_queues", {})
        total_pending = sum(queue.get("pending", 0) for queue in recovery_queues.values())

        # Calculate health score
        health_score = 100

        # Deduct points for open circuits
        health_score -= len(open_circuits) * 20

        # Deduct points for pending recovery items
        if total_pending > 10:
            health_score -= min(30, total_pending * 2)

        # Determine health status
        if health_score >= 90:
            return "excellent"
        elif health_score >= 75:
            return "good"
        elif health_score >= 50:
            return "fair"
        else:
            return "poor"

    except Exception:
        return "unknown"
