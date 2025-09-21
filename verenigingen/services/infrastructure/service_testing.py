"""
Service Testing Framework - Standardized testing patterns for services.

This module provides base classes and utilities for testing services with
consistent patterns, mocking capabilities, and performance validation.

Classes:
    - ServiceTestCase: Base test case for service testing
    - MockServiceFactory: Mock factory for testing with dependency injection
    - ServicePerformanceTest: Performance testing utilities
    - ServiceIntegrationTest: Integration testing base class
"""

import time
import unittest
from typing import Any, Dict, List, Optional, Type
from unittest.mock import Mock, patch

import frappe
from frappe.test_runner import make_test_records

from verenigingen.services.infrastructure.base_service import BaseService
from verenigingen.services.infrastructure.service_factory import ServiceFactory, ServiceRegistry
from verenigingen.utils.service_error_handler import ServiceError


class ServiceTestCase(unittest.TestCase):
    """Base test case for service testing with common setup and utilities."""

    @classmethod
    def setUpClass(cls):
        """Set up test class with clean database state."""
        super().setUpClass()
        cls.test_records = make_test_records("verenigingen")

    def setUp(self):
        """Set up individual test with fresh service instances."""
        super().setUp()
        self.service_factory = ServiceFactory()
        self.mock_services = {}

        # Start database transaction for test isolation
        frappe.db.begin()

    def tearDown(self):
        """Clean up after each test."""
        # Rollback any database changes
        frappe.db.rollback()

        # Clean up mock services
        for mock_service in self.mock_services.values():
            if hasattr(mock_service, "cleanup"):
                mock_service.cleanup()

        # Clear service factory
        self.service_factory.shutdown_services()
        super().tearDown()

    def create_mock_service(self, service_class: Type[BaseService], service_name: str = None) -> Mock:
        """Create a mock service instance.

        Args:
            service_class: Service class to mock
            service_name: Name for the service

        Returns:
            Mock service instance
        """
        service_name = service_name or service_class.__name__
        mock_service = Mock(spec=service_class)
        mock_service.service_name = service_name
        mock_service.get_metrics.return_value = {
            "calls": 0,
            "errors": 0,
            "total_time": 0.0,
            "average_time": 0.0,
            "error_rate": 0.0,
        }

        self.mock_services[service_name] = mock_service
        return mock_service

    def register_test_service(
        self, service_name: str, service_class: Type[BaseService], config: Dict = None, mock: bool = False
    ) -> BaseService:
        """Register a service for testing.

        Args:
            service_name: Name of the service
            service_class: Service class
            config: Configuration for the service
            mock: Whether to use a mock instead of real service

        Returns:
            Service instance (real or mock)
        """
        if mock:
            return self.create_mock_service(service_class, service_name)

        self.service_factory.register_service(service_name, service_class, config, singleton=False)
        return self.service_factory.create_service(service_name)

    def assert_service_result(
        self, result: Dict, success: bool = True, has_data: bool = None, has_errors: bool = None
    ):
        """Assert that a service result has the expected structure and status.

        Args:
            result: Service result dictionary
            success: Expected success status
            has_data: Whether result should have data
            has_errors: Whether result should have errors
        """
        self.assertIsInstance(result, dict, "Service result must be a dictionary")
        self.assertIn("success", result, "Service result must have 'success' field")
        self.assertEqual(result["success"], success, f"Expected success={success}")

        if has_data is not None:
            if has_data:
                self.assertIn("data", result, "Service result should have 'data' field")
                self.assertIsNotNone(result["data"], "Service result data should not be None")
            else:
                self.assertTrue(
                    "data" not in result or result["data"] is None, "Service result should not have data"
                )

        if has_errors is not None:
            if has_errors:
                self.assertIn("errors", result, "Service result should have 'errors' field")
                self.assertTrue(len(result["errors"]) > 0, "Service result should have error messages")
            else:
                self.assertTrue(
                    "errors" not in result or len(result.get("errors", [])) == 0,
                    "Service result should not have errors",
                )

    def assert_performance_within_limits(
        self, service: BaseService, max_average_time: float = 1.0, max_error_rate: float = 0.05
    ):
        """Assert that service performance is within acceptable limits.

        Args:
            service: Service instance to check
            max_average_time: Maximum acceptable average operation time
            max_error_rate: Maximum acceptable error rate
        """
        metrics = service.get_metrics()

        self.assertLessEqual(
            metrics["average_time"],
            max_average_time,
            f"Average operation time {metrics['average_time']:.3f}s exceeds limit {max_average_time}s",
        )

        self.assertLessEqual(
            metrics["error_rate"],
            max_error_rate,
            f"Error rate {metrics['error_rate']:.2%} exceeds limit {max_error_rate:.2%}",
        )

    def simulate_database_error(self, error_message: str = "Simulated database error"):
        """Simulate a database error for testing error handling.

        Args:
            error_message: Error message to use
        """
        return patch("frappe.db.sql", side_effect=Exception(error_message))

    def simulate_permission_error(self, user: str = "test_user"):
        """Simulate a permission error for testing security.

        Args:
            user: User to simulate permission error for
        """
        return patch("frappe.has_permission", return_value=False)


