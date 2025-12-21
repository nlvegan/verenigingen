"""
Mollie Integration Monitoring Utilities

Performance monitoring, health checks, and operational metrics for Mollie integration.
"""

import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import frappe
from frappe.utils import add_to_date, now_datetime

from .logging import MollieLogger, log_integration_health_check


@dataclass
class PerformanceMetric:
    """Performance metric data structure."""

    operation: str
    duration: float
    timestamp: datetime
    success: bool
    details: Optional[Dict[str, Any]] = None


@dataclass
class HealthCheckResult:
    """Health check result data structure."""

    service: str
    status: str  # healthy, degraded, unhealthy
    latency: Optional[float]
    error_message: Optional[str]
    timestamp: datetime
    details: Optional[Dict[str, Any]] = None


class MolliePerformanceMonitor:
    """
    Monitor performance metrics for Mollie operations.

    Tracks operation durations, success rates, and identifies bottlenecks.
    """

    def __init__(self):
        self.metrics: List[PerformanceMetric] = []
        self.logger = MollieLogger("performance_monitor")

    def start_operation(self, operation: str):
        """
        Start timing an operation.

        Args:
            operation: Operation name

        Returns:
            Start time for use with record_success/record_failure
        """
        import time

        return time.time()

    def record_success(self, operation_start: float, operation: str, details: Optional[Dict] = None):
        """
        Record a successful operation.

        Args:
            operation_start: Start time from start_operation()
            operation: Operation name
            details: Optional operation details
        """
        import time

        duration = time.time() - operation_start
        self.record_operation(operation, duration, True, details)

    def record_failure(self, operation_start: float, operation: str, details: Optional[Dict] = None):
        """
        Record a failed operation.

        Args:
            operation_start: Start time from start_operation()
            operation: Operation name
            details: Optional operation details
        """
        import time

        duration = time.time() - operation_start
        self.record_operation(operation, duration, False, details)

    def record_operation(
        self, operation: str, duration: float, success: bool, details: Optional[Dict] = None
    ):
        """
        Record an operation's performance metrics.

        Args:
            operation: Operation name
            duration: Duration in seconds
            success: Whether operation succeeded
            details: Additional operation details
        """
        metric = PerformanceMetric(
            operation=operation, duration=duration, timestamp=now_datetime(), success=success, details=details
        )
        self.metrics.append(metric)

        # Log if operation is slow
        if duration > 2.0:
            self.logger.warning(
                f"Slow operation detected: {operation}",
                {"duration": duration, "success": success, "details": details},
            )

    def get_operation_stats(self, operation: str, hours: int = 24) -> Dict[str, Any]:
        """
        Get statistics for a specific operation over the last N hours.

        Args:
            operation: Operation name
            hours: Hours to look back

        Returns:
            Dict with operation statistics
        """
        cutoff = add_to_date(now_datetime(), hours=-hours)
        relevant_metrics = [m for m in self.metrics if m.operation == operation and m.timestamp >= cutoff]

        if not relevant_metrics:
            return {
                "operation": operation,
                "total_calls": 0,
                "success_rate": 0,
                "avg_duration": 0,
                "max_duration": 0,
                "min_duration": 0,
            }

        durations = [m.duration for m in relevant_metrics]
        successes = [m.success for m in relevant_metrics]

        return {
            "operation": operation,
            "total_calls": len(relevant_metrics),
            "success_rate": sum(successes) / len(successes) * 100,
            "avg_duration": sum(durations) / len(durations),
            "max_duration": max(durations),
            "min_duration": min(durations),
            "slow_operations": len([d for d in durations if d > 2.0]),
        }

    def get_overall_health(self, hours: int = 24) -> Dict[str, Any]:
        """
        Get overall health metrics for the last N hours.

        Args:
            hours: Hours to look back

        Returns:
            Dict with overall health metrics
        """
        cutoff = add_to_date(now_datetime(), hours=-hours)
        relevant_metrics = [m for m in self.metrics if m.timestamp >= cutoff]

        if not relevant_metrics:
            return {
                "status": "no_data",
                "total_operations": 0,
                "overall_success_rate": 0,
                "avg_duration": 0,
                "operations_by_type": {},
            }

        # Group by operation type
        operations_by_type = defaultdict(list)
        for metric in relevant_metrics:
            operations_by_type[metric.operation].append(metric)

        operation_stats = {}
        for op_type, metrics in operations_by_type.items():
            durations = [m.duration for m in metrics]
            successes = [m.success for m in metrics]
            operation_stats[op_type] = {
                "calls": len(metrics),
                "success_rate": sum(successes) / len(successes) * 100,
                "avg_duration": sum(durations) / len(durations),
            }

        overall_success_rate = sum(m.success for m in relevant_metrics) / len(relevant_metrics) * 100
        avg_duration = sum(m.duration for m in relevant_metrics) / len(relevant_metrics)

        # Determine overall health status
        if overall_success_rate >= 95 and avg_duration < 2.0:
            status = "healthy"
        elif overall_success_rate >= 85 and avg_duration < 5.0:
            status = "degraded"
        else:
            status = "unhealthy"

        return {
            "status": status,
            "total_operations": len(relevant_metrics),
            "overall_success_rate": overall_success_rate,
            "avg_duration": avg_duration,
            "operations_by_type": operation_stats,
            "period_hours": hours,
        }


