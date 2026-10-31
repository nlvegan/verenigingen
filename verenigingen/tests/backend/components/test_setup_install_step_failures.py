# #1662: an install step that fails must reach execute_after_install's failed-step list.
#
# Before the fix, several steps caught their own exception and only printed, so the
# runner (_run_install_step, which only sees exceptions) reported a clean install.
#
# Stand-in, said plainly: a test site already holds every seed row, so the "create"
# branch never runs. `_fresh_site_refusing` therefore (a) makes frappe.db.exists /
# get_singles_dict answer "not there" for ONE doctype and (b) makes Document.insert raise
# for it. The step's own code, its own handler and the runner are all REAL; only the
# framework boundary (does the row exist / will the insert succeed) is stood in for.
# Nothing is deleted, so nothing the install commits can make a seed row vanish.

import contextlib
from unittest import mock

import frappe
from frappe.model.document import Document
from frappe.tests.utils import FrappeTestCase

from verenigingen import setup as setup_mod


@contextlib.contextmanager
def _fresh_site_refusing(doctype, name=None):
    """`doctype` (optionally one row, `name`) looks absent and its insert is refused."""
    real_insert = Document.insert
    real_exists = frappe.db.exists
    real_singles = frappe.db.get_singles_dict

    def _is_target(dt, dn=None):
        return dt == doctype and (name is None or dn is None or dn == name)

    def insert(self, *args, **kwargs):
        if self.doctype == doctype and (name is None or self.get("name") == name or name in vars(self).values()):
            raise frappe.ValidationError(f"refused insert of {self.doctype} (test)")
        return real_insert(self, *args, **kwargs)

    def exists(dt, dn=None, *args, **kwargs):
        if isinstance(dt, str) and _is_target(dt, dn if isinstance(dn, str) else None):
            return None
        return real_exists(dt, dn, *args, **kwargs)

    def singles(dt, *args, **kwargs):
        return {} if dt == doctype else real_singles(dt, *args, **kwargs)

    with mock.patch.object(Document, "insert", insert), mock.patch.object(
        frappe.db, "exists", exists
    ), mock.patch.object(frappe.db, "get_singles_dict", singles):
        yield


