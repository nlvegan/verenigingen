"""
Test coverage for 2 termination services.

Services tested:
1. TerminationExecutionService — termination execution with idempotency
2. TerminationAuditService — termination audit trail management
"""

import frappe
from frappe.utils import now, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


# ---------------------------------------------------------------------------
# Helper: create a Membership Termination Request for testing
# ---------------------------------------------------------------------------
def _create_termination_request(member_name, status="Approved", termination_type="Voluntary"):
    """Create a Membership Termination Request for tests."""
    doc = frappe.get_doc(
        {
            "doctype": "Membership Termination Request",
            "member": member_name,
            "termination_type": termination_type,
            "status": status,
            "request_date": today(),
            "termination_date": today(),
            "termination_reason": "Test termination reason",
        }
    )
    doc.insert(ignore_permissions=True)
    return doc


# ---------------------------------------------------------------------------
# 1. TerminationExecutionService
# ---------------------------------------------------------------------------
class TestTerminationExecutionService(EnhancedTestCase):
    """Tests for TerminationExecutionService — execute, validate, track."""

    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="TermExec", last_name=f"S{self.uid}")

    def _get_service(self):
        from verenigingen.services.termination.termination_execution_service import (
            get_termination_execution_service,
        )

        return get_termination_execution_service()

    # --- execute: type validation ---
    def test_execute_rejects_non_document(self):
        """execute() raises TypeError when passed a non-Document."""
        svc = self._get_service()
        with self.assertRaises(TypeError):
            svc.execute("not-a-document")

    def test_execute_rejects_wrong_doctype(self):
        """execute() raises TypeError when passed a document of wrong DocType."""
        svc = self._get_service()
        member_doc = frappe.get_doc("Member", self.member.name)
        with self.assertRaises(TypeError):
            svc.execute(member_doc)

    # --- _validate_preconditions ---
    def test_validate_preconditions_requires_member_exists(self):
        """_validate_preconditions raises when member does not exist."""
        svc = self._get_service()
        req = _create_termination_request(self.member.name, status="Approved")
        # Patch member field to non-existent
        req.member = "NONEXISTENT-MEMBER-12345"
        with self.assertRaises(frappe.ValidationError):
            svc._validate_preconditions(req)

    def test_validate_preconditions_requires_approved_status(self):
        """_validate_preconditions raises when status is not Approved."""
        svc = self._get_service()
        req = _create_termination_request(self.member.name, status="Draft")
        with self.assertRaises(frappe.ValidationError):
            svc._validate_preconditions(req)

    def test_validate_preconditions_passes_for_approved(self):
        """_validate_preconditions succeeds for an Approved request with valid member."""
        svc = self._get_service()
        req = _create_termination_request(self.member.name, status="Approved")
        # Should not raise
        svc._validate_preconditions(req)

    # --- _update_tracking ---
    def test_update_tracking_sets_execution_fields(self):
        """_update_tracking sets executed_by and execution_date on first call."""
        svc = self._get_service()
        req = _create_termination_request(self.member.name)
        results = {"actions_taken": ["a", "b"], "errors": [], "sepa_mandates_cancelled": 2,
                    "positions_ended": 1, "customer_updated": True, "outstanding_invoices_cancelled": 3}
        svc._update_tracking(req, results)
        self.assertEqual(req.executed_by, frappe.session.user)
        self.assertIsNotNone(req.execution_date)
        self.assertEqual(req.sepa_mandates_cancelled, 2)
        self.assertEqual(req.positions_ended, 1)
        self.assertEqual(req.newsletters_updated, 1)
        self.assertEqual(req.outstanding_invoices_cancelled, 3)

    def test_update_tracking_preserves_original_on_retry(self):
        """_update_tracking keeps original executed_by on retry."""
        svc = self._get_service()
        req = _create_termination_request(self.member.name)
        # Simulate first execution
        req.executed_by = "original@example.com"
        req.execution_date = "2025-01-01 00:00:00"
        results = {"actions_taken": [], "errors": [], "sepa_mandates_cancelled": 0,
                    "positions_ended": 0, "customer_updated": False, "outstanding_invoices_cancelled": 0}
        svc._update_tracking(req, results)
        self.assertEqual(req.executed_by, "original@example.com")
        self.assertEqual(str(req.execution_date), "2025-01-01 00:00:00")

    # --- execute_from_api ---
    def test_execute_from_api_rejects_non_approved(self):
        """execute_from_api raises for a non-Approved request."""
        svc = self._get_service()
        req = _create_termination_request(self.member.name, status="Draft")
        with self.assertRaises(frappe.ValidationError):
            svc.execute_from_api(req)

    # --- _check_idempotency_with_lock ---
    def test_idempotency_check_returns_false_when_not_executed(self):
        """_check_idempotency_with_lock returns False for fresh request."""
        svc = self._get_service()
        req = _create_termination_request(self.member.name)
        result = svc._check_idempotency_with_lock(req)
        self.assertFalse(result)

    def test_idempotency_check_returns_true_when_already_executed(self):
        """_check_idempotency_with_lock returns True when execution_date is set."""
        svc = self._get_service()
        req = _create_termination_request(self.member.name)
        # Set execution_date directly in DB
        frappe.db.set_value(
            "Membership Termination Request", req.name,
            {"execution_date": now(), "executed_by": frappe.session.user},
        )
        result = svc._check_idempotency_with_lock(req)
        self.assertTrue(result)


