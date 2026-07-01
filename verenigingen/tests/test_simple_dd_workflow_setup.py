# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen Contributors
# See license.txt

"""
Real integration tests for verenigingen/setup/simple_dd_workflow_setup.py

This module builds a *simplified* SEPA Direct Debit Batch approval Workflow
(6 states / 6 transitions) on the ``Direct Debit Batch`` doctype. It pre-creates
the Workflow State / Workflow Action Master masters it needs, so the workflow
actually gets created.

Tests create REAL Workflow / Workflow State / Workflow Action Master docs and
clean them up via ``track_doc`` (no business-logic mocking).

Notable production behaviour these tests pin down (see module report):
- ``add_workflow_custom_fields`` collides with the native ``approval_status``
  field on ``Direct Debit Batch``; via ``secure_document_operation`` it returns
  False and writes Error Logs instead of raising (BUG).
"""

import frappe

from verenigingen.setup.simple_dd_workflow_setup import (
    add_workflow_custom_fields,
    create_simple_dd_batch_workflow,
    setup_production_simple_workflow,
    setup_simple_dd_workflow,
)
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.constants import Roles

WORKFLOW_NAME = "SEPA Direct Debit Batch Simple Workflow"
DOCUMENT_TYPE = "Direct Debit Batch"

REQUIRED_STATES = ["Draft", "Pending", "Approved", "Rejected", "Submitted", "Completed"]
REQUIRED_ACTIONS = ["Approve", "Reject", "Submit", "Complete"]


