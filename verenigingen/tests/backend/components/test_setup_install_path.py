# Integration tests for the FRESH-INSTALL path in verenigingen/setup/__init__.py
#
# Frappe SKIPS patches on a fresh install, so anything a brand-new site needs has
# to come from execute_after_install() / get_custom_fields(). Nothing else in the
# suite exercises that ordering, and execute_after_install() swallows every
# exception into a print, so a broken step produces a site that boots but is
# missing half its reference data.
#
# These tests cover:
#   * get_custom_fields() as *installable* definitions (anchors, Link targets)
#     and the fields a fresh site must have without any patch having run.
#   * That execute_after_install() runs every step and does not mark a failed
#     run complete (#1645), and the no-Company settings case (#1647).
#   * Install-time invariants for the service user, E-Boekhouden Settings, the
#     after_migrate payment-mode top-up and the always-failing dependency
#     verifier.

import os

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen import setup as setup_mod


class TestCustomFieldsAreInstallable(FrappeTestCase):
    """get_custom_fields() must produce definitions create_custom_fields() can
    actually place correctly on a fresh site."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.custom_fields = setup_mod.get_custom_fields()

    def test_link_fields_target_existing_doctypes(self):
        """A Link whose options DocType is absent makes every save of the host
        DocType fail link validation."""
        broken = [
            (dt, f["fieldname"], f.get("options"))
            for dt, fields in self.custom_fields.items()
            for f in fields
            if f.get("fieldtype") == "Link" and not frappe.db.exists("DocType", f.get("options"))
        ]
        self.assertEqual(broken, [], f"Link custom fields pointing at missing DocTypes: {broken}")

    def test_host_doctypes_all_exist(self):
        for dt in self.custom_fields:
            self.assertTrue(frappe.db.exists("DocType", dt), f"Host DocType missing: {dt}")

    def test_insert_after_anchors_exist_on_their_host_doctype(self):
        """`insert_after` decides where a field lands in the form. A dangling
        anchor is silently ignored by Frappe, so the field is appended at an
        arbitrary position instead of the section it was designed for.

        KNOWN DEFECT: Donation.btw_exemption_type anchors to `donation_category`,
        which the Donation DocType does not have. Pinned here so a *new* dangling
        anchor fails the test, and so fixing this one is noticed.
        """
        known_broken = {("Donation", "btw_exemption_type", "donation_category")}
        broken = {
            (dt, f["fieldname"], f["insert_after"])
            for dt, fields in self.custom_fields.items()
            for f in fields
            if f.get("insert_after") and not frappe.get_meta(dt).get_field(f["insert_after"])
        }
        self.assertEqual(
            broken,
            known_broken,
            "Dangling insert_after anchors changed; new ones misplace their field",
        )

    def test_membership_procurios_id_ships_outside_the_patch(self):
        """The Procurios import's idempotency key is defined BOTH in the v15_0
        patch and in get_custom_fields(), precisely because patches are skipped on
        a fresh install. Both definitions must stay in step, and the field must be
        present on the live Membership meta.
        """
        seed = next(
            f for f in self.custom_fields["Membership"] if f["fieldname"] == "procurios_membership_id"
        )
        self.assertEqual(seed["fieldtype"], "Data")
        self.assertEqual(seed["read_only"], 1)
        self.assertEqual(seed["no_copy"], 1)
        self.assertEqual(seed["search_index"], 1)
        self.assertEqual(seed["insert_after"], "amended_from")

        df = frappe.get_meta("Membership").get_field("procurios_membership_id")
        self.assertIsNotNone(df, "A fresh site must get procurios_membership_id without the patch running")
        self.assertEqual(df.fieldtype, "Data")
        self.assertEqual(df.search_index, 1)

    def test_btw_exemption_selects_share_one_option_set(self):
        """Sales Invoice / Membership / Donation all key off the same BTW code
        list; divergence would make an invoice's exemption unrepresentable on the
        membership that produced it."""
        option_sets = {
            dt: f["options"]
            for dt, fields in self.custom_fields.items()
            for f in fields
            if f["fieldname"] == "btw_exemption_type"
        }
        self.assertEqual(set(option_sets), {"Sales Invoice", "Membership", "Donation"})
        self.assertEqual(len(set(option_sets.values())), 1, f"BTW options diverged: {option_sets}")
        codes = [c for c in next(iter(option_sets.values())).split("\n") if c]
        self.assertIn("EXEMPT_MEMBERSHIP", codes)
        self.assertIn("EXEMPT_FUNDRAISING", codes)

    def test_membership_and_donation_defaults_are_valid_options(self):
        """A default that is not in the Select options renders as an invalid
        value on every new document."""
        for dt in ("Membership", "Donation"):
            field = next(f for f in self.custom_fields[dt] if f["fieldname"] == "btw_exemption_type")
            self.assertIn(field["default"], field["options"].split("\n"))

    def test_donation_key_is_conditional_on_the_doctype(self):
        """The Donation entry is only added when the DocType exists, so the dict
        stays installable on a site without the donation module."""
        self.assertEqual("Donation" in self.custom_fields, bool(frappe.db.exists("DocType", "Donation")))


class TestExecuteAfterInstallRunsEveryStep(FrappeTestCase):
    """execute_after_install() must neither abort at one failing step (#1645) nor
    mark a half-done install complete.

    History: setup_verenigingen() activated a Domain "Verenigingen" that nothing
    ships (and no `domains` hook declares), so it raised on every fresh install
    (CI included) and the blanket handler swallowed it, skipping every later step.
    These tests drive the REAL execute_after_install(); the spies use `wraps=` so
    the real steps still run, and the one injected failure is a step raising.
    """

    LATE_STEPS = (
        "create_all_reference_data",
        "setup_membership_application_system",
        "setup_tax_exemption_on_install",
        "setup_termination_system_integration",
        "setup_workspace",
        "load_application_fixtures",
    )

    def setUp(self):
        super().setUp()
        # Mock justified: the idempotency gate. A warm site (and these very tests, which
        # run the real steps and so mark the site complete) would otherwise make every
        # later test a no-op that passes vacuously.
        from unittest import mock

        gate = mock.patch.object(setup_mod, "_is_initial_setup_complete", return_value=False)
        gate.start()
        self.addCleanup(gate.stop)

    def _spy_on(self, stack, names):
        from unittest import mock

        return {
            name: stack.enter_context(mock.patch.object(setup_mod, name, wraps=getattr(setup_mod, name)))
            for name in names
        }

    def test_setup_verenigingen_no_longer_needs_a_domain_record(self):
        self.assertFalse(frappe.db.exists("Domain", "Verenigingen"), "premise: no Domain is shipped")
        setup_mod.setup_verenigingen()  # raised LinkValidationError before #1645

    def test_every_step_after_setup_verenigingen_runs(self):
        import contextlib

        with contextlib.ExitStack() as stack:
            spies = self._spy_on(stack, self.LATE_STEPS)
            failed = setup_mod.execute_after_install()
        for name, spy in spies.items():
            self.assertTrue(spy.called, f"{name} was skipped by an earlier step's failure")
        self.assertNotIn("setup_verenigingen", failed)

    def test_a_failing_step_does_not_skip_later_steps_and_is_not_marked_done(self):
        import contextlib
        from unittest import mock

        with contextlib.ExitStack() as stack:
            spies = self._spy_on(stack, ("setup_workspace", "_mark_initial_setup_complete"))
            stack.enter_context(
                mock.patch.object(setup_mod, "create_all_reference_data", side_effect=RuntimeError("boom"))
            )
            failed = setup_mod.execute_after_install()
        self.assertIn("create reference data", failed)
        self.assertTrue(spies["setup_workspace"].called, "a later step was skipped after a failure")
        self.assertFalse(
            spies["_mark_initial_setup_complete"].called,
            "a run with a failed step was marked initial_setup_complete",
        )

    def test_a_webhook_step_reporting_failure_counts_as_failed(self):
        """The webhook / public-creator steps return {"success": False} instead of raising."""
        from unittest import mock

        with mock.patch(
            "verenigingen.setup.webhook_user_setup.setup_webhook_user",
            return_value={"success": False, "message": "nope"},
        ):
            failed = setup_mod.execute_after_install()
        self.assertIn("set up webhook user", failed)

    def test_run_complete_setup_reports_failed_steps(self):
        from unittest import mock

        with mock.patch.object(setup_mod, "setup_workspace", side_effect=RuntimeError("boom")):
            result = setup_mod.run_complete_setup()
        self.assertFalse(result["success"])
        self.assertIn("set up workspace", result["message"])


class TestSettingsWithoutACompany(FrappeTestCase):
    """#1647: on a site with no Company the mandatory `company` cannot be met."""

    def _empty_settings_single(self):
        frappe.db.delete("Singles", {"doctype": "Verenigingen Settings"})
        self.assertFalse(frappe.db.get_singles_dict("Verenigingen Settings"))

    def test_creation_is_skipped_with_a_clear_message(self):
        import contextlib
        import io
        from unittest import mock

        self._empty_settings_single()
        out = io.StringIO()
        with mock.patch("verenigingen.utils.validation_utilities.get_all_active_records", return_value=[]):
            with contextlib.redirect_stdout(out):
                result = setup_mod.create_default_verenigingen_settings()
        self.assertIsNone(result)
        self.assertIn("no Company exists yet", out.getvalue())
        self.assertFalse(frappe.db.get_singles_dict("Verenigingen Settings"), "no placeholder was saved")

    def test_public_creator_config_skips_when_settings_are_unsaved(self):
        from verenigingen.setup.public_document_creator_setup import configure_creation_user_in_settings

        self._empty_settings_single()
        result = configure_creation_user_in_settings("someone@example.com")
        self.assertTrue(result["success"])
        self.assertIn("skipped", result["message"])


class TestVerifyAppDependencies(FrappeTestCase):
    """KNOWN PRODUCTION BUG: verify_app_dependencies() imports `required_apps`
    from verenigingen.hooks, a name that hooks/__init__.py does not export. The
    ImportError is caught by its own except, so this diagnostic endpoint can
    never return anything but a failure - it is unusable for its stated purpose.
    """

    def test_required_apps_is_not_exported_by_hooks(self):
        with self.assertRaises(ImportError):
            from verenigingen.hooks import required_apps  # noqa: F401

    def test_endpoint_always_reports_failure(self):
        result = setup_mod.verify_app_dependencies()
        self.assertFalse(
            result["success"],
            "If this now succeeds the missing `required_apps` hook was added - " "update this test",
        )
        self.assertIn("required_apps", result["message"])
        self.assertNotIn("dependency_status", result)


class TestLoadApplicationFixtures(FrappeTestCase):
    """KNOWN DEAD CODE: load_application_fixtures() resolves its fixtures
    directory as `<app_path>/../fixtures`, i.e. apps/verenigingen/fixtures - one
    level above the real fixtures directory (apps/verenigingen/verenigingen/
    fixtures). Both files it looks for are absent there, so the function is a
    no-op on every install."""

    def test_resolved_fixture_directory_does_not_exist(self):
        app_path = frappe.get_app_path("verenigingen")
        resolved = os.path.normpath(os.path.join(app_path, "..", "fixtures"))
        real = os.path.join(app_path, "fixtures")
        self.assertTrue(os.path.isdir(real), "The real fixtures directory moved")
        self.assertNotEqual(resolved, real)
        self.assertFalse(os.path.isdir(resolved), f"Unexpected fixtures dir at {resolved}")

    def test_runs_as_a_noop_without_raising(self):
        self.assertIsNone(setup_mod.load_application_fixtures())


class TestBackgroundServiceUser(FrappeTestCase):
    """create_background_service_user() is the account webhooks and scheduled
    jobs authenticate as. It swallows its own failure, so its prerequisites have
    to hold or a fresh site silently ends up without the account."""

    EMAIL = "background.service@verenigingen.local"

    def test_webhook_role_exists_so_the_insert_can_succeed(self):
        """The user is created with roles=[{"role": "Verenigingen Webhook User"}].
        If that Role is missing the insert dies on link validation and the
        exception is printed, not raised."""
        self.assertTrue(frappe.db.exists("Role", "Verenigingen Webhook User"))

    def test_service_user_exists_enabled_and_carries_the_webhook_role(self):
        setup_mod.create_background_service_user()
        self.assertTrue(frappe.db.exists("User", self.EMAIL))
        user = frappe.get_doc("User", self.EMAIL)
        self.assertEqual(user.enabled, 1)
        self.assertIn("Verenigingen Webhook User", [r.role for r in user.roles])

    def test_declared_system_user_type_is_overridden_by_frappe(self):
        """KNOWN DISCREPANCY: the seed declares `"user_type": "System User"`, but
        User.validate() derives user_type from whether any assigned role grants
        desk access. "Verenigingen Webhook User" has desk_access = 0, so the
        account is silently created as a Website User instead.

        Pinned because the declared value reads as a guarantee it is not: giving
        that role desk access, or adding a desk role, would flip the account's
        type without anyone touching the setup code.
        """
        setup_mod.create_background_service_user()
        self.assertEqual(frappe.db.get_value("Role", "Verenigingen Webhook User", "desk_access"), 0)
        self.assertEqual(frappe.db.get_value("User", self.EMAIL, "user_type"), "Website User")

    def test_is_idempotent(self):
        setup_mod.create_background_service_user()
        before = frappe.db.count("User")
        setup_mod.create_background_service_user()
        self.assertEqual(frappe.db.count("User"), before)


class TestEboekhoudenSettingsSeed(FrappeTestCase):
    def test_settings_exist_with_the_seeded_api_url(self):
        # frappe.db.exists("E-Boekhouden Settings", "E-Boekhouden Settings") is
        # always truthy for a Single (see #889); check the singleton has
        # actually been saved instead.
        setup_mod.create_default_eboekhouden_settings()
        self.assertTrue(frappe.db.get_singles_dict("E-Boekhouden Settings"))
        settings = frappe.get_single("E-Boekhouden Settings")
        self.assertTrue(settings.api_url, "A fresh site needs a default API url")

    def test_is_idempotent(self):
        setup_mod.create_default_eboekhouden_settings()
        before = frappe.db.get_single_value("E-Boekhouden Settings", "api_url")
        setup_mod.create_default_eboekhouden_settings()
        self.assertEqual(
            frappe.db.get_single_value("E-Boekhouden Settings", "api_url"),
            before,
            "Re-running install must not reset a configured API url",
        )


class TestEnsureRequiredPaymentModes(FrappeTestCase):
    """after_migrate hook: the membership application form cannot submit without
    these Mode of Payment records."""

    def test_creates_nothing_new_on_a_seeded_site_and_leaves_modes_present(self):
        setup_mod.ensure_required_payment_modes()
        for mode in ("Bank Transfer", "SEPA Direct Debit"):
            self.assertTrue(frappe.db.exists("Mode of Payment", mode), f"Missing payment mode: {mode}")

    def test_is_idempotent(self):
        setup_mod.ensure_required_payment_modes()
        before = frappe.db.count("Mode of Payment")
        setup_mod.ensure_required_payment_modes()
        self.assertEqual(frappe.db.count("Mode of Payment"), before)
