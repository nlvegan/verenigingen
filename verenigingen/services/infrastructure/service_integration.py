"""
Service Integration Module

Registers existing services with the service factory and provides
centralized service management for the Verenigingen application.

ERROR HANDLING PATTERN: OperationResult Pattern
===============================================
API methods return OperationResult[Dict] with type-safe error handling.
Never throws exceptions - all errors returned as OperationResult.fail().

Public API Methods:
- get_service_infrastructure_status: Returns OperationResult[Dict] (service health status)
- run_service_integration_tests: Returns OperationResult[Dict] (integration test results)

Migration Status: ✅ COMPLETE (2025-11-25)
- All API methods migrated from dict-based to OperationResult pattern
- Consistent error handling with comprehensive metadata
- Type-safe error handling preserved across all infrastructure endpoints

See: docs/patterns/OPERATION_RESULT_PATTERN.md
"""

import logging
from typing import Any, Dict, List, Optional

import frappe
from frappe import _

from verenigingen.services.customer_handling_service import CustomerHandlingService
from verenigingen.services.infrastructure.base_service import StatefulService
from verenigingen.services.infrastructure.example_service import ExampleCalculationService, ExampleDataService
from verenigingen.services.infrastructure.service_factory import get_service_factory
from verenigingen.utils.operation_result import OperationResult