# ---------------------------------------------------------------------------
# 2. TerminationAuditService
# ---------------------------------------------------------------------------
class TestTerminationAuditService(EnhancedTestCase):
    """Tests for TerminationAuditService — audit entry creation and status logging."""

    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="TermAudit", last_name=f"S{self.uid}")

    def _get_service(self):
        from verenigingen.services.termination.termination_audit_service import (
            get_termination_audit_service,
        )

        return get_termination_audit_service()

    # --- add_entry ---
    def test_add_entry_appends_user_action(self):
        """add_entry appends a user-initiated audit entry."""
        svc = self._get_service()
        req = _create_termination_request(self.member.name)
        svc.add_entry(req, "Test Action", "Some details")
        trail = [r for r in req.audit_trail if r.action == "Test Action"]
        self.assertEqual(len(trail), 1)
        self.assertEqual(trail[0].details, "Some details")
        self.assertEqual(trail[0].system_action, 0)

    def test_add_entry_system_action_uses_administrator(self):
        """add_entry with is_system=True uses Administrator as user."""
        svc = self._get_service()
        req = _create_termination_request(self.member.name)
        svc.add_entry(req, "System Op", "sys details", is_system=True)
        trail = [r for r in req.audit_trail if r.action == "System Op"]
        self.assertEqual(len(trail), 1)
        self.assertEqual(trail[0].user, "Administrator")
        self.assertEqual(trail[0].system_action, 1)

    def test_add_entry_invalid_user_falls_back_to_administrator(self):
        """add_entry falls back to Administrator when session user does not exist."""
        svc = self._get_service()
        req = _create_termination_request(self.member.name)
        original_user = frappe.session.user
        try:
            frappe.session.user = "nonexistent_user_xyz@invalid.tld"
            svc.add_entry(req, "Fallback Test", "fallback details")
            trail = [r for r in req.audit_trail if r.action == "Fallback Test"]
            self.assertEqual(len(trail), 1)
            self.assertEqual(trail[0].user, "Administrator")
        finally:
            frappe.session.user = original_user

    # --- log_status_change ---
    def test_log_status_change_records_transition(self):
        """log_status_change adds audit entry with old/new status."""
        svc = self._get_service()
        req = _create_termination_request(self.member.name)
        initial_count = len(req.audit_trail)
        svc.log_status_change(req, old_status="Draft", new_status="Approved")
        # Should have added at least one audit entry for the status change
        self.assertGreater(len(req.audit_trail), initial_count)
        latest = req.audit_trail[-1]
        self.assertIn("Approved", latest.details)

    def test_log_status_change_approved_logs_approver(self):
        """log_status_change for Approved transition logs the approver."""
        svc = self._get_service()
        req = _create_termination_request(self.member.name, status="Approved")
        req.approved_by = frappe.session.user
        initial_count = len(req.audit_trail)
        svc.log_status_change(req, old_status="Draft", new_status="Approved")
        # Should log both status change and approval entry
        self.assertGreater(len(req.audit_trail), initial_count)

    def test_log_status_change_rejected_logs_reason(self):
        """log_status_change for Rejected transition logs the rejector and the
        approver_notes as the rejection reason.

        Regression (audit T1.1, 2026-05-17): the service previously read
        doc.rejection_reason, a field absent from the Membership Termination
        Request DocType, raising AttributeError on every rejection. It must
        read approver_notes (the real field) instead.
        """
        svc = self._get_service()
        req = _create_termination_request(self.member.name, status="Rejected")
        req.approved_by = frappe.session.user
        req.approver_notes = "Policy violation"
        svc.log_status_change(req, old_status="Approved", new_status="Rejected")
        reject_entries = [r for r in req.audit_trail if r.action == "Request Rejected"]
        self.assertEqual(len(reject_entries), 1)
        self.assertIn("Policy violation", reject_entries[0].details)

    # --- log_document_update ---
    def test_log_document_update(self):
        """log_document_update adds an audit entry (hooks may add entries on insert)."""
        svc = self._get_service()
        req = _create_termination_request(self.member.name)
        count_before = len([r for r in req.audit_trail if r.action == "Document Updated"])
        svc.log_document_update(req)
        count_after = len([r for r in req.audit_trail if r.action == "Document Updated"])
        self.assertEqual(count_after, count_before + 1)

    # --- log_request_created ---
    def test_log_request_created(self):
        """log_request_created adds entry with termination type."""
        svc = self._get_service()
        req = _create_termination_request(self.member.name, termination_type="Voluntary")
        count_before = len([r for r in req.audit_trail if r.action == "Request Created"])
        svc.log_request_created(req)
        trail = [r for r in req.audit_trail if r.action == "Request Created"]
        self.assertEqual(len(trail), count_before + 1)
        self.assertIn("Voluntary", trail[-1].details)

    # --- log_execution_complete ---
    def test_log_execution_complete_no_errors(self):
        """log_execution_complete adds entries for actions taken."""
        svc = self._get_service()
        req = _create_termination_request(self.member.name)
        results = {"actions_taken": ["Cancel membership", "Cancel SEPA"], "errors": []}
        svc.log_execution_complete(req, results)
        exec_entries = [r for r in req.audit_trail if r.action == "Termination Executed"]
        self.assertEqual(len(exec_entries), 1)
        self.assertIn("2 actions", exec_entries[0].details)

    def test_log_execution_complete_with_errors(self):
        """log_execution_complete logs warnings count."""
        svc = self._get_service()
        req = _create_termination_request(self.member.name)
        results = {"actions_taken": ["a"], "errors": ["err1", "err2"]}
        svc.log_execution_complete(req, results)
        exec_entries = [r for r in req.audit_trail if r.action == "Termination Executed"]
        self.assertIn("2 warnings", exec_entries[0].details)

    # --- log_execution_failed ---
    def test_log_execution_failed_records_error(self):
        """log_execution_failed adds audit entry with error info."""
        svc = self._get_service()
        req = _create_termination_request(self.member.name)
        try:
            raise ValueError("Test error for audit")
        except ValueError as e:
            svc.log_execution_failed(req, e)
        fail_entries = [r for r in req.audit_trail if r.action == "Execution Failed"]
        self.assertEqual(len(fail_entries), 1)
        self.assertIn("ValueError", fail_entries[0].details)
        self.assertIn("Test error for audit", fail_entries[0].details)
