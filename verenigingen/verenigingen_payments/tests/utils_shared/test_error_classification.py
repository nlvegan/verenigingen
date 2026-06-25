"""
Tests for shared error classification utility.

Tests the `classify_error` function which categorizes exceptions
into standardized failure categories for unified error handling.
"""

from enum import Enum
from unittest import TestCase

import frappe

from verenigingen.verenigingen_payments.utils.shared.error_classification import (
    FailureCategory,
    classify_error,
)


class TestErrorClassification(TestCase):
    """Test suite for error classification"""

    def test_classify_transient_connection_error(self):
        """Connection errors should be classified as TRANSIENT"""
        error = Exception("connection reset by peer")
        self.assertEqual(classify_error(error), FailureCategory.TRANSIENT)

    def test_classify_transient_timeout_error(self):
        """Timeout errors should be classified as TRANSIENT"""
        error = Exception("request timeout")
        self.assertEqual(classify_error(error), FailureCategory.TRANSIENT)

    def test_classify_validation_error_from_message(self):
        """Validation keyword in message should classify as VALIDATION"""
        error = Exception("invalid IBAN")
        self.assertEqual(classify_error(error), FailureCategory.VALIDATION)

    def test_classify_validation_error_value_error(self):
        """ValueError should be classified as VALIDATION"""
        error = ValueError("x")
        self.assertEqual(classify_error(error), FailureCategory.VALIDATION)

    def test_classify_validation_error_type_error(self):
        """TypeError should be classified as VALIDATION"""
        error = TypeError("x")
        self.assertEqual(classify_error(error), FailureCategory.VALIDATION)

    def test_classify_authorization_error_from_message(self):
        """Permission errors in message should classify as AUTHORIZATION"""
        error = Exception("permission denied")
        self.assertEqual(classify_error(error), FailureCategory.AUTHORIZATION)

    def test_classify_authorization_error_frappe_permission_error(self):
        """frappe.PermissionError should be classified as AUTHORIZATION"""
        error = frappe.PermissionError("access denied")
        self.assertEqual(classify_error(error), FailureCategory.AUTHORIZATION)

    def test_classify_data_error(self):
        """Data not found errors should classify as DATA"""
        error = Exception("record not found")
        self.assertEqual(classify_error(error), FailureCategory.DATA)

    def test_classify_system_error(self):
        """Unclassified errors should default to SYSTEM"""
        error = Exception("weird error")
        self.assertEqual(classify_error(error), FailureCategory.SYSTEM)

    def test_classify_resource_error(self):
        """Resource limit errors should classify as RESOURCE"""
        error = Exception("limit exceeded")
        self.assertEqual(classify_error(error), FailureCategory.RESOURCE)

    def test_failure_category_is_enum(self):
        """FailureCategory should be an Enum with string values"""
        self.assertTrue(issubclass(FailureCategory, Enum))
        self.assertTrue(issubclass(FailureCategory, str))

    def test_failure_category_has_all_required_values(self):
        """FailureCategory should have all required category values"""
        required = {"TRANSIENT", "RESOURCE", "VALIDATION", "AUTHORIZATION", "BUSINESS", "DATA", "SYSTEM"}
        actual = {member.name for member in FailureCategory}
        self.assertEqual(actual, required)

    def test_classify_empty_error_message(self):
        """Error with empty message should default to SYSTEM"""
        error = Exception("")
        self.assertEqual(classify_error(error), FailureCategory.SYSTEM)

    def test_classify_case_insensitive_matching(self):
        """Error classification should be case-insensitive"""
        error = Exception("CONNECTION RESET")
        self.assertEqual(classify_error(error), FailureCategory.TRANSIENT)

    def test_classify_network_error(self):
        """Network errors should classify as TRANSIENT"""
        error = Exception("network unreachable")
        self.assertEqual(classify_error(error), FailureCategory.TRANSIENT)

    def test_classify_deadlock_error(self):
        """Deadlock errors should classify as TRANSIENT"""
        error = Exception("deadlock detected")
        self.assertEqual(classify_error(error), FailureCategory.TRANSIENT)

    def test_classify_unavailable_error(self):
        """Service unavailable errors should classify as TRANSIENT"""
        error = Exception("service unavailable")
        self.assertEqual(classify_error(error), FailureCategory.TRANSIENT)

    def test_classify_overload_error(self):
        """Overload errors should classify as TRANSIENT"""
        error = Exception("server overload")
        self.assertEqual(classify_error(error), FailureCategory.TRANSIENT)

    def test_classify_missing_field_error(self):
        """Missing field validation errors should classify as VALIDATION"""
        error = Exception("required field missing")
        self.assertEqual(classify_error(error), FailureCategory.VALIDATION)

    def test_classify_format_error(self):
        """Format validation errors should classify as VALIDATION"""
        error = Exception("invalid format")
        self.assertEqual(classify_error(error), FailureCategory.VALIDATION)

    def test_classify_constraint_violation(self):
        """Constraint violation errors should classify as VALIDATION"""
        error = Exception("constraint violation")
        self.assertEqual(classify_error(error), FailureCategory.VALIDATION)

    def test_classify_duplicate_error(self):
        """Duplicate entry errors should classify as VALIDATION"""
        error = Exception("duplicate entry")
        self.assertEqual(classify_error(error), FailureCategory.VALIDATION)

    def test_classify_authentication_error(self):
        """Authentication errors should classify as AUTHORIZATION"""
        error = Exception("authentication failed")
        self.assertEqual(classify_error(error), FailureCategory.AUTHORIZATION)

    def test_classify_unauthorized_error(self):
        """Unauthorized errors should classify as AUTHORIZATION"""
        error = Exception("unauthorized access")
        self.assertEqual(classify_error(error), FailureCategory.AUTHORIZATION)

    def test_classify_forbidden_error(self):
        """Forbidden errors should classify as AUTHORIZATION"""
        error = Exception("access forbidden")
        self.assertEqual(classify_error(error), FailureCategory.AUTHORIZATION)

    def test_classify_does_not_exist_error(self):
        """Does not exist errors should classify as DATA"""
        error = Exception("does not exist")
        self.assertEqual(classify_error(error), FailureCategory.DATA)

    def test_classify_empty_result_error(self):
        """Empty result errors should classify as DATA"""
        error = Exception("result is empty")
        self.assertEqual(classify_error(error), FailureCategory.DATA)

    def test_classify_null_error(self):
        """Null value errors should classify as DATA"""
        error = Exception("null value")
        self.assertEqual(classify_error(error), FailureCategory.DATA)

    def test_classify_resource_limit_error(self):
        """Resource limit errors should classify as RESOURCE"""
        error = Exception("resource limit exceeded")
        self.assertEqual(classify_error(error), FailureCategory.RESOURCE)

    def test_classify_resource_busy_error(self):
        """Resource busy errors should classify as RESOURCE"""
        error = Exception("resource busy")
        self.assertEqual(classify_error(error), FailureCategory.RESOURCE)

    def test_business_category_exists(self):
        """BUSINESS category should exist for future use"""
        self.assertEqual(FailureCategory.BUSINESS.value, "business")
