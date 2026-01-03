# File: verenigingen/tests/backend/unit/services/test_approval_notifications.py
"""
Tests to prevent regression of approval notification issues.

Catches:
1. EmailService result uses 'error' key (not 'message') on failure
2. Template names match existing fixtures
3. Member ID generation doesn't use explicit transactions
"""

import inspect
import unittest

import frappe
from frappe.tests.utils import FrappeTestCase


class TestEmailServiceResultFormat(FrappeTestCase):
    """Verify EmailService returns correct keys in result dict."""

    def test_failed_result_uses_error_key_not_message(self):
        """EmailService failure results must use 'error' key, not 'message'."""
        from verenigingen.services.communication.email_service import get_email_service

        email_service = get_email_service()

        # Send with non-existent template to force failure
        result = email_service.send_templated_email(
            template_name="nonexistent_template_xyz",
            recipients=["test@example.com"],
            context={},
        )

        # Verify failure
        self.assertFalse(result.get("success"), "Should fail with nonexistent template")

        # CRITICAL: Error must be in 'error' key, NOT 'message'
        self.assertIsNotNone(
            result.get("error"),
            "Failed result must have 'error' key with error message",
        )


class TestApprovalTemplatesExist(FrappeTestCase):
    """Verify approval email templates exist in the system."""

    def test_termination_approval_template_exists(self):
        """Termination Approval Required template must exist."""
        exists = frappe.db.exists("Email Template", "Termination Approval Required")
        self.assertTrue(exists, "Email template 'Termination Approval Required' must exist")

    def test_termination_execution_template_exists(self):
        """Termination Execution Notice template must exist."""
        exists = frappe.db.exists("Email Template", "Termination Execution Notice")
        self.assertTrue(exists, "Email template 'Termination Execution Notice' must exist")

    def test_amendment_approved_template_exists(self):
        """amendment_approved template must exist."""
        exists = frappe.db.exists("Email Template", "amendment_approved")
        self.assertTrue(exists, "Email template 'amendment_approved' must exist")

    def test_amendment_rejected_template_exists(self):
        """amendment_rejected template must exist."""
        exists = frappe.db.exists("Email Template", "amendment_rejected")
        self.assertTrue(exists, "Email template 'amendment_rejected' must exist")


class TestMemberIDGenerationNoExplicitTransaction(FrappeTestCase):
    """Verify member ID generation doesn't cause transaction errors."""

    def test_member_id_generation_works(self):
        """Member ID generation must work without transaction errors."""
        from verenigingen.verenigingen.doctype.member.member_id_manager import MemberIDManager

        member_id = MemberIDManager.get_next_member_id()

        self.assertIsNotNone(member_id, "Should return a member ID")
        self.assertIsInstance(member_id, int, "Member ID should be an integer")
        self.assertGreater(member_id, 0, "Member ID should be positive")

    def test_member_id_manager_has_no_explicit_begin(self):
        """Verify MemberIDManager code doesn't call frappe.db.begin()."""
        from verenigingen.verenigingen.doctype.member.member_id_manager import MemberIDManager

        source = inspect.getsource(MemberIDManager.get_next_member_id)

        # Filter out comments and docstrings - look for actual code calls
        # Real calls would be indented: "    frappe.db.begin()"
        # or at start of line in single-line context
        import re

        # Pattern matches actual function calls, not mentions in comments/docstrings
        begin_call_pattern = r"^\s*frappe\.db\.begin\(\)"
        begin_matches = re.findall(begin_call_pattern, source, re.MULTILINE)

        self.assertEqual(
            len(begin_matches),
            0,
            "get_next_member_id must NOT call frappe.db.begin() - causes implicit commit errors",
        )


class TestApprovalServiceErrorHandling(FrappeTestCase):
    """Verify approval services use correct error key from EmailService."""

    def test_termination_service_uses_error_key(self):
        """TerminationApprovalService must use result.get('error')."""
        from verenigingen.services.approval.termination_approval_service import (
            TerminationApprovalService,
        )

        source = inspect.getsource(TerminationApprovalService.send_approval_notification)
        self.assertIn("result.get('error')", source)
        self.assertNotIn("result.get('message')", source)

    def test_contribution_service_uses_error_key(self):
        """ContributionAmendmentApprovalService must use result.get('error')."""
        from verenigingen.services.approval.contribution_amendment_approval_service import (
            ContributionAmendmentApprovalService,
        )

        source = inspect.getsource(ContributionAmendmentApprovalService.send_approval_notification)
        self.assertIn("result.get('error')", source)
        self.assertNotIn("result.get('message')", source)
