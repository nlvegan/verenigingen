# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Unit tests for Member Test Utilities API

Tests member testing utility API endpoints with OperationResult pattern.
Focus on type-safe error handling for member testing operations.

Migration Status: ✅ COMPLETE (2025-11-25)
- All tests use OperationResult API
- Proper assertions for .success, .data, .error_message
"""

import unittest

import frappe

from verenigingen.services.member.testing.member_test_utilities import (
    test_amendment_filtering,
    test_automatic_fee_history_update,
    test_dues_schedule_query,
    test_fee_history_functionality,
    test_member_form_functionality,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMemberTestUtilitiesAPI(EnhancedTestCase):
    """Unit tests for Member Test Utilities API endpoints"""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        # Create a test member for testing
        self.test_member = self.create_test_member(first_name="TestUtilities", last_name="Member")

    def test_test_member_form_functionality_returns_operation_result(self):
        """Test test_member_form_functionality returns OperationResult.

        Rewritten: `assertIsNotNone(result.success)` is always true (success
        is a bool), and the `if result.success:` guard meant the rest of the
        method silently asserted nothing on a failure — the test passed
        either way. With a real, freshly-created member the call must
        succeed; assert that unconditionally (matching the established
        pattern in `test_dues_schedule_query_with_valid_member` below).
        """
        result = test_member_form_functionality(self.test_member.name)

        self.assertTrue(result.success, result.error_message)
        self.assertIsInstance(result.data, dict)
        self.assertIn("tests", result.data)
        self.assertIn("member_name", result.data)

    def test_test_member_form_functionality_with_invalid_member(self):
        """Test member form functionality with non-existent member"""
        result = test_member_form_functionality("INVALID_MEMBER_NAME")

        # Should fail gracefully
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error_message)

    def test_test_dues_schedule_query_returns_operation_result(self):
        """Test test_dues_schedule_query returns OperationResult.

        Rewritten: same `assertIsNotNone(bool)` + unguarded `if` tautology as
        above — the query itself always succeeds (it succeeds even when no
        schedule is found; see `test_dues_schedule_query_with_valid_member`).
        """
        result = test_dues_schedule_query(self.test_member.name)

        self.assertTrue(result.success, result.error_message)
        self.assertIsInstance(result.data, dict)
        self.assertIn("query_result", result.data)
        self.assertIn("filters_used", result.data)

    def test_test_amendment_filtering_returns_operation_result(self):
        """Test test_amendment_filtering returns OperationResult.

        Rewritten: same `assertIsNotNone(bool)` + unguarded `if` tautology.
        Note: `test_amendment_filtering()` (the production function) takes no
        argument and queries a hardcoded member name internally — it succeeds
        (with a 0-amendment result) regardless of whether that member exists
        on this site, confirmed empirically; assert the success unconditionally.
        """
        result = test_amendment_filtering()

        self.assertTrue(result.success, result.error_message)
        self.assertIsInstance(result.data, dict)
        self.assertIn("filtered_count", result.data)
        self.assertIn("raw_count", result.data)

    def test_test_fee_history_functionality_returns_operation_result(self):
        """Test test_fee_history_functionality returns OperationResult.

        Rewritten: same `assertIsNotNone(bool)` + unguarded `if` tautology.
        """
        result = test_fee_history_functionality(self.test_member.name)

        self.assertTrue(result.success, result.error_message)
        self.assertIsInstance(result.data, dict)
        self.assertIn("member_name", result.data)
        self.assertIn("fee_change_history_count", result.data)

    def test_test_utilities_apis_never_throw_exceptions(self):
        """Test that test utility APIs never throw exceptions"""
        # Test with various inputs
        apis_to_test = [
            (test_member_form_functionality, (self.test_member.name,)),
            (test_member_form_functionality, ("INVALID_MEMBER",)),
            (test_dues_schedule_query, (self.test_member.name,)),
            (test_amendment_filtering, ()),
            (test_fee_history_functionality, (self.test_member.name,)),
        ]

        for api_func, args in apis_to_test:
            result = api_func(*args)
            self.assertIsNotNone(result, f"{api_func.__name__} returned None")
            self.assertIsNotNone(result.success, f"{api_func.__name__} missing success attribute")

    def test_api_results_contain_proper_metadata(self):
        """Test that API results contain expected metadata structure"""
        result = test_member_form_functionality(self.test_member.name)

        # Check OperationResult structure
        self.assertIsNotNone(result)
        if result.success:
            self.assertIsInstance(result.data, dict)
        else:
            self.assertIsNotNone(result.error_message)
            self.assertIsInstance(result.errors, list)

    def test_member_form_functionality_test_counts(self):
        """Test that member form functionality returns test counts.

        Rewritten: unguarded `if result.success:` meant this passed even on
        failure (never actually checking a test count). A real member must
        succeed here.
        """
        result = test_member_form_functionality(self.test_member.name)

        self.assertTrue(result.success, result.error_message)
        self.assertIn("tests", result.data)
        self.assertIsInstance(result.data["tests"], list)
        # Should have at least some tests
        self.assertGreater(len(result.data["tests"]), 0)

    def test_dues_schedule_query_with_valid_member(self):
        """Test dues schedule query with valid member"""
        result = test_dues_schedule_query(self.test_member.name)

        # Should succeed even if no schedule found
        self.assertTrue(result.success)
        self.assertIn("filters_used", result.data)


def run_tests():
    """Helper function to run tests from console"""
    frappe.flags.in_test = True
    import unittest

    suite = unittest.TestLoader().loadTestsFromTestCase(TestMemberTestUtilitiesAPI)
    unittest.TextTestRunner(verbosity=2).run(suite)