class MollieHealthChecker:
    """
    Perform health checks on Mollie integration components.

    Validates API connectivity, webhook endpoints, and service availability.
    """

    def __init__(self):
        self.logger = MollieLogger("health_checker")

    def check_mollie_api_connectivity(self) -> HealthCheckResult:
        """
        Check connectivity to Mollie API.

        Returns:
            HealthCheckResult with API connectivity status
        """
        start_time = time.time()

        try:
            # Get Mollie settings and test connection
            mollie_settings = frappe.get_single("Mollie Settings")

            if not mollie_settings.api_key:
                return HealthCheckResult(
                    service="mollie_api",
                    status="unhealthy",
                    latency=None,
                    error_message="No API key configured",
                    timestamp=now_datetime(),
                    details={"check": "api_key_validation"},
                )

            # Test API call (get methods - lightweight)
            mollie = mollie_settings.get_mollie_client()
            methods = mollie.methods.list()

            latency = time.time() - start_time

            return HealthCheckResult(
                service="mollie_api",
                status="healthy",
                latency=latency,
                error_message=None,
                timestamp=now_datetime(),
                details={
                    "check": "api_methods_list",
                    "methods_count": len(methods),
                    "api_key_prefix": (
                        mollie_settings.api_key[:8] + "..." if mollie_settings.api_key else None
                    ),
                },
            )

        except Exception as e:
            latency = time.time() - start_time

            return HealthCheckResult(
                service="mollie_api",
                status="unhealthy",
                latency=latency,
                error_message=str(e),
                timestamp=now_datetime(),
                details={"check": "api_connection", "error_type": type(e).__name__},
            )

    def check_webhook_endpoints(self) -> List[HealthCheckResult]:
        """
        Check webhook endpoint availability and configuration.

        Returns:
            List of HealthCheckResult for each webhook endpoint
        """
        results = []

        # Check if webhook endpoints are properly registered
        webhook_endpoints = [
            # Legacy endpoint disabled: "vereinigingen.integrations.mollie.api.payment_webhook.handle_mollie_payment_webhook",
            "verenigingen.verenigingen_payments.mollie.api.unified_payment_api.handle_payment_webhook",
        ]

        for endpoint in webhook_endpoints:
            start_time = time.time()

            try:
                # Check if endpoint is importable
                module_path, function_name = endpoint.rsplit(".", 1)
                module = frappe.get_module(module_path)

                if hasattr(module, function_name):
                    latency = time.time() - start_time
                    results.append(
                        HealthCheckResult(
                            service=f"webhook_endpoint_{function_name}",
                            status="healthy",
                            latency=latency,
                            error_message=None,
                            timestamp=now_datetime(),
                            details={"endpoint": endpoint, "check": "import_validation"},
                        )
                    )
                else:
                    results.append(
                        HealthCheckResult(
                            service=f"webhook_endpoint_{function_name}",
                            status="unhealthy",
                            latency=None,
                            error_message=f"Function {function_name} not found in module",  # noqa: E713
                            timestamp=now_datetime(),
                            details={"endpoint": endpoint, "check": "function_validation"},
                        )
                    )

            except Exception as e:
                latency = time.time() - start_time
                results.append(
                    HealthCheckResult(
                        service="webhook_endpoint",
                        status="unhealthy",
                        latency=latency,
                        error_message=str(e),
                        timestamp=now_datetime(),
                        details={
                            "endpoint": endpoint,
                            "check": "import_validation",
                            "error_type": type(e).__name__,
                        },
                    )
                )

        return results

    def check_service_layer_health(self) -> List[HealthCheckResult]:
        """
        Check health of service layer components.

        Returns:
            List of HealthCheckResult for each service
        """
        results = []

        services = [
            (
                "webhook_wrapper_service",
                "verenigingen.verenigingen_payments.mollie.services.webhook_wrapper_service",
                "WebhookWrapperService",
            ),
            (
                "payment_service",
                "verenigingen.verenigingen_payments.mollie.services.payment_service",
                "PaymentService",
            ),
            (
                "complete_payment_service",
                "verenigingen.verenigingen_payments.mollie.services.complete_payment_service",
                "CompletePaymentService",
            ),
        ]

        for service_name, module_path, class_name in services:
            start_time = time.time()

            try:
                # Test service import and instantiation
                module = frappe.get_module(module_path)
                service_class = getattr(module, class_name)

                # Try to instantiate
                _ = service_class()  # service_instance for potential future use

                latency = time.time() - start_time
                results.append(
                    HealthCheckResult(
                        service=f"service_{service_name}",
                        status="healthy",
                        latency=latency,
                        error_message=None,
                        timestamp=now_datetime(),
                        details={"service": service_name, "class": class_name, "check": "instantiation"},
                    )
                )

            except Exception as e:
                latency = time.time() - start_time
                results.append(
                    HealthCheckResult(
                        service=f"service_{service_name}",
                        status="unhealthy",
                        latency=latency,
                        error_message=str(e),
                        timestamp=now_datetime(),
                        details={
                            "service": service_name,
                            "class": class_name,
                            "check": "instantiation",
                            "error_type": type(e).__name__,
                        },
                    )
                )

        return results

    def run_comprehensive_health_check(self) -> Dict[str, Any]:
        """
        Run all health checks and return comprehensive health report.

        Returns:
            Dict with complete health check results
        """
        self.logger.info("Starting comprehensive health check")
        start_time = time.time()

        results = []

        # API connectivity
        api_result = self.check_mollie_api_connectivity()
        results.append(api_result)
        log_integration_health_check("mollie_api", api_result.status, api_result.details)

        # Webhook endpoints
        webhook_results = self.check_webhook_endpoints()
        results.extend(webhook_results)
        for result in webhook_results:
            log_integration_health_check(result.service, result.status, result.details)

        # Service layer
        service_results = self.check_service_layer_health()
        results.extend(service_results)
        for result in service_results:
            log_integration_health_check(result.service, result.status, result.details)

        # Aggregate results
        healthy_count = len([r for r in results if r.status == "healthy"])
        degraded_count = len([r for r in results if r.status == "degraded"])
        unhealthy_count = len([r for r in results if r.status == "unhealthy"])

        if unhealthy_count > 0:
            overall_status = "unhealthy"
        elif degraded_count > 0:
            overall_status = "degraded"
        else:
            overall_status = "healthy"

        total_duration = time.time() - start_time

        health_report = {
            "overall_status": overall_status,
            "check_duration": total_duration,
            "timestamp": now_datetime().isoformat(),
            "summary": {
                "total_checks": len(results),
                "healthy": healthy_count,
                "degraded": degraded_count,
                "unhealthy": unhealthy_count,
            },
            "details": [
                {
                    "service": r.service,
                    "status": r.status,
                    "latency": r.latency,
                    "error": r.error_message,
                    "details": r.details,
                }
                for r in results
            ],
        }

        self.logger.success(
            "Comprehensive health check completed",
            {"overall_status": overall_status, "total_checks": len(results), "duration": total_duration},
        )

        return health_report


# Global instances for easy access
performance_monitor = MolliePerformanceMonitor()
health_checker = MollieHealthChecker()


def record_operation_performance(
    operation: str, duration: float, success: bool, details: Optional[Dict] = None
):
    """
    Convenience function to record operation performance.

    Args:
        operation: Operation name
        duration: Duration in seconds
        success: Whether operation succeeded
        details: Additional operation details
    """
    performance_monitor.record_operation(operation, duration, success, details)


def get_mollie_health_status() -> Dict[str, Any]:
    """
    Get current Mollie integration health status.

    Returns:
        Dict with health status and recent performance metrics
    """
    health_report = health_checker.run_comprehensive_health_check()
    performance_summary = performance_monitor.get_overall_health(hours=24)

    return {
        "health_check": health_report,
        "performance_metrics": performance_summary,
        "generated_at": now_datetime().isoformat(),
    }
