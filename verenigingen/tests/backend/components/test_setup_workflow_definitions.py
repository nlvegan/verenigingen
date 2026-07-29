# Integration tests for verenigingen/setup/workflow_setup.py
#
# This module runs on every fresh install (execute_after_install ->
# setup_termination_system_integration -> setup_workflows_corrected) and is the
# only thing that creates the "Membership Termination Workflow".
#
# KNOWN PRODUCTION BUG pinned by these tests:
#   create_workflow_action_masters() creates only the "Execute" Workflow Action
#   Master ("standard ones should exist"), but the termination workflow's
#   transitions also reference a "Submit" action -- which is NOT a standard
#   Frappe/ERPNext master and is NOT in verenigingen/fixtures/
#   workflow_action_master.json (that fixture ships "Execute" only).
#   Workflow Transition.action is a Link, so the insert dies on link validation
#   ("Could not find Row #1: Action: Submit"), secure_document_operation returns
#   success=False, create_termination_workflow_corrected() logs an Error Log and
#   returns False -- and setup_workflows_corrected() STILL returns True because
#   the appeals workflow "succeeds" by skipping. The caller then prints
#   "Workflows created successfully". Net effect: no termination workflow, ever,
#   and no visible failure.
#
# TestTerminationWorkflowDefinition proves the rest of the definition is sound by
# supplying the missing masters and asserting the workflow then builds correctly
# and lines up with the Membership Termination Request status field.
#
# Isolation: create_termination_workflow_corrected() /
# create_appeals_workflow_corrected() do NOT commit (secure_document_operation
# has no commit), so everything they insert is rolled back with the test
# transaction. setup_workflows_corrected() DOES commit; the only tests that call
# it are the ones asserting its (non-)effects.

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.setup import workflow_setup as wf
from verenigingen.utils.constants import Roles

TERMINATION_WORKFLOW = "Membership Termination Workflow"
TARGET_DOCTYPE = "Membership Termination Request"
# Every action referenced by the termination workflow's transitions.
TRANSITION_ACTIONS = ["Submit", "Approve", "Reject", "Execute"]
# Every state referenced by the termination workflow.
WORKFLOW_STATES = ["Draft", "Pending", "Approved", "Rejected", "Executed"]


class TestWorkflowMasters(FrappeTestCase):
    """create_workflow_state_masters() / create_workflow_action_masters()."""

    def test_state_masters_ensure_the_custom_executed_state(self):
        wf.create_workflow_state_masters()
        self.assertTrue(
            frappe.db.exists("Workflow State", "Executed"),
            "'Executed' is the one non-standard state the termination workflow needs",
        )

    def test_state_masters_are_idempotent(self):
        wf.create_workflow_state_masters()
        before = frappe.db.count("Workflow State")
        self.assertEqual(wf.create_workflow_state_masters(), 0)
        self.assertEqual(frappe.db.count("Workflow State"), before)

    def test_action_masters_ensure_the_custom_execute_action(self):
        wf.create_workflow_action_masters()
        self.assertTrue(frappe.db.exists("Workflow Action Master", "Execute"))

    def test_action_masters_are_idempotent(self):
        wf.create_workflow_action_masters()
        before = frappe.db.count("Workflow Action Master")
        self.assertEqual(wf.create_workflow_action_masters(), 0)
        self.assertEqual(frappe.db.count("Workflow Action Master"), before)

    def test_action_masters_do_not_cover_the_submit_transition(self):
        """KNOWN BUG (see module docstring).

        create_workflow_action_masters() creates only "Execute". "Submit" is
        referenced by four of the termination workflow's transitions but is
        neither a standard master nor created/shipped anywhere, so it is still
        absent after the setup has run.
        """
        wf.create_workflow_action_masters()
        self.assertFalse(
            frappe.db.exists("Workflow Action Master", "Submit"),
            "If 'Submit' now exists the upstream bug was fixed - update this test "
            "and the workflow-creation tests below",
        )


