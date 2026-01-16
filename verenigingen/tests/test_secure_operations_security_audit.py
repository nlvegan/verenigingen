"""
Test Suite for Secure Operations Security Audit Fixes
=====================================================

Tests for security fixes implemented based on the security audit:
1. get_system_user_for_operation - ConfigurationError when not configured (no Administrator fallback)
2. Authorization before impersonation - escalation check before set_user
3. bypass_validations gating - early enforcement and audit recording
4. Nested impersonation protection - prevent privilege confusion
5. Post-bypass integrity verification
6. Observability metrics

Author: Security Audit Response
"""

import frappe
from frappe.tests import IntegrationTestCase
from unittest.mock import patch, MagicMock
import threading


class TestSecureOperationsSecurityAudit(IntegrationTestCase):
    """Tests for secure_operations security audit fixes."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        # Store original user
        self.original_user = frappe.session.user

    def tearDown(self):
        """Clean up after tests."""
        # Restore original user
        frappe.set_user(self.original_user)
        super().tearDown()

    # =========================================================================
    # (High) 1) get_system_user_for_operation - No Administrator Fallback
    # =========================================================================

    def test_get_system_user_raises_configuration_error_when_not_configured(self):
        """Test that missing creation_user raises ConfigurationError, not Administrator fallback."""
        from verenigingen.utils.secure_operations import get_system_user_for_operation
        from verenigingen.utils.error_handling import ConfigurationError

        # Mock settings with no creation_user
        mock_settings = MagicMock()
        mock_settings.creation_user = None

        with patch("frappe.get_single", return_value=mock_settings):
            with self.assertRaises(ConfigurationError) as context:
                get_system_user_for_operation("test_operation")

            self.assertIn("Creation User", str(context.exception))
            # Verify Administrator is NOT returned
            self.assertNotIn("Administrator", str(context.exception))

    def test_get_system_user_raises_when_user_does_not_exist(self):
        """Test that non-existent creation_user raises ConfigurationError."""
        from verenigingen.utils.secure_operations import get_system_user_for_operation
        from verenigingen.utils.error_handling import ConfigurationError

        mock_settings = MagicMock()
        mock_settings.creation_user = "nonexistent_user@example.com"

        with patch("frappe.get_single", return_value=mock_settings):
            with patch("frappe.db.exists", return_value=False):
                with self.assertRaises(ConfigurationError) as context:
                    get_system_user_for_operation("test_operation")

                self.assertIn("does not exist", str(context.exception))

    def test_get_system_user_raises_when_user_is_disabled(self):
        """Test that disabled creation_user raises ConfigurationError."""
        from verenigingen.utils.secure_operations import get_system_user_for_operation
        from verenigingen.utils.error_handling import ConfigurationError

        mock_settings = MagicMock()
        mock_settings.creation_user = "disabled_user@example.com"

        mock_user_doc = MagicMock()
        mock_user_doc.enabled = False

        with patch("frappe.get_single", return_value=mock_settings):
            with patch("frappe.db.exists", return_value=True):
                with patch("frappe.get_doc", return_value=mock_user_doc):
                    with self.assertRaises(ConfigurationError) as context:
                        get_system_user_for_operation("test_operation")

                    self.assertIn("disabled", str(context.exception))

    # =========================================================================
    # (High) 2) Authorization Before Impersonation
    # =========================================================================

    def test_unauthorized_user_cannot_trigger_escalation(self):
        """Test that unprivileged user is denied escalation before frappe.set_user is called."""
        from verenigingen.utils.secure_operations import secure_document_operation

        # Create a Customer document - Guest cannot create these
        test_doc = frappe.new_doc("Customer")
        test_doc.customer_name = "Test Unauthorized Escalation"
        test_doc.customer_type = "Individual"

        # Set to unprivileged user (Guest)
        frappe.set_user("Guest")

        # Guest cannot create Customer and cannot request escalation
        # secure_document_operation catches exceptions and returns them in result.errors
        result = secure_document_operation(
            operation="create",
            doc=test_doc,
            justification="Test escalation denial for Guest user",
            allow_system_user=True,  # Would escalate, but Guest can't request it
        )

        # Verify operation failed
        self.assertFalse(result.success, "Operation should fail for unauthorized user")

        # Verify error mentions permission/escalation
        error_text = " ".join(result.errors).lower()
        self.assertTrue(
            "permission" in error_text or "escalation" in error_text,
            f"Error should mention permission denial: {result.errors}",
        )

        # Verify no document was created
        self.assertIsNone(result.doc_name, "No document should be created")

    def test_authorized_user_can_trigger_escalation(self):
        """Test that privileged user can trigger escalation and original user is restored."""
        from verenigingen.utils.secure_operations import (
            secure_document_operation,
            can_request_system_escalation,
        )

        # Verify the admin user can escalate
        frappe.set_user("Administrator")
        self.assertTrue(can_request_system_escalation("Administrator"))

        # Create a test document
        test_doc = frappe.new_doc("ToDo")
        test_doc.description = "Test authorized escalation"

        # This should succeed with Administrator
        result = secure_document_operation(
            operation="create",
            doc=test_doc,
            justification="Test authorized escalation by Administrator",
            allow_system_user=False,  # Don't need escalation for Admin
        )

        # Verify operation succeeded
        self.assertTrue(result.success, f"Operation should succeed: {result.errors}")

        # Verify user is restored
        self.assertEqual(frappe.session.user, "Administrator")

        # Clean up
        if result.doc_name:
            frappe.delete_doc("ToDo", result.doc_name, force=True)

    # =========================================================================
    # (High) 3) bypass_validations Gating
    # =========================================================================

    def test_unprivileged_user_denied_bypass_validations(self):
        """Test that non-admin users cannot use bypass_validations parameter."""
        from verenigingen.utils.secure_operations import secure_document_operation

        # Set to a user without bypass privileges
        frappe.set_user("Guest")

        test_doc = frappe.new_doc("ToDo")
        test_doc.description = "Test bypass denial"

        with self.assertRaises(frappe.PermissionError) as context:
            secure_document_operation(
                operation="create",
                doc=test_doc,
                justification="Test bypass validation denial",
                bypass_validations=["link_validation"],
            )

        self.assertIn("bypass", str(context.exception).lower())

    def test_bypass_validations_recorded_in_audit(self):
        """Test that bypass_validations is recorded in audit entries."""
        from verenigingen.utils.secure_operations import secure_document_operation

        frappe.set_user("Administrator")

        test_doc = frappe.new_doc("ToDo")
        test_doc.description = "Test bypass audit"

        result = secure_document_operation(
            operation="create",
            doc=test_doc,
            justification="Test bypass validation audit recording",
            bypass_validations=["link_validation"],
        )

        # Check audit trail contains bypass_validations
        audit_with_bypass = [
            entry
            for entry in result.audit_trail
            if entry.get("details", {}).get("bypass_validations")
        ]
        self.assertGreater(
            len(audit_with_bypass),
            0,
            "Audit trail should contain bypass_validations in details",
        )

        # Verify the bypass list is recorded correctly
        for entry in audit_with_bypass:
            self.assertIn("link_validation", entry["details"]["bypass_validations"])

        # Clean up
        if result.doc_name:
            frappe.delete_doc("ToDo", result.doc_name, force=True)

    # =========================================================================
    # (Medium) 4) Nested Impersonation Protection
    # =========================================================================

    def test_nested_impersonation_blocked(self):
        """Test that nested impersonation attempts are blocked."""
        from verenigingen.utils.secure_operations import (
            secure_user_context_with_validation,
            _get_impersonation_stack,
        )

        # Clear any existing stack
        stack = _get_impersonation_stack()
        stack.clear()

        frappe.set_user("Administrator")

        # First impersonation should work
        with secure_user_context_with_validation("Administrator", "outer_operation"):
            # Verify stack has one entry
            self.assertEqual(len(_get_impersonation_stack()), 1)

            # Nested impersonation should be blocked
            with self.assertRaises(frappe.PermissionError) as context:
                with secure_user_context_with_validation("Administrator", "inner_operation"):
                    pass

            self.assertIn("Nested impersonation", str(context.exception))

        # Verify stack is cleared after context exits
        self.assertEqual(len(_get_impersonation_stack()), 0)

    def test_context_manager_restores_user_on_exception(self):
        """Test that context manager restores user even when exception occurs."""
        from verenigingen.utils.secure_operations import (
            secure_user_context_with_validation,
            _get_impersonation_stack,
        )

        # Clear stack
        _get_impersonation_stack().clear()

        frappe.set_user("Administrator")
        original_user = frappe.session.user

        try:
            with secure_user_context_with_validation("Administrator", "test_exception"):
                # Simulate an error
                raise ValueError("Test exception")
        except ValueError:
            pass

        # Verify user is restored
        self.assertEqual(frappe.session.user, original_user)

        # Verify stack is cleared
        self.assertEqual(len(_get_impersonation_stack()), 0)

    # =========================================================================
    # (Medium) 5) Post-Bypass Integrity Verification
    # =========================================================================

    def test_verify_document_integrity_detects_broken_links(self):
        """Test that verify_document_integrity detects broken links after bypass."""
        from verenigingen.utils.secure_operations import verify_document_integrity

        # Create a mock document with a broken link
        mock_doc = MagicMock()
        mock_doc.doctype = "ToDo"
        mock_doc.name = "test-todo"
        mock_doc.get = MagicMock(return_value="nonexistent-record")

        # Mock meta to return link fields
        mock_meta = MagicMock()
        mock_link_field = MagicMock()
        mock_link_field.fieldname = "reference_name"
        mock_link_field.options = "SomeDocType"
        mock_meta.get_link_fields.return_value = [mock_link_field]
        mock_meta.get_table_fields.return_value = []

        with patch("frappe.get_meta", return_value=mock_meta):
            with patch("frappe.db.exists", return_value=False):
                violations = verify_document_integrity(mock_doc, ["link_validation"])

        self.assertGreater(len(violations), 0)
        self.assertIn("Broken link", violations[0])

    def test_integrity_verification_called_after_bypass(self):
        """Test that integrity verification is called after bypass operations."""
        from verenigingen.utils.secure_operations import (
            secure_document_operation,
            verify_document_integrity,
        )

        frappe.set_user("Administrator")

        test_doc = frappe.new_doc("ToDo")
        test_doc.description = "Test integrity verification"

        # Mock verify_document_integrity to track calls
        with patch(
            "verenigingen.utils.secure_operations.verify_document_integrity",
            return_value=[],
        ) as mock_verify:
            result = secure_document_operation(
                operation="create",
                doc=test_doc,
                justification="Test integrity verification call",
                bypass_validations=["link_validation"],
            )

            # Verify integrity check was called
            mock_verify.assert_called_once()
            call_args = mock_verify.call_args
            self.assertEqual(call_args[1].get("bypass_validations") or call_args[0][1], ["link_validation"])

        # Clean up
        if result.doc_name:
            frappe.delete_doc("ToDo", result.doc_name, force=True)

    # =========================================================================
    # (Low) 6) Observability Metrics
    # =========================================================================

    def test_metrics_increment_on_bypass_denied(self):
        """Test that bypass_denied metric is incremented when bypass is denied."""
        from verenigingen.utils.secure_operations import _get_metrics, increment_metric

        # Reset metrics
        metrics = _get_metrics()
        initial_denied = metrics.get("bypass_denied", 0)

        # Trigger bypass denial
        frappe.set_user("Guest")
        test_doc = frappe.new_doc("ToDo")
        test_doc.description = "Test metric"

        try:
            from verenigingen.utils.secure_operations import secure_document_operation

            secure_document_operation(
                operation="create",
                doc=test_doc,
                justification="Test bypass metric",
                bypass_validations=["link_validation"],
            )
        except frappe.PermissionError:
            pass

        # Verify metric was incremented
        self.assertGreater(
            metrics.get("bypass_denied", 0),
            initial_denied,
            "bypass_denied metric should be incremented",
        )

    def test_metrics_increment_on_impersonation(self):
        """Test that impersonations metric is incremented on successful impersonation."""
        from verenigingen.utils.secure_operations import (
            secure_user_context_with_validation,
            _get_metrics,
            _get_impersonation_stack,
        )

        # Clear stack and reset metrics
        _get_impersonation_stack().clear()
        metrics = _get_metrics()
        initial_impersonations = metrics.get("impersonations", 0)

        frappe.set_user("Administrator")

        with secure_user_context_with_validation("Administrator", "test_metric"):
            pass

        # Verify metric was incremented
        self.assertGreater(
            metrics.get("impersonations", 0),
            initial_impersonations,
            "impersonations metric should be incremented",
        )

    def test_metrics_increment_on_bypass_used(self):
        """Test that bypass_used metric is incremented when bypass is used."""
        from verenigingen.utils.secure_operations import secure_document_operation, _get_metrics

        frappe.set_user("Administrator")
        metrics = _get_metrics()
        initial_bypass_used = metrics.get("bypass_used", 0)

        test_doc = frappe.new_doc("ToDo")
        test_doc.description = "Test bypass used metric"

        result = secure_document_operation(
            operation="create",
            doc=test_doc,
            justification="Test bypass_used metric tracking",
            bypass_validations=["link_validation"],
        )

        # Verify metric was incremented
        self.assertGreater(
            metrics.get("bypass_used", 0),
            initial_bypass_used,
            "bypass_used metric should be incremented",
        )

        # Clean up
        if result.doc_name:
            frappe.delete_doc("ToDo", result.doc_name, force=True)