class ServiceIntegrationManager:
    """Manages integration of existing services with the new infrastructure."""

    def __init__(self):
        self.logger = logging.getLogger("verenigingen.services.integration")
        self.factory = get_service_factory()
        self._registered_services = {}

    def register_core_services(self) -> Dict[str, bool]:
        """Register all core services with the service factory.

        Returns:
            Dictionary of service registration results
        """
        registration_results = {}

        # Core production services
        core_services = [
            {
                "name": "customer_handling",
                "class": CustomerHandlingService,
                "config": {"debug_context": "production"},
                "singleton": True,
                "description": "Customer and mandate management service",
            },
            {
                "name": "customer_handling_webhook",
                "class": CustomerHandlingService,
                "config": {"debug_context": "webhook"},
                "singleton": False,
                "description": "Customer handling for webhook processing",
            },
            {
                "name": "example_calculation",
                "class": ExampleCalculationService,
                "config": {"max_calculation_value": 10000},
                "singleton": True,
                "description": "Example calculation service for demonstrations",
            },
            {
                "name": "example_data",
                "class": ExampleDataService,
                "config": {"default_limit": 100, "enable_caching": True},
                "singleton": True,
                "description": "Example data service with field validation",
            },
        ]

        for service_info in core_services:
            try:
                self.factory.register_service(
                    service_info["name"],
                    service_info["class"],
                    config=service_info["config"],
                    singleton=service_info["singleton"],
                )

                # Test service creation
                test_service = self.factory.get_service(service_info["name"])
                if isinstance(test_service, StatefulService):
                    config_valid = test_service.validate_configuration()
                    is_healthy = test_service.is_healthy()
                    registration_results[service_info["name"]] = config_valid and is_healthy
                else:
                    registration_results[service_info["name"]] = True

                self._registered_services[service_info["name"]] = service_info
                self.logger.info(
                    f"Registered service: {service_info['name']} - {service_info['description']}"
                )

            except Exception as e:
                registration_results[service_info["name"]] = False
                self.logger.error(f"Failed to register service {service_info['name']}: {str(e)}")

        return registration_results

    def get_service_health_summary(self) -> Dict[str, any]:
        """Get health summary for all registered services.

        Returns:
            Comprehensive health summary
        """
        health_summary = {
            "timestamp": frappe.utils.now(),
            "total_services": len(self._registered_services),
            "healthy_services": 0,
            "unhealthy_services": 0,
            "service_details": {},
        }

        for service_name in self._registered_services:
            try:
                service = self.factory.get_service(service_name)
                is_healthy = service.is_healthy()
                metrics = service.get_metrics()

                health_summary["service_details"][service_name] = {
                    "healthy": is_healthy,
                    "metrics": metrics,
                    "service_type": type(service).__name__,
                    "description": self._registered_services[service_name]["description"],
                }

                if is_healthy:
                    health_summary["healthy_services"] += 1
                else:
                    health_summary["unhealthy_services"] += 1

            except Exception as e:
                health_summary["service_details"][service_name] = {
                    "healthy": False,
                    "error": str(e),
                    "service_type": "unknown",
                    "description": self._registered_services[service_name]["description"],
                }
                health_summary["unhealthy_services"] += 1

        health_summary["overall_health"] = (
            health_summary["healthy_services"] / health_summary["total_services"]
            if health_summary["total_services"] > 0
            else 0
        )

        return health_summary

    def run_integration_tests(self) -> Dict[str, any]:
        """Run comprehensive integration tests on all services.

        Returns:
            Test results summary
        """
        test_results = {
            "timestamp": frappe.utils.now(),
            "total_tests": 0,
            "passed_tests": 0,
            "failed_tests": 0,
            "test_details": {},
        }

        # Test service factory functionality
        factory_tests = self._test_service_factory()
        test_results["test_details"]["service_factory"] = factory_tests
        test_results["total_tests"] += factory_tests["total"]
        test_results["passed_tests"] += factory_tests["passed"]
        test_results["failed_tests"] += factory_tests["failed"]

        # Test individual services
        for service_name in self._registered_services:
            service_tests = self._test_individual_service(service_name)
            test_results["test_details"][service_name] = service_tests
            test_results["total_tests"] += service_tests["total"]
            test_results["passed_tests"] += service_tests["passed"]
            test_results["failed_tests"] += service_tests["failed"]

        test_results["success_rate"] = (
            test_results["passed_tests"] / test_results["total_tests"]
            if test_results["total_tests"] > 0
            else 0
        )

        return test_results

    def _test_service_factory(self) -> Dict[str, int]:
        """Test service factory functionality."""
        results = {"total": 0, "passed": 0, "failed": 0, "details": []}

        tests = [
            ("Service registration", self._test_service_registration),
            ("Singleton behavior", self._test_singleton_behavior),
            ("Service metrics", self._test_factory_metrics),
            ("Service cleanup", self._test_service_cleanup),
        ]

        for test_name, test_func in tests:
            results["total"] += 1
            try:
                test_func()
                results["passed"] += 1
                results["details"].append(f"✅ {test_name}")
            except Exception as e:
                results["failed"] += 1
                results["details"].append(f"❌ {test_name}: {str(e)}")

        return results

    def _test_individual_service(self, service_name: str) -> Dict[str, int]:
        """Test individual service functionality."""
        results = {"total": 0, "passed": 0, "failed": 0, "details": []}

        try:
            service = self.factory.get_service(service_name)

            tests = [
                ("Service creation", lambda: self._test_service_creation(service)),
                ("Configuration validation", lambda: self._test_service_configuration(service)),
                ("Health check", lambda: self._test_service_health(service)),
                ("Metrics collection", lambda: self._test_service_metrics(service)),
            ]

            # Add service-specific tests
            if isinstance(service, CustomerHandlingService):
                tests.append(("Customer operations", lambda: self._test_customer_operations(service)))
            elif isinstance(service, ExampleCalculationService):
                tests.append(("Calculation operations", lambda: self._test_calculation_operations(service)))
            elif isinstance(service, ExampleDataService):
                tests.append(("Data operations", lambda: self._test_data_operations(service)))

            for test_name, test_func in tests:
                results["total"] += 1
                try:
                    test_func()
                    results["passed"] += 1
                    results["details"].append(f"✅ {test_name}")
                except Exception as e:
                    results["failed"] += 1
                    results["details"].append(f"❌ {test_name}: {str(e)}")

        except Exception as e:
            results["total"] = 1
            results["failed"] = 1
            results["details"].append(f"❌ Service access failed: {str(e)}")

        return results

    def _test_service_registration(self):
        """Test service registration."""
        test_service_name = "test_registration"
        self.factory.register_service(test_service_name, ExampleCalculationService, singleton=False)
        service = self.factory.get_service(test_service_name)
        assert isinstance(service, ExampleCalculationService), "Service registration failed"

    def _test_singleton_behavior(self):
        """Test singleton behavior."""
        service1 = self.factory.get_service("customer_handling")
        service2 = self.factory.get_service("customer_handling")
        assert service1 is service2, "Singleton behavior failed"

    def _test_factory_metrics(self):
        """Test factory metrics collection."""
        metrics = self.factory.get_service_metrics()
        assert isinstance(metrics, dict), "Factory metrics failed"
        assert len(metrics) > 0, "No services in metrics"

    def _test_service_cleanup(self):
        """Test service cleanup functionality."""
        # Use the test service created in registration test
        test_service = self.factory.get_service("test_registration")
        if test_service and hasattr(test_service, "cleanup"):
            test_service.cleanup()
            assert not test_service.is_healthy(), "Service cleanup failed"
        else:
            # If cleanup is not available, test that service can be properly reset
            assert test_service is not None, "Service not available for cleanup test"

    def _test_service_creation(self, service):
        """Test service creation."""
        assert service is not None, "Service creation failed"
        assert hasattr(service, "service_name"), "Service missing name attribute"

    def _test_service_configuration(self, service):
        """Test service configuration validation."""
        if hasattr(service, "validate_configuration"):
            assert service.validate_configuration(), "Configuration validation failed"

    def _test_service_health(self, service):
        """Test service health check."""
        assert service.is_healthy(), "Service health check failed"

    def _test_service_metrics(self, service):
        """Test service metrics collection."""
        metrics = service.get_metrics()
        assert isinstance(metrics, dict), "Metrics collection failed"
        assert "calls" in metrics, "Missing calls metric"

    def _test_customer_operations(self, service: CustomerHandlingService):
        """Test customer service operations."""
        # Test customer existence validation
        result = service.ensure_donor_customer_exists("test-customer")
        assert isinstance(result, dict), "Customer operation failed"

    def _test_calculation_operations(self, service: ExampleCalculationService):
        """Test calculation service operations."""
        result = service.calculate_fibonacci(5)
        assert result["success"], "Calculation operation failed"
        assert result["data"]["result"] == 5, "Incorrect calculation result"

    def _test_data_operations(self, service: ExampleDataService):
        """Test data service operations."""
        # Test field validation is enabled
        assert hasattr(service, "_field_validation_enabled"), "Field validation not available"


