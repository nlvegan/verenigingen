"""
Tests for MollieErrorHandler
Tests error handling, logging, and user notification functionality
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.core.error_handler import MollieErrorHandler


class TestMollieErrorHandler(FrappeTestCase):
    """Test suite for MollieErrorHandler"""

    def setUp(self):
        """Set up test fixtures"""
        self.handler = MollieErrorHandler()
        self.mock_audit_trail = MagicMock()

    def test_error_templates_structure(self):
        """Test that all error templates have required fields"""
        required_fields = ["message", "user_message", "severity", "log_to_error_log", "notify_user"]

        for error_type, template in MollieErrorHandler.ERROR_TEMPLATES.items():
            for field in required_fields:
                self.assertIn(
                    field,
                    template,
                    f"Error template '{error_type}' missing required field '{field}'",
                )

            # Validate severity values
            self.assertIn(
                template["severity"],
                ["warning", "error", "critical"],
                f"Error template '{error_type}' has invalid severity '{template['severity']}'",
            )

            # Validate boolean fields
            self.assertIsInstance(
                template["log_to_error_log"],
                bool,
                f"Error template '{error_type}' log_to_error_log should be boolean",
            )
            self.assertIsInstance(
                template["notify_user"],
                bool,
                f"Error template '{error_type}' notify_user should be boolean",
            )

    def test_get_error_template(self):
        """Test getting error template"""
        # Valid error type
        template = self.handler.get_error_template("api_connection")
        self.assertIsNotNone(template)
        self.assertEqual(template["severity"], "error")

        # Invalid error type
        template = self.handler.get_error_template("nonexistent_type")
        self.assertIsNone(template)

    def test_get_available_error_types(self):
        """Test getting list of available error types"""
        error_types = self.handler.get_available_error_types()

        self.assertIsInstance(error_types, list)
        self.assertGreater(len(error_types), 0)
        self.assertIn("api_connection", error_types)
        self.assertIn("configuration_missing", error_types)

    @patch("frappe.log_error")
    @patch("frappe.msgprint")
    def test_handle_error_logs_to_error_log(self, mock_msgprint, mock_log_error):
        """Test that errors are logged to error log when configured"""
        error = Exception("Test connection error")

        with self.assertRaises(Exception):
            self.handler.handle_error(
                error_type="api_connection",
                error=error,
                context={"endpoint": "/settlements"},
            )

        # Verify error log was called
        mock_log_error.assert_called_once()
        call_kwargs = mock_log_error.call_args[1]
        self.assertIn("Mollie api_connection", call_kwargs["title"])
        self.assertIn("Test connection error", call_kwargs["message"])

    @patch("frappe.log_error")
    @patch("frappe.msgprint")
    def test_handle_error_skips_error_log_when_disabled(self, mock_msgprint, mock_log_error):
        """Test that error log is skipped when log_to_error_log=False"""
        error = Exception("Rate limit exceeded")

        with self.assertRaises(Exception):
            self.handler.handle_error(
                error_type="api_rate_limit",  # This has log_to_error_log=False
                error=error,
            )

        # Verify error log was NOT called
        mock_log_error.assert_not_called()

        # But msgprint should still be called
        mock_msgprint.assert_called_once()

    @patch("frappe.msgprint")
    def test_handle_error_notifies_user(self, mock_msgprint):
        """Test that user is notified when notify_user=True"""
        error = Exception("Configuration missing")

        with self.assertRaises(Exception):
            self.handler.handle_error(
                error_type="configuration_missing",
                error=error,
                context={"field": "api_key"},
            )

        # Verify msgprint was called
        mock_msgprint.assert_called_once()
        call_args = mock_msgprint.call_args
        self.assertIn("api_key", str(call_args))

    @patch("frappe.log_error")
    def test_handle_error_with_audit_trail(self, mock_log_error):
        """Test that errors are logged to audit trail when provided"""
        error = Exception("Test error")

        with self.assertRaises(Exception):
            self.handler.handle_error(
                error_type="api_connection",
                error=error,
                context={"operation": "test"},
                audit_trail=self.mock_audit_trail,
            )

        # Verify audit trail was called
        self.mock_audit_trail.log_event.assert_called_once()
        call_args = self.mock_audit_trail.log_event.call_args[0]
        call_kwargs = self.mock_audit_trail.log_event.call_args[1]

        # Check event type and severity
        from verenigingen.verenigingen_payments.core.compliance.audit_trail import (
            AuditEventType,
            AuditSeverity,
        )

        self.assertEqual(call_args[0], AuditEventType.ERROR_OCCURRED)
        self.assertEqual(call_args[1], AuditSeverity.ERROR)

        # Check details
        self.assertIn("error_type", call_kwargs["details"])
        self.assertEqual(call_kwargs["details"]["error_type"], "api_connection")

    def test_handle_error_reraises_exception(self):
        """Test that original exception is re-raised"""
        original_error = ValueError("Test validation error")

        with self.assertRaises(ValueError) as context:
            self.handler.handle_error(
                error_type="data_validation",
                error=original_error,
            )

        # Verify it's the same exception
        self.assertIs(context.exception, original_error)

    @patch("frappe.log_error")
    def test_handle_error_with_severity_override(self, mock_log_error):
        """Test that severity can be overridden"""
        error = Exception("Test error")

        with self.assertRaises(Exception):
            self.handler.handle_error(
                error_type="api_connection",  # Default severity: "error"
                error=error,
                severity_override="critical",  # Override to critical
                audit_trail=self.mock_audit_trail,
            )

        # Verify audit trail received critical severity
        from verenigingen.verenigingen_payments.core.compliance.audit_trail import AuditSeverity

        call_args = self.mock_audit_trail.log_event.call_args[0]
        self.assertEqual(call_args[1], AuditSeverity.CRITICAL)

    def test_handle_error_with_unknown_error_type(self):
        """Test that unknown error types fallback to operation_failed"""
        error = Exception("Test error")

        with patch("frappe.log_error") as mock_log_error:
            with self.assertRaises(Exception):
                self.handler.handle_error(
                    error_type="nonexistent_error_type",
                    error=error,
                )

            # Should still log error with fallback type
            mock_log_error.assert_called_once()
            call_kwargs = mock_log_error.call_args[1]
            self.assertIn("operation_failed", call_kwargs["title"])

    def test_handle_error_with_missing_context_keys(self):
        """Test graceful handling of missing context keys in templates"""
        error = Exception("Test error")

        # Template expects {resource_type} and {resource_id} in context
        # We provide neither - should handle gracefully
        with patch("frappe.log_error"):
            with self.assertRaises(Exception):
                self.handler.handle_error(
                    error_type="resource_not_found",
                    error=error,
                    context={},  # Missing required context keys
                )
            # Should not crash, error should be logged with fallback formatting

    def test_wrap_operation_success(self):
        """Test wrap_operation with successful operation"""

        def successful_operation():
            return "success_result"

        result = self.handler.wrap_operation(
            operation_name="test_operation",
            operation_callable=successful_operation,
        )

        self.assertEqual(result, "success_result")

    def test_wrap_operation_failure_raises_by_default(self):
        """Test wrap_operation raises exception by default"""

        def failing_operation():
            raise ValueError("Operation failed")

        with patch("frappe.log_error"):
            with self.assertRaises(ValueError):
                self.handler.wrap_operation(
                    operation_name="test_operation",
                    operation_callable=failing_operation,
                    error_type="operation_failed",
                )

    def test_wrap_operation_failure_with_suppression(self):
        """Test wrap_operation returns fallback when suppress_errors=True"""

        def failing_operation():
            raise ValueError("Operation failed")

        with patch("frappe.log_error"):
            result = self.handler.wrap_operation(
                operation_name="test_operation",
                operation_callable=failing_operation,
                error_type="operation_failed",
                fallback_value=[],
                suppress_errors=True,
            )

        self.assertEqual(result, [])

    def test_wrap_operation_adds_operation_to_context(self):
        """Test that wrap_operation adds operation name to context"""

        def failing_operation():
            raise ValueError("Operation failed")

        with patch("frappe.log_error") as mock_log_error:
            with self.assertRaises(ValueError):
                self.handler.wrap_operation(
                    operation_name="get_settlement",
                    operation_callable=failing_operation,
                    error_type="settlement_processing",
                    context={"settlement_id": "stl_123"},
                )

            # Verify operation name was added to context in error message
            call_kwargs = mock_log_error.call_args[1]
            self.assertIn("get_settlement", call_kwargs["message"])

    def test_wrap_operation_with_audit_trail(self):
        """Test wrap_operation logs to audit trail"""

        def failing_operation():
            raise ValueError("Operation failed")

        with patch("frappe.log_error"):
            with self.assertRaises(ValueError):
                self.handler.wrap_operation(
                    operation_name="test_operation",
                    operation_callable=failing_operation,
                    error_type="operation_failed",
                    audit_trail=self.mock_audit_trail,
                )

        # Verify audit trail was called
        self.mock_audit_trail.log_event.assert_called_once()

    def test_wrap_operation_with_lambda(self):
        """Test wrap_operation works with lambda functions"""
        test_data = {"key": "value"}

        result = self.handler.wrap_operation(
            operation_name="lambda_test",
            operation_callable=lambda: test_data,
        )

        self.assertEqual(result, test_data)

    def test_critical_error_severity(self):
        """Test that critical errors are handled with appropriate severity"""
        error = Exception("Authentication failed")

        with patch("frappe.log_error"):
            with patch("frappe.msgprint") as mock_msgprint:
                with self.assertRaises(Exception):
                    self.handler.handle_error(
                        error_type="api_authentication",
                        error=error,
                        audit_trail=self.mock_audit_trail,
                    )

                # Verify msgprint was called with red indicator
                call_kwargs = mock_msgprint.call_args[1]
                self.assertEqual(call_kwargs["indicator"], "red")

    def test_warning_error_severity(self):
        """Test that warning errors are handled with appropriate severity"""
        error = Exception("Rate limit")

        with patch("frappe.msgprint") as mock_msgprint:
            with self.assertRaises(Exception):
                self.handler.handle_error(
                    error_type="api_rate_limit",
                    error=error,
                    audit_trail=self.mock_audit_trail,
                )

            # Verify msgprint was called with orange indicator
            call_kwargs = mock_msgprint.call_args[1]
            self.assertEqual(call_kwargs["indicator"], "orange")

    def test_error_handler_graceful_audit_trail_failure(self):
        """Test that audit trail failures don't prevent error handling"""
        error = Exception("Test error")

        # Mock audit trail that raises exception
        failing_audit_trail = MagicMock()
        failing_audit_trail.log_event.side_effect = Exception("Audit trail failed")

        with patch("frappe.log_error"):
            with self.assertRaises(Exception) as context:
                self.handler.handle_error(
                    error_type="api_connection",
                    error=error,
                    audit_trail=failing_audit_trail,
                )

            # Should still raise original exception, not audit trail exception
            self.assertIs(context.exception, error)

    def test_error_handler_graceful_msgprint_failure(self):
        """Test that msgprint failures don't prevent error handling"""
        error = Exception("Test error")

        with patch("frappe.log_error"):
            with patch("frappe.msgprint", side_effect=Exception("msgprint failed")):
                with self.assertRaises(Exception) as context:
                    self.handler.handle_error(
                        error_type="api_connection",
                        error=error,
                    )

                # Should still raise original exception
                self.assertIs(context.exception, error)

    def test_error_types_coverage(self):
        """Test that we have error types for common scenarios"""
        required_error_types = [
            "api_connection",
            "api_authentication",
            "api_rate_limit",
            "api_validation",
            "configuration_missing",
            "resource_not_found",
            "settlement_processing",
            "balance_operation",
            "payment_operation",
        ]

        available_types = self.handler.get_available_error_types()

        for required_type in required_error_types:
            self.assertIn(
                required_type,
                available_types,
                f"Required error type '{required_type}' not found in ERROR_TEMPLATES",
            )

    def test_context_preservation(self):
        """Test that error context is preserved in logging"""
        error = Exception("Test error")
        context = {
            "settlement_id": "stl_123",
            "operation": "reconcile",
            "amount": 100.50,
        }

        with patch("frappe.log_error") as mock_log_error:
            with self.assertRaises(Exception):
                self.handler.handle_error(
                    error_type="settlement_processing",
                    error=error,
                    context=context,
                )

            # Verify context is in error log
            call_kwargs = mock_log_error.call_args[1]
            message = call_kwargs["message"]
            self.assertIn("stl_123", message)
            self.assertIn("reconcile", message)
