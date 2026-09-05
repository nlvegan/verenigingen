# Integration tests for the TERMINATION SYSTEM SETUP cluster in
# verenigingen/setup/__init__.py
#
# Covered functions:
#   - setup_termination_system_integration()
#   - setup_termination_settings()
#   - setup_termination_workflows_and_templates()
#   - setup_termination_roles_and_permissions()
#   - setup_termination_system_manual()            (@frappe.whitelist)
#   - run_termination_diagnostics()                (@frappe.whitelist)
#
# These are install-time, idempotent setup functions guarded by
# `if not frappe.db.exists(...)` so they are safe to call repeatedly on an
# already-installed test site. Tests assert real post-conditions (Role /
# Workflow exist, settings persisted, return-dict shape) rather than
# "created N new records", and assert idempotency by running twice and
# confirming no growth.

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen import setup as setup_mod
from verenigingen.utils.constants import Roles


class TestSetupTerminationRoles(FrappeTestCase):
    """setup_termination_roles_and_permissions()"""

    def test_creates_verenigingen_administrator_role(self):
        setup_mod.setup_termination_roles_and_permissions()
        # The function's sole documented effect: the admin role must exist.
        self.assertTrue(
            frappe.db.exists("Role", Roles.VERENIGINGEN_ADMIN),
            f"Role '{Roles.VERENIGINGEN_ADMIN}' should exist after role setup",
        )

    def test_role_is_idempotent(self):
        setup_mod.setup_termination_roles_and_permissions()
        before = frappe.db.count("Role")
        setup_mod.setup_termination_roles_and_permissions()
        after = frappe.db.count("Role")
        self.assertEqual(before, after, "Re-running role setup must not create duplicate roles")

    def test_role_setup_swallows_db_errors(self):
        """The function wraps its body in try/except and only prints on
        failure (never raises). Force frappe.db.exists to blow up and assert
        the function returns None instead of propagating."""
        with patch.object(frappe.db, "exists", side_effect=RuntimeError("boom")):
            # Must not raise.
            result = setup_mod.setup_termination_roles_and_permissions()
        self.assertIsNone(result)


class TestSetupTerminationSettings(FrappeTestCase):
    """setup_termination_settings()"""

    def test_persists_existing_termination_fields(self):
        """The seed only writes fields that actually exist on the doctype
        (it guards each with hasattr). For the fields that DO exist
        (auto_cancel_sepa_mandates, auto_end_board_positions,
        send_termination_notifications) the value must be truthy after setup."""
        setup_mod.setup_termination_settings()

        from verenigingen.utils.settings_utils import get_verenigingen_settings

        settings = get_verenigingen_settings()
        meta = frappe.get_meta("Verenigingen Settings")
        live_fields = {f.fieldname for f in meta.fields}

        for field in (
            "auto_cancel_sepa_mandates",
            "auto_end_board_positions",
            "send_termination_notifications",
        ):
            self.assertIn(field, live_fields, f"{field} expected to exist on the doctype")
            self.assertTrue(
                getattr(settings, field),
                f"setup_termination_settings should leave {field} truthy",
            )

    def test_idempotent_no_new_settings_rows(self):
        """Verenigingen Settings is a Single; re-running must not error and
        must leave the single doc present."""
        setup_mod.setup_termination_settings()
        setup_mod.setup_termination_settings()
        # frappe.db.exists(dt, dt) is always truthy for a Single (#889) and
        # cannot prove the doc still has data; check get_singles_dict instead.
        self.assertTrue(
            frappe.db.get_singles_dict("Verenigingen Settings"),
            "The Verenigingen Settings single doc must still exist after re-run",
        )

    def test_early_return_when_settings_missing(self):
        """If the Verenigingen Settings single has never been saved, the
        function returns early without touching settings. Simulate the
        missing-single branch by making get_singles_dict report empty (the
        real "has this Single ever been saved" check -- frappe.db.exists(dt,
        dt) is unconditionally truthy for a Single and so cannot be used to
        simulate this branch, see #889), and assert get_verenigingen_settings
        is never reached."""
        with patch.object(frappe.db, "get_singles_dict", return_value={}):
            with patch("verenigingen.utils.settings_utils.get_verenigingen_settings") as mock_get:
                setup_mod.setup_termination_settings()
                mock_get.assert_not_called()