class ServicePerformanceTest(ServiceTestCase):
    """Performance testing utilities for services."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.performance_data = []

    def measure_operation_performance(self, operation_func, iterations: int = 10, *args, **kwargs) -> Dict:
        """Measure performance of a service operation.

        Args:
            operation_func: Function to measure
            iterations: Number of iterations to run
            *args: Arguments for the function
            **kwargs: Keyword arguments for the function

        Returns:
            Performance measurement results
        """
        times = []
        errors = 0

        for i in range(iterations):
            start_time = time.time()
            try:
                operation_func(*args, **kwargs)
            except Exception:
                errors += 1
            times.append(time.time() - start_time)

        results = {
            "iterations": iterations,
            "total_time": sum(times),
            "average_time": sum(times) / len(times),
            "min_time": min(times),
            "max_time": max(times),
            "errors": errors,
            "error_rate": errors / iterations,
            "operations_per_second": iterations / sum(times),
        }

        self.performance_data.append(
            {"operation": operation_func.__name__, "results": results, "timestamp": time.time()}
        )

        return results

    def assert_performance_regression(
        self, current_results: Dict, baseline_results: Dict, tolerance: float = 0.2
    ):
        """Assert that performance hasn't regressed compared to baseline.

        Args:
            current_results: Current performance results
            baseline_results: Baseline performance results
            tolerance: Acceptable performance degradation (20% by default)
        """
        current_avg = current_results["average_time"]
        baseline_avg = baseline_results["average_time"]

        max_acceptable = baseline_avg * (1 + tolerance)

        self.assertLessEqual(
            current_avg,
            max_acceptable,
            f"Performance regression detected: {current_avg:.3f}s vs baseline {baseline_avg:.3f}s "
            f"(+{((current_avg / baseline_avg) - 1) * 100:.1f}%)",
        )

    def benchmark_service(self, service: BaseService, operations: List[str], iterations: int = 10) -> Dict:
        """Benchmark multiple operations on a service.

        Args:
            service: Service to benchmark
            operations: List of operation method names
            iterations: Number of iterations per operation

        Returns:
            Benchmark results for all operations
        """
        results = {}

        for operation_name in operations:
            if hasattr(service, operation_name):
                operation_func = getattr(service, operation_name)
                results[operation_name] = self.measure_operation_performance(operation_func, iterations)
            else:
                self.fail(f"Service {service.service_name} does not have operation {operation_name}")

        return results


class ServiceIntegrationTest(ServiceTestCase):
    """Base class for service integration testing."""

    def setUp(self):
        """Set up integration test with real services and dependencies."""
        super().setUp()
        self.integration_services = {}

    def create_integration_environment(self, services: List[str]):
        """Create an integration testing environment with real services.

        Args:
            services: List of service names to set up
        """
        for service_name in services:
            try:
                service = self.service_factory.get_service(service_name)
                self.integration_services[service_name] = service
            except Exception as e:
                self.skipTest(
                    f"Cannot set up integration test - service {service_name} unavailable: {str(e)}"
                )

    def test_service_dependencies(self, service_name: str):
        """Test that all service dependencies are properly resolved.

        Args:
            service_name: Name of the service to test
        """
        service = self.integration_services.get(service_name)
        if not service:
            self.skipTest(f"Service {service_name} not available in integration environment")

        # Test that service is properly configured
        self.assertTrue(service.validate_configuration(), f"Service {service_name} configuration is invalid")

        # Test that service can perform basic operations
        metrics = service.get_metrics()
        self.assertIsInstance(metrics, dict, "Service should return metrics")

    def test_end_to_end_workflow(self, workflow_steps: List[Dict]):
        """Test an end-to-end workflow across multiple services.

        Args:
            workflow_steps: List of workflow step dictionaries with 'service', 'operation', and 'params'
        """
        results = []

        for step in workflow_steps:
            service_name = step["service"]
            operation = step["operation"]
            params = step.get("params", {})

            service = self.integration_services.get(service_name)
            if not service:
                self.fail(f"Service {service_name} not available for workflow step")

            if not hasattr(service, operation):
                self.fail(f"Service {service_name} does not have operation {operation}")

            operation_func = getattr(service, operation)
            try:
                result = operation_func(**params)
                results.append({"step": step, "result": result, "success": True})
            except Exception as e:
                results.append({"step": step, "error": str(e), "success": False})
                self.fail(f"Workflow step failed: {service_name}.{operation} - {str(e)}")

        return results


class MockServiceFactory(ServiceFactory):
    """Mock service factory for testing with controlled dependencies."""

    def __init__(self):
        super().__init__(ServiceRegistry())
        self.mocks = {}

    def register_mock_service(self, service_name: str, mock_service: Mock):
        """Register a mock service.

        Args:
            service_name: Name of the service
            mock_service: Mock service instance
        """
        self.mocks[service_name] = mock_service
        self.registry._singletons[service_name] = mock_service

    def get_service(self, service_name: str) -> BaseService:
        """Get a service (mock if available, otherwise real).

        Args:
            service_name: Name of the service

        Returns:
            Service instance (mock or real)
        """
        if service_name in self.mocks:
            return self.mocks[service_name]
        return super().get_service(service_name)

    def reset_mocks(self):
        """Reset all mock services."""
        for mock_service in self.mocks.values():
            mock_service.reset_mock()

    def cleanup(self):
        """Clean up factory resources."""
        # Clean up all mock services
        for mock_service in self.mocks.values():
            if hasattr(mock_service, "cleanup"):
                mock_service.cleanup()

        # Clean up base factory
        super().shutdown_services()
        self.mocks.clear()


def create_test_service_environment() -> MockServiceFactory:
    """Create a test environment with mock services.

    Returns:
        MockServiceFactory configured for testing
    """
    factory = MockServiceFactory()

    # Create common mock services
    from verenigingen.services.infrastructure.base_service import StatelessService

    mock_age_service = Mock(spec=StatelessService)
    mock_age_service.service_name = "member_age"
    mock_age_service.calculate_member_age.return_value = 25
    factory.register_mock_service("member_age", mock_age_service)

    return factory