class TestValidatePrerequisites(FrappeTestCase):
    def test_passes_on_an_installed_site(self):
        self.assertTrue(wf.validate_prerequisites())
        # The individual things it checks must really be there, so a True above
        # is not an accident of the check being vacuous.
        self.assertTrue(frappe.db.exists("DocType", TARGET_DOCTYPE))
        for role in Roles.ADMIN_PAIR:
            self.assertTrue(frappe.db.exists("Role", role), f"Missing role {role}")

    def test_fails_when_a_required_role_is_absent(self):
        """A fresh site that has not yet created the Verenigingen Administrator
        role must abort workflow setup rather than build a workflow whose
        allow_edit/allowed roles do not exist."""

        class _RolesWithPhantomAdmin:
            ADMIN_PAIR = frozenset({Roles.SYSTEM_MANAGER, "No Such Role For Workflow Test"})

        original = wf.Roles
        wf.Roles = _RolesWithPhantomAdmin
        try:
            self.assertFalse(wf.validate_prerequisites())
        finally:
            wf.Roles = original


class TestTerminationWorkflowCreation(FrappeTestCase):
    """create_termination_workflow_corrected() -- the broken install step."""

    def setUp(self):
        super().setUp()
        if frappe.db.exists("Workflow", TERMINATION_WORKFLOW):
            self.skipTest(
                f"{TERMINATION_WORKFLOW} already exists on this site; these tests " "cover the creation path"
            )

    @staticmethod
    def _drop(doctype, name):
        if frappe.db.exists(doctype, name):
            frappe.delete_doc(doctype, name, force=1)

    def _drop_workflow(self):
        self._drop("Workflow", TERMINATION_WORKFLOW)

    def test_creation_fails_and_persists_nothing_while_submit_master_is_missing(self):
        """KNOWN BUG (see module docstring): the insert dies on link validation
        for the 'Submit' action, so the function returns False and no Workflow
        row is written."""
        self.assertFalse(frappe.db.exists("Workflow Action Master", "Submit"))

        self.assertFalse(wf.create_termination_workflow_corrected())
        self.assertFalse(
            frappe.db.exists("Workflow", TERMINATION_WORKFLOW),
            "No workflow may be half-written when creation fails",
        )

    def test_definition_is_valid_once_every_referenced_master_exists(self):
        """The rest of the definition is sound: supply the missing masters and
        the workflow builds with all 5 states and all 10 transitions.

        This isolates the failure to the missing 'Submit' Workflow Action Master
        and simultaneously guards the definition itself (state/transition counts,
        the state field it drives, and its active flag).
        """
        # Everything created here is removed again by addCleanup so the rest of
        # the suite still sees a site without a termination workflow.
        self.addCleanup(self._drop_workflow)
        for action in TRANSITION_ACTIONS:
            if not frappe.db.exists("Workflow Action Master", action):
                frappe.get_doc({"doctype": "Workflow Action Master", "workflow_action_name": action}).insert()
                self.addCleanup(self._drop, "Workflow Action Master", action)
        for state in WORKFLOW_STATES:
            if not frappe.db.exists("Workflow State", state):
                frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": state}).insert()
                self.addCleanup(self._drop, "Workflow State", state)

        self.assertTrue(
            wf.create_termination_workflow_corrected(),
            "With every referenced master present the workflow must be creatable",
        )

        doc = frappe.get_doc("Workflow", TERMINATION_WORKFLOW)
        self.assertEqual(doc.document_type, TARGET_DOCTYPE)
        self.assertEqual(doc.workflow_state_field, "status")
        self.assertEqual(doc.is_active, 1)
        self.assertEqual([s.state for s in doc.states], WORKFLOW_STATES)
        self.assertEqual(len(doc.transitions), 10)
        # "Executed" is the only submitted state; everything else stays draft.
        self.assertEqual(
            {s.state: s.doc_status for s in doc.states},
            {"Draft": "0", "Pending": "0", "Approved": "0", "Rejected": "0", "Executed": "1"},
        )


