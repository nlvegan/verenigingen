"""
Service Infrastructure Tests - Enhanced Test Factory Integration

Tests using the Enhanced Test Factory to validate service infrastructure
components with realistic business data and proper field validation.
"""

import time
from unittest.mock import patch

import frappe

from verenigingen.services.infrastructure.base_service import APIService, DataService, StatefulService
from verenigingen.services.infrastructure.example_service import (
    ExampleCalculationService,
    ExampleDataService,
    calculate_fibonacci_api,
    search_members_api,
)
from verenigingen.services.infrastructure.production_readiness import validate_production_readiness
from verenigingen.services.infrastructure.service_factory import get_service_factory
from verenigingen.services.infrastructure.service_metrics import get_health_monitor, get_metrics_collector
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class ServiceInfrastructureEnhancedTests(EnhancedTestCase):
    """Enhanced test suite for service infrastructure using realistic test data."""

    @classmethod
    def setUpClass(cls):
        """Set up test environment with Enhanced Test Factory."""
        super().setUpClass()
        cls.factory = get_service_factory()

    def setUp(self):
        """Set up individual test with query monitoring."""
        super().setUp()
        self.test_services = []
        self.logger = frappe.logger("test_service_infrastructure")

    def assert_service_result(self, result, success=True, has_data=None, has_errors=None):
        """Assert that a service result has the expected structure and status."""
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

    def tearDown(self):
        """Clean up test services."""
        for service in self.test_services:
            try:
                if hasattr(service, "cleanup"):
                    service.cleanup()
            except Exception as e:
                self.logger.warning(f"Error cleaning up test service: {str(e)}")
        super().tearDown()

    def test_example_calculation_service_with_real_data(self):
        """Test calculation service with realistic business scenarios."""
        service = ExampleCalculationService("test_calc")
        self.test_services.append(service)

        # Test configuration validation
        self.assertTrue(service.validate_configuration())

        # Test health check
        self.assertTrue(service.is_healthy())

        # Test Fibonacci calculation with business-relevant numbers
        # Use typical member counts for chapters
        test_cases = [
            (0, 0),  # Empty chapter
            (1, 1),  # Single member
            (5, 5),  # Small chapter
            (10, 55),  # Medium chapter
            (13, 233),  # Large chapter
        ]

        for input_value, expected in test_cases:
            with self.subTest(input=input_value, expected=expected):
                result = service.calculate_fibonacci(input_value)
                self.assert_service_result(result, success=True, has_data=True)
                self.assertEqual(result["data"]["result"], expected)
                self.assertEqual(result["data"]["input"], input_value)
                self.assertIn("calculation_time", result["data"])

        # Test batch calculation
        batch_result = service.batch_calculate([0, 1, 5, 10])
        self.assert_service_result(batch_result, success=True, has_data=True)
        self.assertEqual(len(batch_result["data"]["results"]), 4)
        self.assertEqual(batch_result["data"]["successful"], 4)
        self.assertEqual(batch_result["data"]["failed"], 0)

    def test_example_data_service_with_enhanced_members(self):
        """Test data service with Enhanced Test Factory members."""
        service = ExampleDataService("test_data")
        self.test_services.append(service)

        # Test configuration validation
        self.assertTrue(service.validate_configuration())

        # Create realistic test members using Enhanced Test Factory
        test_members = []
        for i in range(3):
            member = self.create_test_member(
                first_name=f"TestMember{i:02d}",
                last_name="DataService",
                email=f"test.member{i:02d}@verenigingen-test.nl",
            )
            test_members.append(member)

        # Test member search with realistic data
        search_result = service.search_members("DataService")
        self.assert_service_result(search_result, success=True, has_data=True)

        # Verify search found our test members. EnhancedTestDataFactory
        # uniquifies last_name (appends digits), so full_name is a prefix match
        # rather than an exact match.
        found_members = search_result["data"]["members"]
        found_names = [m.get("full_name", "") for m in found_members]
        expected_prefixes = [f"TestMember{i:02d} DataService" for i in range(3)]

        for expected_prefix in expected_prefixes:
            self.assertTrue(
                any(name.startswith(expected_prefix) for name in found_names),
                f"Expected member {expected_prefix} not found in search results: {found_names}",
            )

    def test_api_service_security_integration(self):
        """Test API service security methods with Enhanced Test Factory."""
        service = APIService("test_api")
        self.test_services.append(service)

        # Test security context retrieval
        security_context = service.get_security_context()
        self.assertIsInstance(security_context, dict)
        self.assertIn("user", security_context)
        self.assertIn("roles", security_context)
        self.assertIn("service", security_context)
        self.assertEqual(security_context["service"], "test_api")

        # Test permission validation with Member DocType (field-validated)
        permission_result = service.validate_permissions("read", "Member")
        self.assert_service_result(permission_result, success=True, has_data=True)
        self.assertIn("permission_level", permission_result["data"])

        # Test input validation
        test_data = {"name": "Test", "email": "test@example.com"}
        validation_result = service.validate_input(test_data, ["name", "email"])
        self.assert_service_result(validation_result, success=True)

        # Test missing required fields
        incomplete_data = {"name": "Test"}
        validation_result = service.validate_input(incomplete_data, ["name", "email"])
        self.assert_service_result(validation_result, success=False, has_errors=True)
        self.assertIn("email", str(validation_result["errors"]))

    def test_stateful_service_transaction_management(self):
        """Test stateful service transaction handling with real database."""
        service = StatefulService("test_stateful")
        self.test_services.append(service)

        # Test transaction operations
        def test_operation():
            # Create a test member within transaction
            member = self.create_test_member(
                first_name="Transaction",
                last_name="Test",
                email="transaction.test@verenigingen-test.nl",
            )
            return member.name

        # Test successful transaction
        member_name = service.execute_with_transaction(test_operation)
        self.assertIsNotNone(member_name)

        # Verify member was created
        import frappe

        member_exists = frappe.db.exists("Member", member_name)
        self.assertTrue(member_exists)

    def test_service_factory_integration_with_enhanced_data(self):
        """Test service factory with Enhanced Test Factory data."""
        factory = get_service_factory()

        # Register and create example services
        factory.register_service("calc_service", ExampleCalculationService, singleton=True)
        factory.register_service("data_service", ExampleDataService, singleton=False)

        calc_service = factory.get_service("calc_service")
        data_service = factory.create_service("data_service")

        self.test_services.extend([calc_service, data_service])

        # Test singleton behavior
        calc_service2 = factory.get_service("calc_service")
        self.assertIs(calc_service, calc_service2)

        # Test non-singleton behavior
        data_service2 = factory.create_service("data_service")
        self.assertIsNot(data_service, data_service2)

        # Test metrics collection
        factory_metrics = factory.get_service_metrics()
        self.assertIn("calc_service", factory_metrics)

    def test_health_monitoring_with_realistic_scenarios(self):
        """Test health monitoring system with realistic service loads."""
        health_monitor = get_health_monitor()
        metrics_collector = get_metrics_collector()

        # Simulate realistic service operations
        for i in range(10):
            metrics_collector.record_service_operation(
                "member_service", "create_member", 0.15 + (i * 0.01), success=True
            )
            metrics_collector.record_service_operation(
                "payment_service", "process_payment", 0.25 + (i * 0.02), success=i % 7 != 0  # Some failures
            )

        # Test system health check
        system_health = health_monitor.get_system_health_summary()
        self.assertIsInstance(system_health, dict)
        self.assertIn("success", system_health)

        # Test aggregated metrics
        aggregated = metrics_collector.get_aggregated_metrics()
        self.assertGreater(aggregated["total_calls"], 0)
        self.assertGreater(aggregated["total_services"], 0)

    def test_production_readiness_validation_comprehensive(self):
        """Test production readiness validation in realistic environment."""
        # This test uses real database and service validation
        with self.assertQueryCount(50):  # Monitor query performance
            validation_results = validate_production_readiness()

        # Validate result structure
        self.assertIsInstance(validation_results, dict)
        self.assertIn("success", validation_results)
        self.assertIn("duration", validation_results)
        self.assertIn("results", validation_results)

        # Check critical validation steps
        required_steps = [
            "Service Factory",
            "Core Services",
            "Database Access",
            "Configuration",
            "Health Monitoring",
            "Error Handling",
            "Performance",
        ]

        for step in required_steps:
            self.assertIn(step, validation_results["results"], f"Missing validation step: {step}")

        # Log results for debugging
        if not validation_results["success"]:
            self.logger.warning(
                f"Production readiness issues: {validation_results.get('critical_errors', [])}"
            )

    def test_api_endpoints_with_security_decorators(self):
        """Test API endpoints using security framework integration."""
        # Create test member for search endpoint
        test_member = self.create_test_member(
            first_name="API",
            last_name="Test",
            email="api.test@verenigingen-test.nl",
        )

        # Test public API endpoint (Fibonacci calculation)
        result = calculate_fibonacci_api(8)
        self.assert_service_result(result, success=True, has_data=True)
        self.assertEqual(result["data"]["result"], 21)  # 8th Fibonacci number

        # Test standard API endpoint (member search) - requires proper security
        search_result = search_members_api("API Test")
        self.assert_service_result(search_result, success=True, has_data=True)

        # Verify search found our test member. EnhancedTestDataFactory
        # uniquifies last_name (appends digits), so match on the name prefix.
        members = search_result["data"]["members"]
        member_names = [m.get("full_name", "") for m in members]
        self.assertTrue(
            any(name.startswith("API Test") for name in member_names),
            f"Expected member 'API Test' not found in search results: {member_names}",
        )

    def test_error_handling_integration(self):
        """Test error handling across service infrastructure."""
        service = ExampleCalculationService("error_test")
        self.test_services.append(service)

        # Test error handling with invalid input
        result = service.calculate_fibonacci(-1)  # Invalid input
        self.assert_service_result(result, success=False, has_errors=True)
        self.assertIn("negative", str(result["errors"]).lower())

        # Test configuration limit enforcement
        result = service.calculate_fibonacci(50000)  # Exceeds configured limit
        self.assert_service_result(result, success=False, has_errors=True)
        self.assertIn("maximum", str(result["errors"]).lower())

    def test_memory_leak_prevention(self):
        """Test that service infrastructure doesn't leak memory."""
        from verenigingen.services.infrastructure.service_metrics import ServiceMetrics

        # Test metrics cleanup
        metrics = ServiceMetrics("memory_test", max_history=5, max_operations=3)

        # Record many operations
        for i in range(20):
            metrics.record_operation(f"op_{i}", 0.001, True)

        # Verify cleanup worked
        memory_usage = metrics.get_memory_usage()
        self.assertLessEqual(memory_usage["operation_count"], 3)
        self.assertTrue(memory_usage["memory_efficient"])

    def test_field_validation_integration(self):
        """Test that service infrastructure respects Enhanced Test Factory field validation."""
        # This test ensures our services work with the field validation system

        # Create member with validated fields
        member = self.create_test_member(
            first_name="Field",
            last_name="Validation",
            email="field.validation@verenigingen-test.nl",
        )

        # Test that service operations respect field validation
        service = ExampleDataService("field_test")
        self.test_services.append(service)

        # Search should work with properly validated member
        result = service.search_members("Field Validation")
        self.assert_service_result(result, success=True, has_data=True)

        # Verify member found
        members = result["data"]["members"]
        self.assertGreater(len(members), 0)