class TestSetupTerminationWorkflows(FrappeTestCase):
    """setup_termination_workflows_and_templates() and the workflow side of
    setup_termination_system_integration().

    NOTE: see the task report -- on this site `setup_workflows_corrected()`
    FAILS to actually persist the "Membership Termination Workflow" because
    its transitions reference a "Submit" Workflow Action Master that the setup
    never creates (link validation throws). The function nonetheless returns
    True / prints "Successfully committed". These tests therefore assert the
    *observable* behavior (runs without raising, does not duplicate state)
    rather than a workflow row that the upstream bug prevents from existing.
    """

    def test_workflow_setup_runs_without_raising(self):
        # Must not propagate any exception even though the underlying workflow
        # insert fails its link validation upstream.
        result = setup_mod.setup_termination_workflows_and_templates()
        self.assertIsNone(result)

    def test_workflows_idempotent(self):
        setup_mod.setup_termination_workflows_and_templates()
        before = frappe.db.count("Workflow")
        setup_mod.setup_termination_workflows_and_templates()
        after = frappe.db.count("Workflow")
        self.assertEqual(before, after, "Re-running workflow setup must not duplicate workflows")

    def test_import_error_branch_does_not_raise(self):
        """The function catches ImportError from the workflow module import.
        Force the import to fail and assert the function swallows it."""
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "verenigingen.setup.workflow_setup":
                raise ImportError("simulated missing module")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            # Must not raise.
            result = setup_mod.setup_termination_workflows_and_templates()
        self.assertIsNone(result)


class TestSetupTerminationSystemIntegration(FrappeTestCase):
    """setup_termination_system_integration() - the orchestrator."""

    def test_integration_creates_admin_role(self):
        setup_mod.setup_termination_system_integration()
        # The role-creation step IS reliable (unlike the workflow step, which
        # is broken upstream -- see TestSetupTerminationWorkflows note).
        self.assertTrue(
            frappe.db.exists("Role", Roles.VERENIGINGEN_ADMIN),
            "Integration setup should ensure the Verenigingen Administrator role",
        )

    def test_integration_idempotent(self):
        setup_mod.setup_termination_system_integration()
        roles_before = frappe.db.count("Role")
        workflows_before = frappe.db.count("Workflow")
        setup_mod.setup_termination_system_integration()
        self.assertEqual(roles_before, frappe.db.count("Role"))
        self.assertEqual(workflows_before, frappe.db.count("Workflow"))

    def test_integration_logs_and_swallows_errors(self):
        """The orchestrator wraps everything in try/except and logs to the
        Error Log instead of raising. Force the first step
        (setup_termination_settings) to raise and assert the function still
        returns None (does not propagate) and an error was logged."""
        with patch.object(setup_mod, "setup_termination_settings", side_effect=RuntimeError("kaboom")):
            with patch.object(frappe, "log_error") as mock_log:
                result = setup_mod.setup_termination_system_integration()
        self.assertIsNone(result)
        mock_log.assert_called_once()


class TestSetupTerminationManualEndpoint(FrappeTestCase):
    """setup_termination_system_manual() whitelisted endpoint."""

    def test_manual_setup_returns_success_dict(self):
        result = setup_mod.setup_termination_system_manual()
        self.assertIsInstance(result, dict)
        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "Termination system setup completed")
        # And the real side effect must be present.
        self.assertTrue(frappe.db.exists("Role", Roles.VERENIGINGEN_ADMIN))

    def test_manual_setup_reports_failure(self):
        """If the underlying integration raises, the endpoint returns
        success=False with the error message rather than raising."""
        with patch.object(
            setup_mod,
            "setup_termination_system_integration",
            side_effect=RuntimeError("integration exploded"),
        ):
            result = setup_mod.setup_termination_system_manual()
        self.assertIsInstance(result, dict)
        self.assertFalse(result["success"])
        self.assertIn("integration exploded", result["message"])


