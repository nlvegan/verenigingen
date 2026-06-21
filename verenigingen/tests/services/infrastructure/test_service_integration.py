# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Real-DB coverage tests for
verenigingen/services/infrastructure/service_integration.py.

ServiceIntegrationManager wires the four core services into the global service
factory and provides health/integration-test orchestration. These tests
exercise the manager against the REAL global ServiceFactory (registering core
services is idempotent and only touches the in-process factory; no DB writes,
no commits, no enqueue) and the standalone module functions.

The two @high_security_api endpoints are covered by
verenigingen/tests/backend/unit/services/test_service_integration_api.py; here
we focus on the manager internals, the individual-service test helpers, and the
production-readiness / load-testing / initialization helpers.
"""

from verenigingen.services.customer_handling_service import CustomerHandlingService
from verenigingen.services.infrastructure.example_service import (
    ExampleCalculationService,
    ExampleDataService,
)
from verenigingen.services.infrastructure.service_factory import get_service_factory
from verenigingen.services.infrastructure.service_integration import (
    ServiceIntegrationManager,
    get_integration_manager,
    initialize_service_infrastructure,
    run_load_testing,
    validate_production_readiness,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

CORE_SERVICE_NAMES = {
    "customer_handling",
    "customer_handling_webhook",
    "example_calculation",
    "example_data",
}


class TestServiceIntegrationManager(EnhancedTestCase):
    """ServiceIntegrationManager: registration, health, integration tests."""

    def setUp(self):
        super().setUp()
        # Use a fresh manager (not the module global) so _registered_services
        # starts empty and we assert on exactly what THIS manager registers.
        self.manager = ServiceIntegrationManager()

    def test_register_core_services_registers_all_four(self):
        results = self.manager.register_core_services()
        self.assertEqual(set(results.keys()), CORE_SERVICE_NAMES)
        # Every core service should report healthy/valid after registration.
        for name, ok in results.items():
            self.assertTrue(ok, f"core service {name} failed registration health check")
        # Internal bookkeeping populated.
        self.assertEqual(set(self.manager._registered_services), CORE_SERVICE_NAMES)

    def test_registered_services_are_retrievable_from_factory(self):
        self.manager.register_core_services()
        factory = get_service_factory()
        self.assertIsInstance(factory.get_service("customer_handling"), CustomerHandlingService)
        self.assertIsInstance(factory.get_service("example_calculation"), ExampleCalculationService)
        self.assertIsInstance(factory.get_service("example_data"), ExampleDataService)

    def test_get_service_health_summary_empty_before_registration(self):
        summary = self.manager.get_service_health_summary()
        self.assertEqual(summary["total_services"], 0)
        self.assertEqual(summary["healthy_services"], 0)
        self.assertEqual(summary["overall_health"], 0)
        self.assertEqual(summary["service_details"], {})

    def test_get_service_health_summary_after_registration(self):
        self.manager.register_core_services()
        summary = self.manager.get_service_health_summary()

        self.assertEqual(summary["total_services"], len(CORE_SERVICE_NAMES))
        # Derive expected counts from the actual details rather than hardcoding.
        healthy = sum(1 for d in summary["service_details"].values() if d["healthy"])
        self.assertEqual(summary["healthy_services"], healthy)
        self.assertEqual(
            summary["unhealthy_services"], summary["total_services"] - summary["healthy_services"]
        )
        expected_overall = summary["healthy_services"] / summary["total_services"]
        self.assertAlmostEqual(summary["overall_health"], expected_overall)
        # Each detail block carries a service_type + description.
        for name, detail in summary["service_details"].items():
            self.assertIn("service_type", detail)
            self.assertIn("description", detail)
            self.assertEqual(
                detail["description"], self.manager._registered_services[name]["description"]
            )

    def test_run_integration_tests_aggregates_counts(self):
        self.manager.register_core_services()
        results = self.manager.run_integration_tests()

        self.assertGreater(results["total_tests"], 0)
        # passed + failed must equal total.
        self.assertEqual(
            results["passed_tests"] + results["failed_tests"], results["total_tests"]
        )
        # success_rate derived consistently.
        self.assertAlmostEqual(
            results["success_rate"], results["passed_tests"] / results["total_tests"]
        )
        # Factory tests plus one block per registered service.
        self.assertIn("service_factory", results["test_details"])
        for name in CORE_SERVICE_NAMES:
            self.assertIn(name, results["test_details"])

    def test_run_integration_tests_factory_block_passes(self):
        self.manager.register_core_services()
        results = self.manager.run_integration_tests()
        factory_block = results["test_details"]["service_factory"]
        # All four factory sub-tests should pass against the live factory.
        self.assertEqual(factory_block["failed"], 0, factory_block["details"])
        self.assertEqual(factory_block["total"], 4)

    def test_health_summary_records_error_for_broken_service(self):
        """If a registered service name cannot be resolved, the summary must
        record it as unhealthy with an 'error' key rather than raising."""
        # Register reals, then inject a bogus name that the factory can't build.
        self.manager.register_core_services()
        self.manager._registered_services["__does_not_exist__"] = {
            "description": "synthetic broken service",
        }
        summary = self.manager.get_service_health_summary()
        broken = summary["service_details"]["__does_not_exist__"]
        self.assertFalse(broken["healthy"])
        self.assertIn("error", broken)
        self.assertEqual(broken["service_type"], "unknown")


class TestIndividualServiceTestHelpers(EnhancedTestCase):
    """The private _test_* helpers used by run_integration_tests."""

    def setUp(self):
        super().setUp()
        self.manager = ServiceIntegrationManager()
        self.manager.register_core_services()
        self.factory = get_service_factory()

    def test_test_individual_service_calculation(self):
        result = self.manager._test_individual_service("example_calculation")
        self.assertEqual(result["failed"], 0, result["details"])
        self.assertGreaterEqual(result["passed"], result["total"])

    def test_test_individual_service_customer(self):
        result = self.manager._test_individual_service("customer_handling")
        self.assertEqual(result["passed"] + result["failed"], result["total"])
        self.assertGreater(result["total"], 0)

    def test_test_individual_service_data(self):
        result = self.manager._test_individual_service("example_data")
        self.assertEqual(result["passed"] + result["failed"], result["total"])

    def test_test_individual_service_unknown_records_failure(self):
        result = self.manager._test_individual_service("not-a-real-service")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["failed"], 1)
        self.assertTrue(any("Service access failed" in d for d in result["details"]))

    def test_calculation_operations_helper(self):
        svc = self.factory.get_service("example_calculation")
        # Must not raise; verifies fibonacci(5) == 5 internally.
        self.manager._test_calculation_operations(svc)

    def test_singleton_behavior_helper(self):
        # customer_handling is registered singleton -> two gets are identical.
        self.manager._test_singleton_behavior()

    def test_factory_metrics_helper(self):
        self.manager._test_factory_metrics()

    def test_service_registration_helper(self):
        self.manager._test_service_registration()
        # The helper registers a throwaway non-singleton service.
        svc = self.factory.get_service("test_registration")
        self.assertIsInstance(svc, ExampleCalculationService)


class TestModuleFunctions(EnhancedTestCase):
    """Standalone module-level orchestration functions."""

    def test_get_integration_manager_singleton(self):
        m1 = get_integration_manager()
        m2 = get_integration_manager()
        self.assertIs(m1, m2)
        self.assertIsInstance(m1, ServiceIntegrationManager)

    def test_initialize_service_infrastructure(self):
        result = initialize_service_infrastructure()
        self.assertIn("success", result)
        self.assertTrue(result["success"])
        self.assertEqual(result["services_registered"], len(CORE_SERVICE_NAMES))
        self.assertEqual(
            set(result["registration_results"].keys()), CORE_SERVICE_NAMES
        )
        self.assertIsInstance(result["manager"], ServiceIntegrationManager)

    def test_validate_production_readiness_success(self):
        result = validate_production_readiness()
        self.assertTrue(result["success"], result)
        tests = result["tests"]
        self.assertTrue(tests["service_registration"]["success"])
        self.assertTrue(tests["health_monitoring"]["success"])
        self.assertTrue(tests["service_factory"]["success"])
        self.assertGreater(tests["health_monitoring"]["total_services"], 0)
        self.assertEqual(result["message"], "Production ready")

    def test_run_load_testing_small(self):
        # Keep workers/ops tiny: pure in-memory service calls, no DB/commit.
        result = run_load_testing(concurrent_workers=2, operations_per_worker=4)
        self.assertIn("load_test_passed", result)
        # total = workers * ops when all workers complete.
        self.assertEqual(result["total_operations"], 2 * 4)
        # success + failure accounting is consistent.
        self.assertEqual(
            result["successful_operations"] + result["failed_operations"],
            result["total_operations"],
        )
        self.assertEqual(
            set(result["services_tested"]), {"example_calculation", "customer_handling"}
        )
        # final_health block populated.
        self.assertIn("final_health", result)
        self.assertGreater(result["final_health"]["total_services"], 0)
        # success_rate derived from the counts.
        self.assertAlmostEqual(
            result["success_rate"],
            result["successful_operations"] / result["total_operations"],
        )

    def test_run_load_testing_passes_on_healthy_infra(self):
        result = run_load_testing(concurrent_workers=2, operations_per_worker=4)
        # Healthy in-process services -> all ops succeed, infra healthy.
        self.assertTrue(result["load_test_passed"], result)
