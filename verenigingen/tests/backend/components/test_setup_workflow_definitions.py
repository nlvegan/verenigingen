# Integration tests for verenigingen/setup/workflow_setup.py
#
# This module runs on every fresh install (execute_after_install ->
# setup_termination_system_integration -> setup_workflows_corrected).
#
# #1640 (maintainer ruling 2026-10-29): it does NOT build a Membership
# Termination Workflow. The service layer is the source of truth for termination
# status; an active workflow on `status` would refuse the services' direct
# status writes. The tests below pin that no such workflow is built and that
# setup still reports success.
#
# setup_workflows_corrected() commits; the tests that call it only assert its
# (non-)effects on workflows and masters.

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.setup import workflow_setup as wf
from verenigingen.utils.constants import Roles
from verenigingen.utils.secure_operations import SecureOperationResult

TERMINATION_WORKFLOW = "Membership Termination Workflow"
TARGET_DOCTYPE = "Membership Termination Request"
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

    def test_termination_workflow_builder_is_gone(self):
        """#1640: nothing in workflow_setup builds the termination workflow, so
        no "Submit" action master is needed either."""
        self.assertFalse(hasattr(wf, "create_termination_workflow_corrected"))


class TestWorkflowMasterDuplicateRace(FrappeTestCase):
    """#1336: secure_document_operation() swallows the DuplicateEntryError a
    concurrent creator's race raises here and reports success=False instead
    of re-raising, so the `except frappe.exceptions.DuplicateEntryError`
    create_workflow_state_masters()/create_workflow_action_masters() relied
    on to recognise "another process just created this" was unreachable -- a
    losing racer logged a spurious "... Creation Failed" Error Log instead of
    quietly treating it as already-created.

    frappe.db.exists() is faked for exactly the (doctype, name) pair the loop
    checks, so the function still believes the row is absent and enters the
    create branch -- the window a real concurrent creator would win in --
    while every other frappe.db.exists() call (harness bookkeeping, etc.)
    passes through untouched.
    """

    def _duplicate_key_result(self, doctype, name):
        result = SecureOperationResult(False, "test_master_race")
        result.add_error(
            f"Operation failed: ('{doctype}', '{name}', "
            f"IntegrityError(1062, \"Duplicate entry '{name}' for key 'PRIMARY'\"))"
        )
        return result

    def _fake_exists_missing_for(self, doctype, name):
        real_exists = frappe.db.exists

        def _fake(dt, *args, **kwargs):
            if dt == doctype and args and args[0] == name:
                return False
            return real_exists(dt, *args, **kwargs)

        return _fake

    def test_state_master_race_is_not_logged_as_a_failure(self):
        error_log_marker = frappe.utils.now_datetime()

        with patch.object(
            frappe.db, "exists", side_effect=self._fake_exists_missing_for("Workflow State", "Executed")
        ):
            with patch.object(
                wf,
                "secure_document_operation",
                return_value=self._duplicate_key_result("Workflow State", "Executed"),
            ):
                created = wf.create_workflow_state_masters()

        self.assertEqual(created, 0)
        self.assertFalse(
            frappe.db.exists(
                "Error Log",
                {"method": "Workflow State Creation Failed", "creation": [">=", error_log_marker]},
            )
        )

    def test_action_master_race_is_not_logged_as_a_failure(self):
        error_log_marker = frappe.utils.now_datetime()

        with patch.object(
            frappe.db, "exists", side_effect=self._fake_exists_missing_for("Workflow Action Master", "Execute")
        ):
            with patch.object(
                wf,
                "secure_document_operation",
                return_value=self._duplicate_key_result("Workflow Action Master", "Execute"),
            ):
                created = wf.create_workflow_action_masters()

        self.assertEqual(created, 0)
        self.assertFalse(
            frappe.db.exists(
                "Error Log",
                {"method": "Workflow Action Creation Failed", "creation": [">=", error_log_marker]},
            )
        )

    def test_non_duplicate_state_failure_still_logs(self):
        # Control: a genuine (non-duplicate) failure must still be reported,
        # so the fix narrows the swallow to duplicate-key errors only.
        error_log_marker = frappe.utils.now_datetime()
        result = SecureOperationResult(False, "test_master_other_failure")
        result.add_error("Operation failed: PermissionError('No create permission for Workflow State')")

        with patch.object(
            frappe.db, "exists", side_effect=self._fake_exists_missing_for("Workflow State", "Executed")
        ):
            with patch.object(wf, "secure_document_operation", return_value=result):
                wf.create_workflow_state_masters()

        self.assertTrue(
            frappe.db.exists(
                "Error Log",
                {"method": "Workflow State Creation Failed", "creation": [">=", error_log_marker]},
            )
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

    def test_reports_success_and_builds_no_termination_workflow(self):
        """#1640: setup succeeds, and leaves no Membership Termination Workflow
        behind. A committed one (e.g. from an older test run) is removed inside
        the test transaction first, so the assertion is about this run."""
        if frappe.db.exists("Workflow", TERMINATION_WORKFLOW):
            frappe.delete_doc("Workflow", TERMINATION_WORKFLOW, force=1)
        # Control: supply every master a builder would need (veg11 has "Submit"),
        # so an absent workflow means "not built", not "link validation failed".
        for action in ("Submit", "Approve", "Reject", "Execute"):
            if not frappe.db.exists("Workflow Action Master", action):
                frappe.get_doc({"doctype": "Workflow Action Master", "workflow_action_name": action}).insert()

        # commit patched out (infrastructure) so the masters inserted above roll back
        with patch.object(frappe.db, "commit"):
            self.assertTrue(wf.setup_workflows_corrected())
        self.assertFalse(frappe.db.exists("Workflow", TERMINATION_WORKFLOW))

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