class TestTerminationWorkflowContract(FrappeTestCase):
    """Invariants the workflow definition depends on, independent of whether the
    workflow row can currently be created."""

    def test_workflow_states_are_selectable_values_of_the_status_field(self):
        """The workflow drives Membership Termination Request.status. If the
        DocType's Select options and the workflow's states ever drift apart,
        documents get stuck in a state the field cannot hold."""
        options = frappe.get_meta(TARGET_DOCTYPE).get_field("status").options.split("\n")
        for state in WORKFLOW_STATES:
            self.assertIn(state, options, f"Workflow state '{state}' is not a valid status option")

    def test_every_role_referenced_by_the_workflow_exists(self):
        """allow_edit / allowed are Link fields onto Role; a missing role would
        be another silent link-validation failure at install time."""
        for role in ("System Manager", Roles.VERENIGINGEN_ADMIN):
            self.assertTrue(frappe.db.exists("Role", role), f"Missing role: {role}")


class TestAppealsWorkflow(FrappeTestCase):
    def test_skipped_when_its_doctype_does_not_exist(self):
        """create_appeals_workflow_corrected() returns True by SKIPPING when the
        Termination Appeals Process DocType is absent -- which it is, app-wide.

        That truthy skip is what lets setup_workflows_corrected() report overall
        success even when the termination workflow failed to build.
        """
        self.assertFalse(frappe.db.exists("DocType", "Termination Appeals Process"))
        self.assertTrue(wf.create_appeals_workflow_corrected())
        self.assertFalse(frappe.db.exists("Workflow", "Termination Appeals Workflow"))


class TestSetupWorkflowsCorrected(FrappeTestCase):
    """The orchestrator. NOTE: it calls frappe.db.commit() internally."""

    def test_reports_success_although_the_termination_workflow_is_absent(self):
        """KNOWN BUG (see module docstring): setup_workflows_corrected() returns
        True purely because the appeals branch skipped, while the workflow that
        actually matters was never created. A fresh site therefore ends up with
        no termination workflow and a green install log.

        Skips rather than fails when the workflow is already present: this class
        calls setup_workflows_corrected(), which commits internally, so a sibling
        test (or a site where 'Submit' exists) can leave the workflow behind and
        turn this into a spurious red that says nothing about the code.
        """
        if frappe.db.exists("Workflow", TERMINATION_WORKFLOW):
            self.skipTest(
                f"{TERMINATION_WORKFLOW} already exists on this site - the "
                "missing-workflow bug this test documents is not reproducible here"
            )

        self.assertTrue(wf.setup_workflows_corrected())
        self.assertFalse(
            frappe.db.exists("Workflow", TERMINATION_WORKFLOW),
            "If the workflow now exists the upstream bug was fixed - update this test",
        )

    def test_is_idempotent_and_does_not_duplicate_masters(self):
        wf.setup_workflows_corrected()
        states = frappe.db.count("Workflow State")
        actions = frappe.db.count("Workflow Action Master")
        workflows = frappe.db.count("Workflow")

        wf.setup_workflows_corrected()

        self.assertEqual(frappe.db.count("Workflow State"), states)
        self.assertEqual(frappe.db.count("Workflow Action Master"), actions)
        self.assertEqual(frappe.db.count("Workflow"), workflows)

    def test_aborts_when_prerequisites_fail(self):
        """A missing role must stop the run before any master is created."""

        class _RolesWithPhantomAdmin:
            ADMIN_PAIR = frozenset({Roles.SYSTEM_MANAGER, "No Such Role For Workflow Test"})

        original = wf.Roles
        wf.Roles = _RolesWithPhantomAdmin
        try:
            self.assertFalse(wf.setup_workflows_corrected())
        finally:
            wf.Roles = original