class TestInstallStepsSurfaceTheirFailures(FrappeTestCase):
    def setUp(self):
        super().setUp()
        # Mock justified: the idempotency gate; a warm site would make every run a no-op.
        # The public-creator step commits users and has its own tests.
        for patcher in (
            mock.patch.object(setup_mod, "_is_initial_setup_complete", return_value=False),
            mock.patch.object(setup_mod, "_install_public_document_creator"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _run(self, refused_doctype, name=None):
        """Run the REAL execute_after_install; return (failed, was_flag_set)."""
        with mock.patch.object(setup_mod, "_mark_initial_setup_complete") as mark:
            with _fresh_site_refusing(refused_doctype, name):
                failed = setup_mod.execute_after_install()
        return failed, mark.called

    def _assert_step_failed(self, label, refused_doctype, name=None):
        failed, flag_set = self._run(refused_doctype, name)
        self.assertIn(label, failed)
        self.assertFalse(flag_set, "a run with a failed step was marked initial_setup_complete")

    def test_eboekhouden_settings(self):
        self._assert_step_failed("create E-Boekhouden Settings", "E-Boekhouden Settings")

    def test_each_reference_data_helper(self):
        for doctype in ("Membership Type", "Team Role", "Team", "Region", "Mode of Payment", "Item"):
            with self.subTest(doctype=doctype):
                self._assert_step_failed("create reference data", doctype)

    def test_reference_data_background_service_user(self):
        self._assert_step_failed("create reference data", "User", "background.service@verenigingen.local")

    def test_one_failing_helper_does_not_skip_the_later_ones(self):
        import functools

        calls = []
        real = setup_mod.create_background_service_user

        @functools.wraps(real)
        def spy():
            calls.append("service user")
            return real()

        with mock.patch.object(setup_mod, "create_background_service_user", spy):
            with _fresh_site_refusing("Region"):
                with self.assertRaises(RuntimeError) as ctx:
                    setup_mod.create_all_reference_data()
        self.assertEqual(calls, ["service user"], "a helper after the failing one was skipped")
        self.assertIn("create_default_regions", str(ctx.exception))

    def test_membership_application_basic_templates(self):
        self._assert_step_failed("set up membership application system", "Email Template")

    def test_basic_application_templates_alone_raise(self):
        """The other two template creators also raise under this refusal, so the step-level
        test above would pass even if this loop still swallowed; pin the loop itself."""
        with _fresh_site_refusing("Email Template"):
            with self.assertRaises(RuntimeError) as ctx:
                setup_mod.create_application_email_templates()
        self.assertIn("membership_application_confirmation", str(ctx.exception))

    def test_termination_roles(self):
        self._assert_step_failed("set up termination system", "Role", "Verenigingen Administrator")

    def test_termination_workflow_setup_raising_is_a_failure(self):
        with mock.patch(
            "verenigingen.setup.workflow_setup.setup_workflows_corrected", side_effect=RuntimeError("boom")
        ):
            failed = setup_mod.execute_after_install()
        self.assertIn("set up termination system", failed)

    def test_a_false_workflow_result_is_benign_on_a_healthy_site(self):
        """Control for the opposite harm: False is what a healthy site returns (the appeals
        DocType is not built), so it must NOT fail the step."""
        with mock.patch("verenigingen.setup.workflow_setup.setup_workflows_corrected", return_value=False):
            failed = setup_mod.execute_after_install()
        self.assertNotIn("set up termination system", failed)

    def test_comprehensive_email_templates_reporting_failure(self):
        """It returns OperationResult.fail on a failed run instead of raising."""
        from verenigingen.utils.operation_result import OperationResult

        with mock.patch(
            "verenigingen.api.email_template_manager.create_comprehensive_email_templates",
            return_value=OperationResult.fail(message="nope", errors=["boom"]),
        ), mock.patch.object(setup_mod, "_mark_initial_setup_complete") as mark:
            failed = setup_mod.execute_after_install()
        self.assertIn("set up membership application system", failed)
        self.assertFalse(mark.called)

    def test_tax_exemption(self):
        enabled = frappe._dict(tax_exempt_for_contributions=1)
        with mock.patch("verenigingen.utils.settings_utils.get_verenigingen_settings", return_value=enabled):
            with mock.patch("verenigingen.utils.setup_dutch_tax_exemption", side_effect=RuntimeError("boom")):
                with mock.patch.object(setup_mod, "_mark_initial_setup_complete") as mark:
                    failed = setup_mod.execute_after_install()
        self.assertIn("set up tax exemption templates", failed)
        self.assertFalse(mark.called)

    def test_termination_failure_is_logged_with_the_cause(self):
        """The swapped log_error put the label in the `error` column and the cause in the
        title; the runner's keyword call records the traceback, which names the cause."""
        flt = {"method": ["like", "%install step failed: set up termination%"]}
        before = frappe.db.count("Error Log", flt)
        self._run("Role", "Verenigingen Administrator")
        rows = frappe.get_all("Error Log", filters=flt, fields=["error"], order_by="creation desc")
        self.assertGreater(len(rows), before)
        self.assertIn("refused insert of Role", rows[0].error)


class TestHealthySiteStillInstallsTwice(FrappeTestCase):
    """Opposite harm: removing the swallows must not fail a healthy install, first or re-run."""

    def setUp(self):
        super().setUp()
        for patcher in (
            mock.patch.object(setup_mod, "_is_initial_setup_complete", return_value=False),
            mock.patch.object(setup_mod, "_install_public_document_creator"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_two_consecutive_installs_report_no_failed_step(self):
        self.assertEqual(setup_mod.execute_after_install(), [])
        self.assertEqual(setup_mod.execute_after_install(), [])
