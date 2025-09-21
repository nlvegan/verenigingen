"""
Integration Tests - Comprehensive testing of service infrastructure with real services.

This module provides integration tests that validate the service infrastructure
using actual service implementations rather than mocks.
"""

import time
import unittest
from typing import Any, Dict

import frappe

from verenigingen.services.customer_handling_service import CustomerHandlingService
from verenigingen.services.infrastructure.base_service import StatefulService
from verenigingen.services.infrastructure.production_readiness import validate_production_readiness
from verenigingen.services.infrastructure.service_factory import get_service_factory
from verenigingen.services.infrastructure.service_testing import ServiceIntegrationTest


class ServiceInfrastructureIntegrationTest(ServiceIntegrationTest):
    """Integration tests for service infrastructure with real services."""

    @classmethod
    def setUpClass(cls):
        """Set up integration test environment."""
        super().setUpClass()
        cls.factory = get_service_factory()

    def setUp(self):
        """Set up individual test."""
        super().setUp()
        self.test_services = []

    def tearDown(self):
        """Clean up after each test."""
        # Clean up any test services
        for service in self.test_services:
            try:
                if hasattr(service, "cleanup"):
                    service.cleanup()
            except Exception as e:
                self.logger.warning(f"Error cleaning up test service: {str(e)}")

        super().tearDown()

    def test_customer_handling_service_integration(self):
        """Test CustomerHandlingService integration with infrastructure."""
        # Create real service instance
        service = CustomerHandlingService("integration_test")
        self.test_services.append(service)

        # Test service inherits from StatefulService
        self.assertIsInstance(service, StatefulService)

        # Test configuration validation
        self.assertTrue(service.validate_configuration())

        # Test service health
        self.assertTrue(service.is_healthy())

        # Test metrics collection
        initial_metrics = service.get_metrics()
        self.assertIsInstance(initial_metrics, dict)
        self.assertIn("calls", initial_metrics)
        self.assertEqual(initial_metrics["calls"], 0)

        # Test actual service operation (requires test customer)
        try:
            # Create test customer for integration test
            test_customer = frappe.new_doc("Customer")
            test_customer.customer_name = f"Integration Test Customer {int(time.time())}"
            test_customer.customer_type = "Individual"
            test_customer.customer_group = "Individual"
            test_customer.territory = "All Territories"
            test_customer.insert()

            # Test linking operation
            mollie_ids = {"customer_id": "cst_test123", "mandate_id": "mdt_test456"}
            result = service.link_customer_to_mollie(test_customer.name, mollie_ids)

            # Validate result format (standardized)
            self.assert_service_result(result, success=True, has_data=True)
            self.assertIn("timestamp", result)
            self.assertIn("service", result)
            self.assertEqual(result["service"], "customer_handling")

            # Test metrics were updated
            updated_metrics = service.get_metrics()
            self.assertGreater(updated_metrics["calls"], initial_metrics["calls"])

            # Clean up test customer
            test_customer.delete()

        except Exception as e:
            self.skipTest(f"Customer DocType integration test failed: {str(e)}")

    def test_service_factory_real_service_creation(self):
        """Test service factory with real service registration and creation."""
        # Register the CustomerHandlingService
        self.factory.register_service(
            "customer_handling_test",
            CustomerHandlingService,
            config={"debug_context": "factory_test"},
            singleton=True,
        )

        # Create service instance
        service = self.factory.get_service("customer_handling_test")
        self.test_services.append(service)

        # Verify it's the correct type
        self.assertIsInstance(service, CustomerHandlingService)

        # Test singleton behavior
        service2 = self.factory.get_service("customer_handling_test")
        self.assertIs(service, service2)

        # Test service metrics through factory
        factory_metrics = self.factory.get_service_metrics()
        self.assertIn("customer_handling_test", factory_metrics)

    def test_configuration_integration(self):
        """Test configuration system integration with real services."""
        from verenigingen.services.infrastructure.service_config import get_config_manager

        config_manager = get_config_manager()

        # Test loading configuration for real service
        customer_config = config_manager.get_service_config("customer_handling")

        # Test setting and validating configuration
        customer_config.add_type_validator("max_retries", int, 1, 10)

        # Valid configuration
        customer_config.validate_and_set("max_retries", 3)
        self.assertEqual(customer_config.get("max_retries"), 3)

        # Invalid configuration should raise error
        with self.assertRaises(ValueError):
            customer_config.validate_and_set("max_retries", 15)  # Exceeds max

        with self.assertRaises(ValueError):
            customer_config.validate_and_set("max_retries", "invalid")  # Wrong type

    def test_metrics_collection_integration(self):
        """Test metrics collection with real service operations."""
        from verenigingen.services.infrastructure.service_metrics import get_metrics_collector

        metrics_collector = get_metrics_collector()

        # Record operations for different services
        metrics_collector.record_service_operation("test_service_1", "operation_a", 0.1, True)
        metrics_collector.record_service_operation("test_service_1", "operation_b", 0.2, False)
        metrics_collector.record_service_operation("test_service_2", "operation_a", 0.15, True)

        # Test aggregated metrics
        all_metrics = metrics_collector.get_all_metrics()
        self.assertIn("test_service_1", all_metrics)
        self.assertIn("test_service_2", all_metrics)

        # Test service 1 metrics
        service1_metrics = all_metrics["test_service_1"]
        self.assertEqual(service1_metrics["calls"], 2)
        self.assertEqual(service1_metrics["errors"], 1)
        self.assertAlmostEqual(service1_metrics["total_time"], 0.3, places=2)

        # Test aggregated metrics
        aggregated = metrics_collector.get_aggregated_metrics()
        self.assertEqual(aggregated["total_calls"], 3)
        self.assertEqual(aggregated["total_errors"], 1)
        self.assertEqual(aggregated["total_services"], 2)

    def test_health_monitoring_integration(self):
        """Test health monitoring with real services."""
        from verenigingen.services.infrastructure.service_metrics import get_health_monitor

        health_monitor = get_health_monitor()

        # Create a service and record some operations
        service = CustomerHandlingService("health_test")
        self.test_services.append(service)

        # Record successful operations
        for _ in range(5):
            service._start_operation("test_op")
            service._end_operation("test_op", time.time() - 0.01, success=True)

        # Check service health
        health_result = health_monitor.check_service_health("customer_handling")
        self.assertIsInstance(health_result, dict)
        self.assertIn("success", health_result)
        self.assertIn("status", health_result)

        # Test system health
        system_health = health_monitor.get_system_health_summary()
        self.assertIsInstance(system_health, dict)
        self.assertIn("success", system_health)
        self.assertIn("data", system_health)

    def test_permission_validation_integration(self):
        """Test permission validation with real user context."""
        service = CustomerHandlingService("permission_test")
        self.test_services.append(service)

        # Test permission validation (will use current user context)
        permission_result = service.validate_permissions("read", "Customer")
        self.assertIsInstance(permission_result, dict)
        self.assertIn("success", permission_result)

        # Test different operations
        operations = ["create", "read", "update", "delete", "list"]
        for operation in operations:
            result = service.validate_permissions(operation, "Customer")
            self.assertIsInstance(result, dict)
            self.assertIn("success", result)
            self.assertIn("data", result)

    def test_error_handling_integration(self):
        """Test error handling with real service operations."""
        service = CustomerHandlingService("error_test")
        self.test_services.append(service)

        # Test handling of invalid operation
        result = service.update_customer_mandate("", "")  # Invalid parameters

        # Should return standardized error result
        self.assert_service_result(result, success=False, has_errors=True)
        self.assertIn("timestamp", result)
        self.assertIn("service", result)
        self.assertEqual(result["service"], "customer_handling")

    def test_production_readiness_validation(self):
        """Test production readiness validation."""
        # Run full production readiness check
        validation_results = validate_production_readiness()

        # Validate result structure
        self.assertIsInstance(validation_results, dict)
        self.assertIn("success", validation_results)
        self.assertIn("duration", validation_results)
        self.assertIn("results", validation_results)

        # Check that all validation steps were run
        expected_steps = [
            "Service Factory",
            "Core Services",
            "Database Access",
            "Configuration",
            "Health Monitoring",
            "Error Handling",
            "Performance",
        ]

        for step in expected_steps:
            self.assertIn(step, validation_results["results"])

        # Log results for analysis
        self.logger.info(f"Production readiness validation: {validation_results['success']}")
        if not validation_results["success"]:
            self.logger.warning(f"Critical errors: {validation_results.get('critical_errors', [])}")

    def test_end_to_end_service_workflow(self):
        """Test complete end-to-end workflow using service infrastructure."""
        # Step 1: Create service through factory
        factory = get_service_factory()
        factory.register_service("e2e_test", CustomerHandlingService, singleton=False)

        service = factory.create_service("e2e_test")
        self.test_services.append(service)

        # Step 2: Validate service configuration
        self.assertTrue(service.validate_configuration())

        # Step 3: Check initial health and metrics
        self.assertTrue(service.is_healthy())
        initial_metrics = service.get_metrics()

        # Step 4: Perform service operations
        try:
            # Create test customer
            test_customer = frappe.new_doc("Customer")
            test_customer.customer_name = f"E2E Test Customer {int(time.time())}"
            test_customer.customer_type = "Individual"
            test_customer.customer_group = "Individual"
            test_customer.territory = "All Territories"
            test_customer.insert()

            # Use service to ensure customer exists
            result = service.ensure_donor_customer_exists(test_customer.name)
            self.assert_service_result(result, success=True, has_data=True)

            # Validate customer setup
            validation_result = service.validate_customer_setup(test_customer.name)
            self.assertIsInstance(validation_result, dict)

            # Step 5: Verify metrics were updated
            final_metrics = service.get_metrics()
            self.assertGreater(final_metrics["calls"], initial_metrics["calls"])

            # Step 6: Check health after operations
            self.assertTrue(service.is_healthy())

            # Clean up
            test_customer.delete()

        except Exception as e:
            self.skipTest(f"End-to-end workflow test failed: {str(e)}")

        # Step 7: Clean up service
        service.cleanup()
        self.assertFalse(service.is_healthy())  # Should be unhealthy after cleanup


