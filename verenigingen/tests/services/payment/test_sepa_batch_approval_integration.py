# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Real-DB integration tests for SEPABatchApprovalService.

The companion test_sepa_batch_approval.py mocks ``_get_batch_info`` and
``frappe.get_roles`` throughout, so the real database lookup in
``_get_batch_info`` and the real role check in ``_user_has_approval_role``
are never exercised. This module drives both against real Direct Debit Batch
documents and real Users.

IMPORTANT (see module FLAG below): the SEPABatchApprovalService /
SEPABatchStateMachine pair operates on the Direct Debit Batch ``status`` field
using values ("Pending Approval", "Approved", ...) that are NOT valid options of
that Select field -- they belong to the separate ``approval_status`` field. The
live production approval workflow is dd_batch_workflow_controller.py (which uses
``approval_status``); this service has no production callers. As a consequence
the happy-path state transition cannot complete against a real batch. The tests
below cover every decision branch that runs BEFORE that transition (which is the
service's actual validation logic) and characterize the broken transition so the
behaviour is pinned for whoever resolves the FLAG.
"""

import frappe

from verenigingen.services.payment.sepa_batch_approval_service import (
    SEPABatchApprovalService,
    get_sepa_batch_approval_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class _BatchMixin:
    """Helpers to create real, invoice-less Direct Debit Batch fixtures."""

    def _make_batch(self, *, status="Pending Approval"):
        """Insert a minimal Direct Debit Batch and force its status directly.

        validate() (invoice validation) is bypassed for the bare insert via
        ignore_validate; the target status is written with set_value so the
        Select-option guard does not reject the workflow-only values. The batch
        owner is the current (Administrator) session user.
        """
        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = frappe.utils.today()
        batch.batch_type = "CORE"
        batch.currency = "EUR"
        batch.status = "Draft"
        batch.batch_description = "approval-service integration fixture"
        batch.flags.ignore_validate = True
        batch.insert()
        if status != "Draft":
            frappe.db.set_value(
                "Direct Debit Batch", batch.name, "status", status, update_modified=False
            )
        return batch.name


class TestSEPABatchApprovalGetBatchInfo(_BatchMixin, EnhancedTestCase):
    """_get_batch_info() reads real status + owner from the DB."""

    def setUp(self):
        super().setUp()
        self.service = SEPABatchApprovalService()

    def test_returns_status_and_owner_for_real_batch(self):
        name = self._make_batch(status="Pending Approval")
        info = self.service._get_batch_info(name)
        self.assertIsNotNone(info)
        self.assertEqual(info["status"], "Pending Approval")
        self.assertEqual(info["owner"], frappe.session.user)

    def test_returns_none_for_missing_batch(self):
        self.assertIsNone(self.service._get_batch_info("BATCH-DOES-NOT-EXIST"))


class TestSEPABatchApprovalRealRoleCheck(_BatchMixin, EnhancedTestCase):
    """_user_has_approval_role() against real Has Role rows."""

    def setUp(self):
        super().setUp()
        self.service = SEPABatchApprovalService()

    def test_user_without_role_is_rejected(self):
        user = self.create_test_user_with_roles(
            email="plain.user@example.com", roles=["Verenigingen Member"]
        ).name
        self.assertFalse(self.service._user_has_approval_role(user))

    def test_user_with_accounts_manager_is_accepted(self):
        user = self.create_test_user_with_roles(
            email="am.user@example.com", roles=["Accounts Manager"]
        ).name
        self.assertTrue(self.service._user_has_approval_role(user))


class TestSEPABatchApprovalRealApprove(_BatchMixin, EnhancedTestCase):
    """approve_batch() validation branches against real batches."""

    def setUp(self):
        super().setUp()
        self.service = SEPABatchApprovalService()

    def test_batch_not_found(self):
        result = self.service.approve_batch("BATCH-DOES-NOT-EXIST", approver="x@example.com")
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "BATCH_NOT_FOUND")

    def test_wrong_state_rejected(self):
        name = self._make_batch(status="Draft")
        result = self.service.approve_batch(name, approver="other@example.com")
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "INVALID_STATE")
        self.assertIn("Pending Approval", result.error_message)

    def test_creator_cannot_approve_own_batch(self):
        # Owner is the current session user; approve as the same user.
        name = self._make_batch(status="Pending Approval")
        result = self.service.approve_batch(name, approver=frappe.session.user)
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "APPROVAL_DENIED")
        self.assertIn("four-eyes", result.error_message.lower())

    def test_approver_without_role_denied(self):
        name = self._make_batch(status="Pending Approval")
        user = self.create_test_user_with_roles(
            email="norole.approver@example.com", roles=["Verenigingen Member"]
        ).name
        result = self.service.approve_batch(name, approver=user)
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "APPROVAL_DENIED")
        self.assertIn("Accounts Manager", result.error_message)

    def test_four_eyes_and_role_pass_then_transition_fails_FLAG(self):
        """A DIFFERENT Accounts Manager passes four-eyes + role, yet approval
        still fails at the state-machine transition.

        This characterizes the FLAG: the service tries to set the Direct Debit
        Batch ``status`` to "Approved" (an invalid Select option / wrong field)
        via a full validating save, which cannot succeed on a real batch. The
        global commit in approve_batch is therefore never reached.
        """
        name = self._make_batch(status="Pending Approval")
        approver = self.create_test_user_with_roles(
            email="real.approver@example.com", roles=["Accounts Manager"]
        ).name
        result = self.service.approve_batch(name, approver=approver)
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "TRANSITION_FAILED")
        # Status is left untouched -- no partial/committed state change.
        self.assertEqual(
            frappe.db.get_value("Direct Debit Batch", name, "status"), "Pending Approval"
        )


class TestSEPABatchApprovalRealReject(_BatchMixin, EnhancedTestCase):
    """reject_batch() validation branches against real batches."""

    def setUp(self):
        super().setUp()
        self.service = SEPABatchApprovalService()

    def test_reason_required(self):
        name = self._make_batch(status="Pending Approval")
        result = self.service.reject_batch(name, rejector="x@example.com", reason="   ")
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "REASON_REQUIRED")

    def test_batch_not_found(self):
        result = self.service.reject_batch(
            "BATCH-DOES-NOT-EXIST", rejector="x@example.com", reason="bad"
        )
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "BATCH_NOT_FOUND")

    def test_wrong_state_rejected(self):
        name = self._make_batch(status="Draft")
        result = self.service.reject_batch(name, rejector="x@example.com", reason="bad")
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "INVALID_STATE")

    def test_reject_transition_fails_on_invoiceless_batch_FLAG(self):
        """Even rejection (-> Draft, a valid status option) fails on a real batch.

        The state machine's execute_transition() performs a full validating
        save, which trips Direct Debit Batch.validate_invoices() ("No valid
        invoices found"). Characterizes the FLAG: the transition layer is
        unusable against real batches regardless of the target status value.
        """
        name = self._make_batch(status="Pending Approval")
        result = self.service.reject_batch(name, rejector="x@example.com", reason="bad")
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "TRANSITION_FAILED")


class TestSEPABatchApprovalFactory(EnhancedTestCase):
    def test_factory_singleton(self):
        a = get_sepa_batch_approval_service()
        b = get_sepa_batch_approval_service()
        self.assertIs(a, b)
        self.assertIsInstance(a, SEPABatchApprovalService)