# Global integration manager instance
_integration_manager = None


def get_integration_manager() -> ServiceIntegrationManager:
    """Get global service integration manager.

    Returns:
        ServiceIntegrationManager instance
    """
    global _integration_manager
    if _integration_manager is None:
        _integration_manager = ServiceIntegrationManager()
    return _integration_manager


def initialize_service_infrastructure() -> Dict[str, any]:
    """Initialize the complete service infrastructure.

    Returns:
        Initialization results
    """
    manager = get_integration_manager()
    registration_results = manager.register_core_services()

    return {
        "success": all(registration_results.values()),
        "timestamp": frappe.utils.now(),
        "services_registered": len(registration_results),
        "registration_results": registration_results,
        "manager": manager,
    }


# Validation and testing functions
def validate_production_readiness() -> Dict[str, any]:
    """Quick production readiness validation for service infrastructure.

    Returns:
        Validation results summary
    """
    try:
        manager = get_integration_manager()

        # Test 1: Service registration
        registration_results = manager.register_core_services()
        registration_success = all(registration_results.values())

        # Test 2: Health monitoring
        health_summary = manager.get_service_health_summary()
        health_success = health_summary["overall_health"] > 0.8

        # Test 3: Service factory operations
        factory = get_service_factory()
        try:
            customer_service = factory.get_service("customer_handling")
            factory_metrics = factory.get_service_metrics()
            factory_success = customer_service is not None and len(factory_metrics) > 0
        except Exception:
            factory_success = False

        overall_success = registration_success and health_success and factory_success

        return {
            "success": overall_success,
            "timestamp": frappe.utils.now(),
            "tests": {
                "service_registration": {
                    "success": registration_success,
                    "services_registered": len(registration_results),
                    "results": registration_results,
                },
                "health_monitoring": {
                    "success": health_success,
                    "overall_health": health_summary["overall_health"],
                    "healthy_services": health_summary["healthy_services"],
                    "total_services": health_summary["total_services"],
                },
                "service_factory": {
                    "success": factory_success,
                    "services_available": len(factory_metrics) if factory_success else 0,
                },
            },
            "message": "Production ready" if overall_success else "Needs attention",
        }

    except Exception as e:
        return {
            "success": False,
            "timestamp": frappe.utils.now(),
            "error": str(e),
            "message": f"Validation failed: {str(e)}",
        }