class TestRunTerminationDiagnostics(FrappeTestCase):
    """run_termination_diagnostics() whitelisted endpoint."""

    def setUp(self):
        super().setUp()
        # run_termination_diagnostics is gated to the DEVELOPMENT environment by
        # the API security framework (OperationType.ADMIN, allowed only in
        # development). The environment is DEVELOPMENT iff frappe.conf.developer_mode
        # is set. Dev/test sites usually have it on, but a fresh CI site does not,
        # so the call raises "Function not available in production environment".
        # Force developer_mode on for these tests (save/restore the raw key —
        # frappe.conf is a frappe._dict, so patch.object does not work on it).
        self._original_dev_mode = frappe.conf.get("developer_mode")
        frappe.conf["developer_mode"] = 1

    def tearDown(self):
        if self._original_dev_mode is None:
            frappe.conf.pop("developer_mode", None)
        else:
            frappe.conf["developer_mode"] = self._original_dev_mode
        super().tearDown()

    def test_diagnostics_returns_expected_shape(self):
        result = setup_mod.run_termination_diagnostics()
        self.assertIsInstance(result, dict)
        self.assertTrue(result["success"])
        self.assertIn("diagnostics_passed", result)
        self.assertIsInstance(result["diagnostics_passed"], bool)

    def test_diagnostics_reflect_real_workflow_absence(self):
        """On this site the Membership Termination Workflow is NOT actually
        persisted (upstream "Submit" action-master bug -- see report), even
        after running the full integration. The real doctypes and admin role
        ARE present. The diagnostics walk every check; because at least one
        workflow is missing, diagnostics_passed must be False -- and the
        function must still return a well-formed success dict."""
        setup_mod.setup_termination_system_integration()
        setup_mod.setup_termination_workflows_and_templates()

        # Sanity: the prerequisites that DO exist, so the False below is
        # attributable to the missing workflow and not to missing doctypes/role.
        self.assertTrue(frappe.db.exists("DocType", "Membership Termination Request"))
        self.assertTrue(frappe.db.exists("DocType", "Expulsion Report Entry"))
        self.assertTrue(frappe.db.exists("Role", Roles.VERENIGINGEN_ADMIN))
        self.assertFalse(
            frappe.db.exists("Workflow", "Membership Termination Workflow"),
            "Documents the upstream bug: the workflow is not persisted",
        )

        result = setup_mod.run_termination_diagnostics()
        self.assertTrue(result["success"])
        self.assertFalse(
            result["diagnostics_passed"],
            "Diagnostics must report failure while the termination workflow is absent",
        )

    def test_diagnostics_pass_when_all_entities_present(self):
        """Covers the all-good (diagnostics_passed True) branch by forcing
        every existence check the diagnostics make to report present. This
        exercises the success summary path independently of the upstream
        workflow-persistence bug."""
        with patch.object(frappe.db, "exists", return_value="dummy-name"):
            result = setup_mod.run_termination_diagnostics()
        self.assertTrue(result["success"])
        self.assertTrue(
            result["diagnostics_passed"],
            "With every required entity present, diagnostics must pass",
        )

    def test_diagnostics_fail_when_role_missing(self):
        """If the admin role is reported missing, diagnostics must flag the
        failure (diagnostics_passed False). Patch exists so the role check
        returns False while everything else stays truthy."""
        real_exists = frappe.db.exists

        def selective_exists(doctype, name=None, *args, **kwargs):
            if doctype == "Role" and name == Roles.VERENIGINGEN_ADMIN:
                return False
            return real_exists(doctype, name, *args, **kwargs)

        with patch.object(frappe.db, "exists", side_effect=selective_exists):
            result = setup_mod.run_termination_diagnostics()
        self.assertTrue(result["success"])
        self.assertFalse(
            result["diagnostics_passed"],
            "Missing admin role must make diagnostics report failure",
        )