class TestSimpleDDWorkflowSetup(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        if frappe.db.exists("Workflow", WORKFLOW_NAME):
            frappe.delete_doc("Workflow", WORKFLOW_NAME, force=True)
        # Snapshot which masters already exist so teardown only removes the ones
        # the code-under-test creates (deleting a pre-existing shared master
        # would corrupt the site).
        self._preexisting_states = {s for s in REQUIRED_STATES if frappe.db.exists("Workflow State", s)}
        self._preexisting_actions = {
            a for a in REQUIRED_ACTIONS if frappe.db.exists("Workflow Action Master", a)
        }

    # ------------------------------------------------------------------ helpers
    def _track_created_masters_then_workflow(self, track_workflow=True):
        """Register newly-created masters, then the workflow LAST so cleanup
        deletes the workflow before the masters it references."""
        for state in REQUIRED_STATES:
            if state not in self._preexisting_states and frappe.db.exists("Workflow State", state):
                self.track_doc("Workflow State", state)
        for action in REQUIRED_ACTIONS:
            if action not in self._preexisting_actions and frappe.db.exists("Workflow Action Master", action):
                self.track_doc("Workflow Action Master", action)
        if track_workflow and frappe.db.exists("Workflow", WORKFLOW_NAME):
            self.track_doc("Workflow", WORKFLOW_NAME)

    @staticmethod
    def _find_transition(workflow, state, action):
        for row in workflow.transitions:
            if row.state == state and row.action == action:
                return row
        return None

    # ---------------------------------------------------------- workflow build
    def test_create_simple_dd_batch_workflow_builds_workflow(self):
        result = create_simple_dd_batch_workflow()
        self._track_created_masters_then_workflow()
        self.assertTrue(result)

        workflow = frappe.get_doc("Workflow", WORKFLOW_NAME)
        self.assertEqual(workflow.document_type, DOCUMENT_TYPE)
        self.assertEqual(workflow.workflow_state_field, "approval_status")
        self.assertEqual(workflow.is_active, 1)
        self.assertEqual(len(workflow.states), 6)
        self.assertEqual(len(workflow.transitions), 6)
        self.assertEqual({s.state for s in workflow.states}, set(REQUIRED_STATES))

        # Draft -> Submit -> Pending, gated to Verenigingen Staff.
        t = self._find_transition(workflow, "Draft", "Submit")
        self.assertIsNotNone(t)
        self.assertEqual(t.next_state, "Pending")
        self.assertEqual(t.allowed, "Verenigingen Staff")

        # Pending -> Approve -> Approved, gated to Financial Manager.
        t = self._find_transition(workflow, "Pending", "Approve")
        self.assertIsNotNone(t)
        self.assertEqual(t.next_state, "Approved")
        self.assertEqual(t.allowed, Roles.FINANCIAL_MANAGER)

        # Pending -> Reject -> Rejected.
        t = self._find_transition(workflow, "Pending", "Reject")
        self.assertIsNotNone(t)
        self.assertEqual(t.next_state, "Rejected")

        # Submitted -> Complete -> Completed, gated to System Manager.
        t = self._find_transition(workflow, "Submitted", "Complete")
        self.assertIsNotNone(t)
        self.assertEqual(t.next_state, "Completed")
        self.assertEqual(t.allowed, "System Manager")

        # doc_status: Approved/Submitted/Completed are submitted (1), Draft is 0.
        states_by_name = {s.state: s for s in workflow.states}
        self.assertEqual(states_by_name["Draft"].doc_status, "0")
        self.assertEqual(states_by_name["Approved"].doc_status, "1")
        self.assertEqual(states_by_name["Completed"].doc_status, "1")

    def test_create_simple_creates_required_masters(self):
        create_simple_dd_batch_workflow()
        self._track_created_masters_then_workflow()

        for state in REQUIRED_STATES:
            self.assert_doc_exists("Workflow State", {"name": state})
        for action in REQUIRED_ACTIONS:
            self.assert_doc_exists("Workflow Action Master", {"name": action})

    def test_create_simple_dd_batch_workflow_idempotent(self):
        first = create_simple_dd_batch_workflow()
        self._track_created_masters_then_workflow()
        self.assertTrue(first)

        second = create_simple_dd_batch_workflow()
        self.assertTrue(second)
        self.assertEqual(frappe.db.count("Workflow", {"workflow_name": WORKFLOW_NAME}), 1)

    # --------------------------------------------------------- custom-field bug
    def test_add_workflow_custom_fields_returns_false_on_native_collision(self):
        """BUG: Direct Debit Batch already has a native ``approval_status`` field.
        secure_document_operation cannot insert a duplicate Custom Field, so the
        function logs errors and returns False (never reaching workflow_state)."""
        self.expectErrorLog("Failed to create approval status field", "Secure Operation Failed")

        result = add_workflow_custom_fields()

        self.assertFalse(result)
        self.assertFalse(frappe.db.exists("Custom Field", f"{DOCUMENT_TYPE}-approval_status"))
        # Early return means workflow_state field is never created either.
        self.assertFalse(frappe.db.exists("Custom Field", f"{DOCUMENT_TYPE}-workflow_state"))

    # ------------------------------------------------------- orchestrator paths
    def test_setup_simple_dd_workflow_end_to_end(self):
        """setup swallows the custom-field failure (Error Logs expected) and still
        creates the workflow via the master-provisioning path."""
        self.expectErrorLog("Failed to create approval status field", "Secure Operation Failed")

        result = setup_simple_dd_workflow()
        self._track_created_masters_then_workflow()

        self.assertTrue(result)
        self.assertTrue(frappe.db.exists("Workflow", WORKFLOW_NAME))
        workflow = frappe.get_doc("Workflow", WORKFLOW_NAME)
        self.assertEqual(len(workflow.states), 6)
        self.assertEqual(len(workflow.transitions), 6)

    def test_setup_production_simple_workflow_whitelisted(self):
        """The whitelisted @critical_api endpoint delegates to
        setup_simple_dd_workflow and produces the same workflow."""
        self.expectErrorLog("Failed to create approval status field", "Secure Operation Failed")

        result = setup_production_simple_workflow()
        self._track_created_masters_then_workflow()

        self.assertTrue(result)
        self.assertTrue(frappe.db.exists("Workflow", WORKFLOW_NAME))
