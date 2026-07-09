"""
JavaScript API Integration Tests

Behavioral tests for the whitelisted APIs that JavaScript calls into. These
exercise the real endpoints (existence/callability, response-envelope shape) and
the real boolean-coercion utility used to normalise JS-sent boolean strings.

NOTE: four source-lint "tests" that only `grep`-ped Python/JS source strings
(``test_boolean_parameter_handling``, ``test_api_function_whitelist``,
``test_member_doctype_boolean_conversions``, ``test_javascript_frappe_call_syntax``)
were removed in the residual-tautology sweep — they asserted on source text, not
runtime behavior, and passed regardless of whether the API actually worked. The
behavior they cared about (JS boolean strings must coerce correctly) is covered
for real by ``test_boolean_string_conversion`` below.
"""

import unittest

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase


class JavaScriptAPIIntegrationTestCase(VereningingenTestCase):
    """Test JavaScript API integration for common issues"""

    def test_api_method_existence(self):
        """Test that API methods referenced in JavaScript actually exist"""

        # Test some critical API endpoints
        test_cases = [
            ("verenigingen.api.membership_application.submit_application", "submit_application"),
            ("verenigingen.api.member_management.get_members_without_chapter", "get_members_without_chapter"),
            ("verenigingen.api.payment_dashboard.get_payment_history", "get_payment_history"),
            ("verenigingen.api.suspension_api.bulk_suspend_members", "bulk_suspend_members"),
        ]

        for method_path, function_name in test_cases:
            try:
                # Try to get the method
                method = frappe.get_attr(method_path)
                self.assertIsNotNone(method, f"Method {method_path} should exist")

                # Check if it's callable
                self.assertTrue(callable(method), f"Method {method_path} should be callable")

            except AttributeError:
                self.fail(f"Method {method_path} not found - check if function exists and is whitelisted")

    def test_critical_api_endpoints(self):
        """Test that critical API endpoints are working correctly"""

        # get_dashboard_data resolves a concrete member, so create one to pass in.
        member = self.create_test_member(first_name="JSAPI", last_name="Dashboard")

        # These endpoints now return an OperationResult-shaped envelope
        # ({"success": True, "data": {...}}). Each is checked for a successful
        # envelope plus the expected type of the inner ``data`` payload.
        test_endpoints = [
            {
                "method": "verenigingen.api.member_management.get_members_without_chapter",
                "args": {"limit": 10, "offset": 0},
                "data_type": dict,
            },
            {
                "method": "verenigingen.api.payment_dashboard.get_dashboard_data",
                "args": {"member": member.name},
                "data_type": dict,
            },
        ]

        for endpoint in test_endpoints:
            try:
                # Try to call the method
                result = frappe.get_attr(endpoint["method"])(**endpoint["args"])

                # Result is the standardized response envelope.
                self.assertIsInstance(
                    result, dict, f"Method {endpoint['method']} should return a response dict"
                )
                self.assertTrue(result.get("success"), f"Method {endpoint['method']} should succeed")
                self.assertIsInstance(
                    result.get("data"),
                    endpoint["data_type"],
                    f"Method {endpoint['method']} data should be {endpoint['data_type'].__name__}",
                )

            except Exception as e:
                self.fail(f"Method {endpoint['method']} failed: {str(e)}")

    def test_boolean_string_conversion(self):
        """Test that the cbool() function properly handles boolean strings"""

        from verenigingen.utils.boolean_utils import cbool

        # Test cases that were causing the original issue
        test_cases = [
            ("true", 1),
            ("false", 0),
            (True, 1),
            (False, 0),
            ("1", 1),
            ("0", 0),
            (1, 1),
            (0, 0),
            (None, 0),
            ("", 0),
        ]

        for input_val, expected in test_cases:
            result = cbool(input_val)
            self.assertEqual(
                result, expected, f"cbool({repr(input_val)}) should return {expected}, got {result}"
            )


class JavaScriptAPIIntegrationRunner:
    """Runner for JavaScript API integration tests"""

    def run_all_tests(self):
        """Run all JavaScript API integration tests"""

        # Create test suite
        suite = unittest.TestSuite()

        # Add all test methods
        test_methods = [
            "test_api_method_existence",
            "test_critical_api_endpoints",
            "test_boolean_string_conversion",
        ]

        for method in test_methods:
            suite.addTest(JavaScriptAPIIntegrationTestCase(method))

        # Run tests
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)

        return result.wasSuccessful()


def run_js_api_integration_tests():
    """Entry point for running JavaScript API integration tests"""
    runner = JavaScriptAPIIntegrationRunner()
    return runner.run_all_tests()


if __name__ == "__main__":
    # Run as standalone script
    success = run_js_api_integration_tests()
    exit(0 if success else 1)
