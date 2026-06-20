# File: verenigingen/tests/backend/unit/services/test_approval_notifications.py
"""
Tests to prevent regression of approval notification issues.

Catches:
1. EmailService result uses 'error' key (not 'message') on failure
2. Template names match existing fixtures
3. Member ID generation doesn't use explicit transactions
"""

import inspect
import re

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.fixtures.singleton_backup import SingletonBackupMixin


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
        self.assertFalse(result.success, "Should fail with nonexistent template")

        # CRITICAL: Error must be in 'error_message' attribute, NOT 'message'
        self.assertIsNotNone(
            result.error_message,
            "Failed result must have 'error_message' with error description",
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

    def test_termination_rejected_template_exists(self):
        """termination_rejected template must exist."""
        exists = frappe.db.exists("Email Template", "termination_rejected")
        self.assertTrue(exists, "Email template 'termination_rejected' must exist")


class TestMemberIDGenerationNoExplicitTransaction(SingletonBackupMixin, FrappeTestCase):
    """Verify member ID generation doesn't cause transaction errors.

    Uses SingletonBackupMixin to ensure Verenigingen Settings exists and is
    restored after tests. This allows testing the real code path rather than
    the fallback path that activates when the singleton is missing.
    """

    protected_singletons = ["Verenigingen Settings"]

    @classmethod
    def setUpClass(cls):
        """Ensure Verenigingen Settings singleton exists for tests."""
        super().setUpClass()

        # Create singleton if it doesn't exist (e.g., in isolated test database)
        if not frappe.db.exists("Verenigingen Settings", "Verenigingen Settings"):
            doc = frappe.new_doc("Verenigingen Settings")
            doc.member_id_start = 1000
            doc.insert(ignore_permissions=True)
            frappe.db.commit()
            cls._created_singleton = True
        else:
            cls._created_singleton = False

    @classmethod
    def tearDownClass(cls):
        """Clean up singleton if we created it."""
        if getattr(cls, "_created_singleton", False):
            frappe.db.delete("Verenigingen Settings", "Verenigingen Settings")
            frappe.db.commit()
        super().tearDownClass()

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

        # Pattern matches actual function calls, not mentions in comments/docstrings
        begin_call_pattern = r"^\s*frappe\.db\.begin\(\)"
        begin_matches = re.findall(begin_call_pattern, source, re.MULTILINE)

        self.assertEqual(
            len(begin_matches),
            0,
            "get_next_member_id must NOT call frappe.db.begin() - causes implicit commit errors",
        )


class TestTerminationTemplatesRender(FrappeTestCase):
    """Render the termination email templates with the REAL service-built context.

    Regression: the senders provided a flattened context (member_name, request_id, ...)
    while the templates reference `member`/`doc` objects (and a field `reason_for_termination`
    that does not exist), so every render raised jinja UndefinedError, swallowed as
    "Termination Approved Email Error" / "Termination Approval Email Error". These tests
    render the actual DB Email Template with the context each sender builds and assert it
    does not raise.
    """

    def _make_request_and_member(self):
        h = frappe.generate_hash(length=6)
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Notice",
                "last_name": f"Render{h}",
                "email": f"notice.render.{h}@test.invalid",
                "status": "Active",
            }
        ).insert(ignore_permissions=True)
        self.addCleanup(lambda: frappe.delete_doc("Member", member.name, force=True, ignore_permissions=True))
        request = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": member.name,
                "termination_type": "Policy Violation",
                "termination_reason": "Render-test reason",
                "disciplinary_documentation": "<p>doc</p>",
                "secondary_approver": "Administrator",
                "requested_by": "Administrator",
            }
        ).insert(ignore_permissions=True)
        self.addCleanup(
            lambda: frappe.delete_doc(
                "Membership Termination Request", request.name, force=True, ignore_permissions=True
            )
        )
        return request, member

    def _render(self, template_name, context):
        tpl = frappe.get_doc("Email Template", template_name)
        body = tpl.response_html or tpl.response
        # Raises jinja UndefinedError if the context is missing a referenced variable.
        frappe.render_template(body, context)
        frappe.render_template(tpl.subject, context)

    def test_pending_approval_template_renders(self):
        from verenigingen.services.approval.termination_approval_service import TerminationApprovalService

        request, member = self._make_request_and_member()
        svc = TerminationApprovalService(request)
        self._render("Termination Approval Required", svc._pending_approval_context(member))

    def test_execution_notice_template_renders(self):
        from verenigingen.services.approval.termination_approval_service import TerminationApprovalService

        request, member = self._make_request_and_member()
        request.termination_date = frappe.utils.today()
        svc = TerminationApprovalService(request)
        self._render("Termination Execution Notice", svc._execution_notice_context(member))


class TestApprovalServiceErrorHandling(FrappeTestCase):
    """Verify approval services use correct error key from EmailService."""

    def test_termination_service_uses_error_message_attribute(self):
        """TerminationApprovalService must use result.error_message."""
        from verenigingen.services.approval.termination_approval_service import (
            TerminationApprovalService,
        )

        source = inspect.getsource(TerminationApprovalService.send_approval_notification)
        self.assertIn("result.error_message", source)
        self.assertNotIn("result.get('message')", source)

    def test_contribution_service_uses_error_message_attribute(self):
        """ContributionAmendmentApprovalService must use result.error_message."""
        from verenigingen.services.approval.contribution_amendment_approval_service import (
            ContributionAmendmentApprovalService,
        )

        source = inspect.getsource(ContributionAmendmentApprovalService.send_approval_notification)
        self.assertIn("result.error_message", source)
        self.assertNotIn("result.get('message')", source)
