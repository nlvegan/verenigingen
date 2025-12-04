# File: verenigingen/tests/services/test_termination_approval_service.py
"""
Unit tests for TerminationApprovalService

Tests the approval workflow service in isolation with comprehensive
coverage of business rules, validation, and state transitions.
"""

import frappe
from frappe.utils import now, today, add_days
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.services.approval import TerminationApprovalService


class TestTerminationApprovalService(EnhancedTestCase):
    """Test suite for TerminationApprovalService"""

    def setUp(self):
        """Set up test data before each test"""
        super().setUp()

        # Create a test member
        self.test_member = self.create_test_member(
            first_name="Approval",
            last_name="Test",
            email="approval.test@verenigingen.test",
            birth_date="1990-01-01"
        )

        # Create a secondary approver user with appropriate roles
        if not frappe.db.exists("User", "approver.test@verenigingen.test"):
            self._create_test_user(
                email="approver.test@verenigingen.test",
                first_name="Test",
                last_name="Approver",
                enabled=1,
                roles=["Verenigingen Administrator"]
            )

    def tearDown(self):
        """Clean up test data"""
        # Clean up test users
        if frappe.db.exists("User", "approver.test@verenigingen.test"):
            frappe.delete_doc("User", "approver.test@verenigingen.test", force=True)

        super().tearDown()

    def _create_termination_request(self, termination_type="Voluntary", **kwargs):
        """Helper to create a termination request"""
        doc = frappe.get_doc({
            "doctype": "Membership Termination Request",
            "member": self.test_member.name,
            "termination_type": termination_type,
            "termination_reason": kwargs.get("termination_reason", "Test reason"),
            "requested_by": frappe.session.user,
            "request_date": today(),
            **kwargs
        })
        doc.insert()
        return doc

    def _create_test_user(self, email, first_name, last_name, enabled=1, roles=None):
        """
        Helper factory method for creating test users with proper permissions.

        Permission bypass is allowed in factory methods for test data creation.
        """
        if frappe.db.exists("User", email):
            frappe.delete_doc("User", email, force=True)

        user = frappe.get_doc({
            "doctype": "User",
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "enabled": enabled,
            "send_welcome_email": 0
        })
        user.insert(ignore_permissions=True)  # OK in factory method

        if roles:
            for role in roles:
                user.add_roles(role)

        return user

    # ========================================================================
    # Approval Requirements Tests
    # ========================================================================

    def test_voluntary_termination_no_secondary_approval(self):
        """Voluntary terminations should not require secondary approval"""
        request = self._create_termination_request(termination_type="Voluntary")
        service = TerminationApprovalService(request)

        self.assertFalse(service.requires_secondary_approval())

        service.set_approval_requirements()
        self.assertEqual(request.requires_secondary_approval, 0)

    def test_disciplinary_termination_requires_secondary_approval(self):
        """Disciplinary terminations should require secondary approval"""
        disciplinary_types = ["Policy Violation", "Disciplinary Action", "Expulsion"]

        for term_type in disciplinary_types:
            with self.subTest(termination_type=term_type):
                request = self._create_termination_request(
                    termination_type=term_type,
                    disciplinary_documentation="Test documentation"
                )
                service = TerminationApprovalService(request)

                self.assertTrue(service.requires_secondary_approval())

                service.set_approval_requirements()
                self.assertEqual(request.requires_secondary_approval, 1)

    def test_nonpayment_termination_no_secondary_approval(self):
        """Non-payment terminations should not require secondary approval"""
        request = self._create_termination_request(termination_type="Non-payment")
        service = TerminationApprovalService(request)

        self.assertFalse(service.requires_secondary_approval())

    # ========================================================================
    # Submission Validation Tests
    # ========================================================================

    def test_validate_submission_requires_termination_reason(self):
        """Should require termination reason before submission"""
        request = self._create_termination_request(termination_reason="Placeholder")
        request.termination_reason = None  # Clear it after creation
        service = TerminationApprovalService(request)

        with self.assertRaises(frappe.ValidationError) as context:
            service.validate_submission_requirements()

        self.assertIn("Termination reason is required", str(context.exception))

    def test_validate_submission_requires_disciplinary_documentation(self):
        """Should require documentation for disciplinary terminations"""
        request = self._create_termination_request(
            termination_type="Policy Violation",
            disciplinary_documentation="Placeholder"
        )
        request.disciplinary_documentation = None  # Clear after creation
        service = TerminationApprovalService(request)

        with self.assertRaises(frappe.ValidationError) as context:
            service.validate_submission_requirements()

        self.assertIn("Documentation is required", str(context.exception))

    def test_validate_submission_passes_with_complete_data(self):
        """Should pass validation with complete data"""
        request = self._create_termination_request(
            termination_type="Policy Violation",
            termination_reason="Test policy violation",
            disciplinary_documentation="Test documentation"
        )
        service = TerminationApprovalService(request)

        # Should not raise
        service.validate_submission_requirements()

    # ========================================================================
    # Submission Workflow Tests
    # ========================================================================

    def test_submit_voluntary_termination_goes_to_approved(self):
        """Voluntary terminations should go directly to Approved"""
        request = self._create_termination_request(termination_type="Voluntary")
        service = TerminationApprovalService(request)

        result = service.submit_for_approval()

        self.assertEqual(result["status"], "Approved")
        self.assertEqual(request.status, "Approved")
        self.assertIsNotNone(request.approved_by)
        self.assertIsNotNone(request.approval_date)

    def test_submit_disciplinary_termination_goes_to_pending(self):
        """Disciplinary terminations should go to Pending status"""
        request = self._create_termination_request(
            termination_type="Disciplinary Action",
            disciplinary_documentation="Test docs",
            secondary_approver="approver.test@verenigingen.test"
        )
        service = TerminationApprovalService(request)

        result = service.submit_for_approval()

        self.assertEqual(result["status"], "Pending")
        self.assertEqual(request.status, "Pending")

    def test_submit_without_secondary_approver_fails(self):
        """Should fail if disciplinary termination lacks secondary approver"""
        request = self._create_termination_request(
            termination_type="Expulsion",
            disciplinary_documentation="Test docs"
            # No secondary_approver set
        )
        service = TerminationApprovalService(request)

        with self.assertRaises(frappe.ValidationError) as context:
            service.submit_for_approval()

        self.assertIn("Secondary approver is required", str(context.exception))

    def test_submit_calculates_termination_date(self):
        """Should calculate termination date on submission"""
        member_request_date = add_days(today(), -5)
        request = self._create_termination_request(
            termination_type="Voluntary",
            member_request_date=member_request_date,
            apply_grace_period=True
        )
        service = TerminationApprovalService(request)

        service.submit_for_approval()

        # Should have calculated termination date (member_request_date + grace period)
        self.assertIsNotNone(request.termination_date)

    # ========================================================================
    # Approval/Rejection Tests
    # ========================================================================

    def test_approve_request_updates_status_and_fields(self):
        """Approving should update status and set approval fields"""
        request = self._create_termination_request(
            termination_type="Disciplinary Action",
            disciplinary_documentation="Test",
            secondary_approver="approver.test@verenigingen.test"
        )
        request.status = "Pending"
        request.save()

        service = TerminationApprovalService(request)
        result = service.approve_request("approved", "Approved after review")

        self.assertEqual(result["status"], "Approved")
        self.assertEqual(request.status, "Approved")
        self.assertEqual(request.approved_by, frappe.session.user)
        self.assertIsNotNone(request.approval_date)
        self.assertEqual(request.approver_notes, "Approved after review")

    def test_reject_request_updates_status_and_fields(self):
        """Rejecting should update status and set rejection fields"""
        request = self._create_termination_request(
            termination_type="Policy Violation",
            disciplinary_documentation="Test",
            secondary_approver="approver.test@verenigingen.test"
        )
        request.status = "Pending"
        request.save()

        service = TerminationApprovalService(request)
        result = service.approve_request("rejected", "Insufficient evidence")

        self.assertEqual(result["status"], "Rejected")
        self.assertEqual(request.status, "Rejected")
        self.assertEqual(request.approved_by, frappe.session.user)
        self.assertEqual(request.approver_notes, "Insufficient evidence")

    def test_approve_invalid_decision_fails(self):
        """Should fail with invalid decision value"""
        request = self._create_termination_request()
        request.status = "Pending"
        request.save()

        service = TerminationApprovalService(request)

        with self.assertRaises(frappe.ValidationError) as context:
            service.approve_request("invalid_decision")

        self.assertIn("Invalid decision", str(context.exception))

    def test_approve_executed_request_fails(self):
        """Should not allow approving already executed requests"""
        request = self._create_termination_request()
        request.status = "Executed"
        request.save()

        service = TerminationApprovalService(request)

        with self.assertRaises(frappe.ValidationError) as context:
            service.approve_request("approved")

        self.assertIn("Only pending or draft", str(context.exception))

    # ========================================================================
    # Status Transition Handler Tests
    # ========================================================================

    def test_handle_approved_status_sets_approval_fields(self):
        """Handle approved status should set approval metadata"""
        request = self._create_termination_request()
        request.status = "Approved"

        service = TerminationApprovalService(request)
        service.handle_approved_status()

        self.assertEqual(request.approved_by, frappe.session.user)
        self.assertIsNotNone(request.approval_date)

    def test_handle_rejected_status_sets_approval_fields(self):
        """Handle rejected status should set rejection metadata"""
        request = self._create_termination_request()
        request.status = "Rejected"

        service = TerminationApprovalService(request)
        service.handle_rejected_status()

        self.assertEqual(request.approved_by, frappe.session.user)
        self.assertIsNotNone(request.approval_date)

    # ========================================================================
    # Approver Validation Tests
    # ========================================================================

    def test_validate_approver_with_valid_user(self):
        """Should pass validation for valid approver"""
        # Should not raise
        TerminationApprovalService().validate_approver_permissions(
            "approver.test@verenigingen.test"
        )

    def test_validate_approver_nonexistent_user_fails(self):
        """Should fail for non-existent user"""
        with self.assertRaises(frappe.ValidationError) as context:
            TerminationApprovalService().validate_approver_permissions(
                "nonexistent@test.com"
            )

        self.assertIn("does not exist", str(context.exception))

    def test_validate_approver_disabled_user_fails(self):
        """Should fail for disabled user"""
        # Create disabled user using factory method
        disabled_user = self._create_test_user(
            email="disabled.test@verenigingen.test",
            first_name="Disabled",
            last_name="User",
            enabled=0,
            roles=["Verenigingen Administrator"]
        )

        try:
            with self.assertRaises(frappe.ValidationError) as context:
                TerminationApprovalService().validate_approver_permissions(
                    "disabled.test@verenigingen.test"
                )

            self.assertIn("is disabled", str(context.exception))
        finally:
            frappe.delete_doc("User", "disabled.test@verenigingen.test", force=True)

    def test_validate_approver_insufficient_roles_fails(self):
        """Should fail for user without approval roles"""
        # Create user without approval roles using factory method
        norole_user = self._create_test_user(
            email="norole.test@verenigingen.test",
            first_name="No",
            last_name="Role",
            enabled=1,
            roles=None  # Don't add any approval roles
        )

        try:
            with self.assertRaises(frappe.ValidationError) as context:
                TerminationApprovalService().validate_approver_permissions(
                    "norole.test@verenigingen.test"
                )

            self.assertIn("does not have permission to approve", str(context.exception))
        finally:
            frappe.delete_doc("User", "norole.test@verenigingen.test", force=True)

    # ========================================================================
    # Get Eligible Approvers Tests
    # ========================================================================

    def test_get_eligible_approvers_returns_users_with_roles(self):
        """Should return users with approval roles"""
        approvers = TerminationApprovalService().get_eligible_approvers()

        self.assertIsInstance(approvers, list)
        self.assertGreater(len(approvers), 0)

        # Each result should be a tuple of (email, full_name)
        for approver in approvers:
            self.assertEqual(len(approver), 2)
            self.assertIsInstance(approver[0], str)  # email
            self.assertIsInstance(approver[1], str)  # full_name

    def test_get_eligible_approvers_filters_by_text(self):
        """Should filter approvers by search text"""
        # Search for the test approver
        approvers = TerminationApprovalService().get_eligible_approvers(txt="Test Approver")

        # Should find our test approver
        approver_emails = [a[0] for a in approvers]
        self.assertIn("approver.test@verenigingen.test", approver_emails)

    def test_get_eligible_approvers_excludes_disabled_users(self):
        """Should not return disabled users"""
        # Create disabled user using factory method
        disabled = self._create_test_user(
            email="disabled.approver@verenigingen.test",
            first_name="Disabled",
            last_name="Approver",
            enabled=0,
            roles=["Verenigingen Administrator"]
        )

        try:
            approvers = TerminationApprovalService().get_eligible_approvers()
            approver_emails = [a[0] for a in approvers]

            # Should not include disabled user
            self.assertNotIn("disabled.approver@verenigingen.test", approver_emails)
        finally:
            frappe.delete_doc("User", "disabled.approver@verenigingen.test", force=True)

    def test_get_eligible_approvers_pagination(self):
        """Should support pagination parameters"""
        # Get first page
        page1 = TerminationApprovalService().get_eligible_approvers(start=0, page_len=2)

        # Get second page
        page2 = TerminationApprovalService().get_eligible_approvers(start=2, page_len=2)

        # Pages should be different (unless there are fewer than 4 approvers total)
        if len(page1) == 2 and len(page2) > 0:
            self.assertNotEqual([a[0] for a in page1], [a[0] for a in page2])

    # ========================================================================
    # Integration Tests
    # ========================================================================

    def test_complete_voluntary_workflow(self):
        """Test complete workflow for voluntary termination"""
        # Create request
        request = self._create_termination_request(
            termination_type="Voluntary",
            member_request_date=today()
        )
        service = TerminationApprovalService(request)

        # Submit for approval
        result = service.submit_for_approval()
        self.assertEqual(result["status"], "Approved")

        # Verify all fields set correctly
        self.assertEqual(request.status, "Approved")
        self.assertIsNotNone(request.approved_by)
        self.assertIsNotNone(request.approval_date)
        self.assertIsNotNone(request.termination_date)

    def test_complete_disciplinary_workflow(self):
        """Test complete workflow for disciplinary termination"""
        # Create request
        request = self._create_termination_request(
            termination_type="Expulsion",
            disciplinary_documentation="Board resolution 2025-001",
            secondary_approver="approver.test@verenigingen.test"
        )
        service = TerminationApprovalService(request)

        # Submit for approval - should go to Pending
        result = service.submit_for_approval()
        self.assertEqual(result["status"], "Pending")

        # Approve the request
        result = service.approve_request("approved", "Board approved expulsion")
        self.assertEqual(result["status"], "Approved")

        # Verify all fields
        self.assertEqual(request.status, "Approved")
        self.assertIsNotNone(request.approved_by)
        self.assertIsNotNone(request.approval_date)
        self.assertEqual(request.approver_notes, "Board approved expulsion")