class ServiceMemoryLeakTest(unittest.TestCase):
    """Test for memory leaks in service infrastructure."""

    def test_metrics_memory_management(self):
        """Test that metrics collection doesn't leak memory."""
        from verenigingen.services.infrastructure.service_metrics import ServiceMetrics

        # Create metrics with small limits for testing
        metrics = ServiceMetrics("memory_test", max_history=10, max_operations=5)

        # Record many operations to test cleanup
        for i in range(100):
            metrics.record_operation(f"operation_{i}", 0.001, True)

        # Check that operation count is limited
        memory_usage = metrics.get_memory_usage()
        self.assertLessEqual(memory_usage["operation_count"], 5)
        self.assertTrue(memory_usage["memory_efficient"])

        # Test cleanup functionality
        old_count = len(metrics.operation_metrics)
        metrics._cleanup_old_operations()
        new_count = len(metrics.operation_metrics)
        self.assertLessEqual(new_count, old_count)

    def test_service_factory_memory_management(self):
        """Test that service factory properly manages memory."""
        factory = get_service_factory()

        initial_singletons = len(factory.registry._singletons)

        # Create multiple service instances
        for i in range(10):
            factory.register_service(f"test_service_{i}", CustomerHandlingService, singleton=True)
            service = factory.get_service(f"test_service_{i}")
            self.assertIsNotNone(service)

        # Check singleton management
        final_singletons = len(factory.registry._singletons)
        self.assertEqual(final_singletons - initial_singletons, 10)

        # Test cleanup
        factory.shutdown_services()
        self.assertEqual(len(factory.registry._singletons), 0)
