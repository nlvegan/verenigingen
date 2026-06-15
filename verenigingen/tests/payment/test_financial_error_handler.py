# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Tests for financial_error_handler module.

Covers error classification, user-message generation, severity-based
exception throwing, error logging, summary aggregation, and the module-level
singleton / convenience functions.

Uses EnhancedTestCase because the handler calls frappe.log_error /
frappe.throw / frappe.logger() which require a real Frappe request context.
Only the framework boundary (frappe) is real; no business logic is mocked.
"""

import unittest

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils.financial_error_handler import (
    FinancialError,
    FinancialErrorCategory,
    FinancialErrorHandler,
    FinancialErrorSeverity,
    get_financial_error_handler,
    handle_data_integrity_error,
    handle_permission_error,
    handle_sepa_validation_error,
)


class TestFinancialErrorClassification(EnhancedTestCase):
    """handle_error() classification with user_facing=False (no throw)."""

    def setUp(self):
        super().setUp()
        self.handler = FinancialErrorHandler()

    def test_known_compliance_error_classified(self):
        err = self.handler.handle_error("F1001", user_facing=False)
        self.assertIsInstance(err, FinancialError)
        self.assertEqual(err.code, "F1001")
        self.assertEqual(err.severity, FinancialErrorSeverity.COMPLIANCE)
        self.assertEqual(err.category, FinancialErrorCategory.SEPA_VALIDATION)
        self.assertEqual(err.message, "Invalid IBAN format for creditor account")
        self.assertIn("IBAN", err.suggested_action)
        # recoverable defaults to False (not present in ERROR_CODES dicts)
        self.assertFalse(err.recoverable)

    def test_security_error_classified(self):
        err = self.handler.handle_error("F2001", user_facing=False)
        self.assertEqual(err.severity, FinancialErrorSeverity.SECURITY)
        self.assertEqual(err.category, FinancialErrorCategory.PERMISSION_VIOLATION)

    def test_critical_data_integrity_error(self):
        err = self.handler.handle_error("F3001", user_facing=False)
        self.assertEqual(err.severity, FinancialErrorSeverity.CRITICAL)
        self.assertEqual(err.category, FinancialErrorCategory.DATA_INTEGRITY)

    def test_business_mandate_error(self):
        err = self.handler.handle_error("F4001", user_facing=False)
        self.assertEqual(err.severity, FinancialErrorSeverity.BUSINESS)
        self.assertEqual(err.category, FinancialErrorCategory.MANDATE_VIOLATION)

    def test_warning_configuration_error(self):
        err = self.handler.handle_error("F5002", user_facing=False)
        self.assertEqual(err.severity, FinancialErrorSeverity.WARNING)

    def test_context_is_attached(self):
        ctx = {"member_name": "Jane Doe", "batch_name": "BATCH-001"}
        err = self.handler.handle_error("F1001", context=ctx, user_facing=False)
        self.assertEqual(err.context, ctx)

    def test_none_context_becomes_empty_dict(self):
        err = self.handler.handle_error("F1001", context=None, user_facing=False)
        self.assertEqual(err.context, {})

    def test_user_message_none_when_not_user_facing(self):
        err = self.handler.handle_error("F1001", user_facing=False)
        self.assertIsNone(err.user_message)

    def test_classified_error_stored_in_log(self):
        self.assertEqual(len(self.handler.error_log), 0)
        self.handler.handle_error("F1001", user_facing=False)
        self.assertEqual(len(self.handler.error_log), 1)


class TestUnknownError(EnhancedTestCase):
    """handle_error() with an unrecognised code."""

    def setUp(self):
        super().setUp()
        self.handler = FinancialErrorHandler()

    def test_unknown_code_is_critical_batch(self):
        err = self.handler.handle_error("F9999", user_facing=False)
        self.assertEqual(err.severity, FinancialErrorSeverity.CRITICAL)
        self.assertEqual(err.category, FinancialErrorCategory.BATCH_PROCESSING)
        self.assertEqual(err.code, "F9999")
        self.assertIn("Unknown financial error", err.message)
        self.assertFalse(err.recoverable)

    def test_unknown_has_generic_user_message(self):
        err = self.handler.handle_error("F9999", user_facing=False)
        # Unknown error always carries a user_message regardless of user_facing
        self.assertEqual(err.user_message, "An unexpected financial processing error occurred")

    def test_unknown_error_not_appended_to_log(self):
        # _handle_unknown_error returns early; handle_error does not append it
        self.handler.handle_error("F9999", user_facing=False)
        self.assertEqual(len(self.handler.error_log), 0)

    def test_unknown_error_does_not_throw_even_when_user_facing(self):
        # handle_error returns the unknown error before reaching the throw path
        err = self.handler.handle_error("F9999", user_facing=True)
        self.assertEqual(err.code, "F9999")


class TestUserMessageGeneration(EnhancedTestCase):
    """_generate_user_message() enrichment with context fields."""

    def setUp(self):
        super().setUp()
        self.handler = FinancialErrorHandler()

    def _msg(self, context):
        err = self.handler.handle_error("F1001", context=context, user_facing=False)
        # user_message is None when not user_facing; build directly
        return self.handler._generate_user_message(
            self.handler.ERROR_CODES["F1001"], context
        )

    def test_member_name_appended(self):
        msg = self._msg({"member_name": "Jane"})
        self.assertIn("(Member: Jane)", msg)

    def test_batch_name_appended(self):
        msg = self._msg({"batch_name": "B-1"})
        self.assertIn("(Batch: B-1)", msg)

    def test_invoice_name_appended(self):
        msg = self._msg({"invoice_name": "INV-1"})
        self.assertIn("(Invoice: INV-1)", msg)

    def test_all_context_fields_appended(self):
        msg = self._msg({"member_name": "Jane", "batch_name": "B-1", "invoice_name": "INV-1"})
        self.assertIn("(Member: Jane)", msg)
        self.assertIn("(Batch: B-1)", msg)
        self.assertIn("(Invoice: INV-1)", msg)

    def test_empty_context_returns_base_message(self):
        msg = self._msg({})
        self.assertEqual(msg, "Invalid IBAN format for creditor account")

    def test_user_facing_attaches_message(self):
        # When user_facing=True the message is attached (use WARNING code to avoid throw)
        err = self.handler.handle_error(
            "F5002", context={"batch_name": "B-9"}, user_facing=True
        )
        self.assertIsNotNone(err.user_message)
        self.assertIn("(Batch: B-9)", err.user_message)


class TestExceptionThrowing(EnhancedTestCase):
    """handle_error(user_facing=True) raises per severity."""

    def setUp(self):
        super().setUp()
        self.handler = FinancialErrorHandler()

    def test_compliance_raises_validation_error(self):
        with self.assertRaises(frappe.ValidationError):
            self.handler.handle_error("F1001", user_facing=True)

    def test_critical_raises_validation_error(self):
        with self.assertRaises(frappe.ValidationError):
            self.handler.handle_error("F3001", user_facing=True)

    def test_security_raises_permission_error(self):
        with self.assertRaises(frappe.PermissionError):
            self.handler.handle_error("F2001", user_facing=True)

    def test_business_raises_validation_error(self):
        with self.assertRaises(frappe.ValidationError):
            self.handler.handle_error("F4001", user_facing=True)

    def test_warning_severity_does_not_throw(self):
        # WARNING falls through all branches in _throw_user_exception -> no raise
        err = self.handler.handle_error("F5002", user_facing=True)
        self.assertEqual(err.code, "F5002")
        self.assertEqual(err.severity, FinancialErrorSeverity.WARNING)

    def test_error_logged_before_throw(self):
        # The error is appended to error_log even though a throw follows
        try:
            self.handler.handle_error("F1001", user_facing=True)
        except frappe.ValidationError:
            pass
        self.assertEqual(len(self.handler.error_log), 1)


class TestErrorSummary(EnhancedTestCase):
    """get_error_summary() aggregation."""

    def setUp(self):
        super().setUp()
        self.handler = FinancialErrorHandler()

    def test_empty_summary(self):
        summary = self.handler.get_error_summary()
        self.assertEqual(summary["total_errors"], 0)
        self.assertEqual(summary["by_severity"], {})
        self.assertEqual(summary["by_category"], {})
        self.assertEqual(summary["critical_errors"], [])

    def test_counts_by_severity_and_category(self):
        self.handler.handle_error("F1001", user_facing=False)  # COMPLIANCE / sepa_validation
        self.handler.handle_error("F1002", user_facing=False)  # COMPLIANCE / sepa_validation
        self.handler.handle_error("F2001", user_facing=False)  # SECURITY / permission_violation
        summary = self.handler.get_error_summary()
        self.assertEqual(summary["total_errors"], 3)
        self.assertEqual(summary["by_severity"]["compliance"], 2)
        self.assertEqual(summary["by_severity"]["security"], 1)
        self.assertEqual(summary["by_category"]["sepa_validation"], 2)
        self.assertEqual(summary["by_category"]["permission_violation"], 1)

    def test_critical_errors_tracked(self):
        self.handler.handle_error("F3001", user_facing=False)  # CRITICAL
        self.handler.handle_error("F1001", user_facing=False)  # not critical
        summary = self.handler.get_error_summary()
        self.assertEqual(len(summary["critical_errors"]), 1)
        self.assertEqual(summary["critical_errors"][0]["code"], "F3001")
        self.assertIn("message", summary["critical_errors"][0])
        self.assertIn("context", summary["critical_errors"][0])


class TestSingletonAndConvenience(EnhancedTestCase):
    """Module-level singleton + convenience wrappers (which throw by default)."""

    def test_singleton_is_stable(self):
        a = get_financial_error_handler()
        b = get_financial_error_handler()
        self.assertIs(a, b)

    def test_convenience_sepa_throws_compliance(self):
        with self.assertRaises(frappe.ValidationError):
            handle_sepa_validation_error("F1001")

    def test_convenience_permission_throws_permission_error(self):
        with self.assertRaises(frappe.PermissionError):
            handle_permission_error("F2001")

    def test_convenience_data_integrity_throws(self):
        with self.assertRaises(frappe.ValidationError):
            handle_data_integrity_error("F3001")

    def test_convenience_warning_returns_without_throw(self):
        err = handle_sepa_validation_error("F5002")
        self.assertEqual(err.code, "F5002")


class TestErrorCodeRegistryIntegrity(EnhancedTestCase):
    """The static ERROR_CODES registry is internally consistent."""

    def test_all_codes_have_required_fields(self):
        for code, definition in FinancialErrorHandler.ERROR_CODES.items():
            self.assertIn("message", definition, code)
            self.assertIn("category", definition, code)
            self.assertIn("severity", definition, code)
            self.assertIn("action", definition, code)
            self.assertIsInstance(definition["severity"], FinancialErrorSeverity, code)
            self.assertIsInstance(definition["category"], FinancialErrorCategory, code)


if __name__ == "__main__":
    unittest.main()