def run_load_testing(concurrent_workers: int = 5, operations_per_worker: int = 20) -> Dict[str, any]:
    """Run load testing on service infrastructure.

    Args:
        concurrent_workers: Number of concurrent threads
        operations_per_worker: Operations per thread

    Returns:
        Load testing results
    """
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    try:
        manager = get_integration_manager()
        factory = get_service_factory()

        # Ensure services are registered
        manager.register_core_services()

        results = {
            "start_time": frappe.utils.now(),
            "workers": concurrent_workers,
            "operations_per_worker": operations_per_worker,
            "total_operations": 0,
            "successful_operations": 0,
            "failed_operations": 0,
            "avg_response_time": 0,
            "services_tested": [],
            "errors": [],
        }

        def worker_task(worker_id: int) -> Dict:
            """Single worker task."""
            worker_results = {
                "worker_id": worker_id,
                "operations": 0,
                "successes": 0,
                "failures": 0,
                "total_time": 0,
            }

            start_time = time.time()

            for op in range(operations_per_worker):
                try:
                    # Test different services (avoid data service for now due to DB connection issues)
                    if op % 2 == 0:
                        # Test calculation service
                        service = factory.get_service("example_calculation")
                        if service:
                            result = service.calculate_fibonacci(min(10, op % 12))
                            if result.get("success", True):
                                worker_results["successes"] += 1
                            else:
                                worker_results["failures"] += 1
                    else:
                        # Test customer service health and metrics
                        service = factory.get_service("customer_handling")
                        if service and hasattr(service, "is_healthy"):
                            healthy = service.is_healthy()
                            metrics = service.get_metrics() if hasattr(service, "get_metrics") else {}
                            if healthy and isinstance(metrics, dict):
                                worker_results["successes"] += 1
                            else:
                                worker_results["failures"] += 1

                    worker_results["operations"] += 1

                except Exception:
                    worker_results["failures"] += 1

            worker_results["total_time"] = time.time() - start_time
            return worker_results

        # Execute concurrent workers
        with ThreadPoolExecutor(max_workers=concurrent_workers) as executor:
            futures = [executor.submit(worker_task, i) for i in range(concurrent_workers)]

            worker_results = []
            for future in futures:
                try:
                    result = future.result()
                    worker_results.append(result)
                except Exception as e:
                    results["errors"].append(f"Worker failed: {str(e)}")

        # Aggregate results
        if worker_results:
            results["total_operations"] = sum(w["operations"] for w in worker_results)
            results["successful_operations"] = sum(w["successes"] for w in worker_results)
            results["failed_operations"] = sum(w["failures"] for w in worker_results)

            total_time = sum(w["total_time"] for w in worker_results)
            if results["total_operations"] > 0:
                results["avg_response_time"] = total_time / results["total_operations"]

        # Test health after load
        final_health = manager.get_service_health_summary()
        results["final_health"] = {
            "overall_health": final_health["overall_health"],
            "healthy_services": final_health["healthy_services"],
            "total_services": final_health["total_services"],
        }

        success_rate = (
            (results["successful_operations"] / results["total_operations"])
            if results["total_operations"] > 0
            else 0
        )
        results["success_rate"] = success_rate
        results["load_test_passed"] = success_rate > 0.8 and final_health["overall_health"] > 0.8

        results["services_tested"] = ["example_calculation", "customer_handling"]

        return results

    except Exception as e:
        return {"load_test_passed": False, "error": str(e), "timestamp": frappe.utils.now()}


# API endpoints for monitoring and testing
@frappe.whitelist()
def get_service_infrastructure_status() -> OperationResult[Dict[str, Any]]:
    """API endpoint to get service infrastructure status.

    Returns:
        OperationResult[Dict]: Service health summary with timestamp
    """
    try:
        manager = get_integration_manager()
        health_summary = manager.get_service_health_summary()

        status_data = {
            "data": health_summary,
            "timestamp": frappe.utils.now(),
        }

        return OperationResult.ok(status_data, message="Service infrastructure status retrieved successfully")

    except Exception as e:
        frappe.log_error(
            f"Error retrieving service infrastructure status: {str(e)}", "Service Integration Error"
        )
        return OperationResult.fail(
            _("Unable to retrieve service infrastructure status. Please contact support."),
            errors=[str(e)],
            timestamp=frappe.utils.now(),
            context={"operation": "infrastructure_status"},
        )


@frappe.whitelist()
def run_service_integration_tests() -> OperationResult[Dict[str, Any]]:
    """API endpoint to run service integration tests.

    Returns:
        OperationResult[Dict]: Integration test results with success rate
    """
    try:
        manager = get_integration_manager()
        test_results = manager.run_integration_tests()

        test_data = {
            "data": test_results,
            "timestamp": frappe.utils.now(),
        }

        # 80% success rate required
        success_rate = test_results.get("success_rate", 0)
        if success_rate > 0.8:
            return OperationResult.ok(
                test_data, message=f"Integration tests passed with {success_rate:.1%} success rate"
            )
        else:
            return OperationResult.fail(
                _("Integration tests failed to meet 80% success threshold"),
                errors=[f"Success rate: {success_rate:.1%}"],
                **test_data,
                context={"operation": "integration_tests", "success_rate": success_rate},
            )

    except Exception as e:
        frappe.log_error(f"Error running service integration tests: {str(e)}", "Service Integration Error")
        return OperationResult.fail(
            _("Unable to run service integration tests. Please contact support."),
            errors=[str(e)],
            timestamp=frappe.utils.now(),
            context={"operation": "integration_tests"},
        )
