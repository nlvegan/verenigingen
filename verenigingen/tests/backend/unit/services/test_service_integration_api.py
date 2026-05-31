# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Unit tests for Service Integration API

Tests service integration API endpoints with OperationResult pattern.
Focus on type-safe error handling for infrastructure monitoring operations.

NOTE (2026-05-31): These API functions are decorated with @high_security_api,
which converts the returned OperationResult into the nested-schema dict via
OperationResult.to_dict(scrub_sensitive=True) for JSON serialization. The
values returned to these tests are dicts, not OperationResult objects:
  - success:  result["success"] (bool)
  - data:     result["data"]
  - failure:  result["error"]["message"], result["error"].get("errors")
"""

import frappe
from verenigingen.services.infrastructure.service_integration import (
    get_service_infrastructure_status,
    run_service_integration_tests,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
import unittest


class TestServiceIntegrationAPI(EnhancedTestCase):
    """Unit tests for Service Integration API endpoints"""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def test_get_service_infrastructure_status_returns_operation_result(self):
        """Test get_service_infrastructure_status returns OperationResult"""
        result = get_service_infrastructure_status()

        # OperationResult (serialized to nested-schema dict by decorator)
        self.assertIsNotNone(result)
        self.assertIn("success", result)

        if result["success"]:
            self.assertIsInstance(result["data"], dict)
            self.assertIn("data", result["data"])
            self.assertIn("timestamp", result["data"])

    def test_run_service_integration_tests_returns_operation_result(self):
        """Test run_service_integration_tests returns OperationResult"""
        result = run_service_integration_tests()

        # OperationResult (serialized to nested-schema dict by decorator)
        self.assertIsNotNone(result)
        self.assertIn("success", result)

        if result["success"]:
            self.assertIsInstance(result["data"], dict)
            self.assertIn("data", result["data"])
            self.assertIn("timestamp", result["data"])

    def test_infrastructure_apis_never_throw_exceptions(self):
        """Test that infrastructure APIs never throw exceptions"""
        # Test all APIs
        apis_to_test = [
            (get_service_infrastructure_status, ()),
            (run_service_integration_tests, ()),
        ]

        for api_func, args in apis_to_test:
            result = api_func(*args)
            self.assertIsNotNone(result, f"{api_func.__name__} returned None")
            self.assertIn("success", result, f"{api_func.__name__} missing success key")

    def test_api_results_contain_proper_metadata(self):
        """Test that API results contain expected metadata structure"""
        result = get_service_infrastructure_status()

        # Check OperationResult nested-schema structure
        self.assertIsNotNone(result)
        if result["success"]:
            self.assertIsInstance(result["data"], dict)
        else:
            self.assertIsNotNone(result["error"]["message"])
            self.assertIsInstance(result["error"].get("errors", []), list)

    def test_infrastructure_status_contains_timestamp(self):
        """Test that infrastructure status contains timestamp"""
        result = get_service_infrastructure_status()

        if result["success"]:
            self.assertIn("timestamp", result["data"])
            self.assertIsNotNone(result["data"]["timestamp"])

    def test_integration_tests_contains_timestamp(self):
        """Test that integration tests contain timestamp"""
        result = run_service_integration_tests()

        # Top-level timestamp is always present in the serialized result dict
        self.assertIn("timestamp", result)
        if result["success"]:
            self.assertIn("timestamp", result["data"])


def run_tests():
    """Helper function to run tests from console"""
    frappe.flags.in_test = True
    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestServiceIntegrationAPI)
    unittest.TextTestRunner(verbosity=2).run(suite)
