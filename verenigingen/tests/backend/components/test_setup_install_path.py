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
#   * The abort behaviour of execute_after_install() and the step that currently
#     triggers it (setup_verenigingen -> missing "Verenigingen" Domain record).
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


class TestExecuteAfterInstallAborts(FrappeTestCase):
    """execute_after_install() wraps every step in one try/except.

    KNOWN PRODUCTION BUG: setup_verenigingen() appends "Verenigingen" to
    Domain Settings.active_domains, but the app ships no `Domain` fixture and
    nothing creates that record, so the save fails link validation. The blanket
    handler swallows it, which means everything AFTER setup_verenigingen() in
    execute_after_install() never runs on a brand-new site:
    create_all_reference_data(), setup_membership_application_system(),
    setup_tax_exemption_on_install(), setup_termination_system_integration(),
    setup_workspace(), load_application_fixtures(), the security/webhook/
    public-document-creator setup, and _mark_initial_setup_complete().
    """

    def test_domain_record_is_not_shipped(self):
        self.assertFalse(
            frappe.db.exists("Domain", "Verenigingen"),
            "If the Domain record now exists the upstream bug was fixed - update " "these tests",
        )

    def test_setup_verenigingen_raises_without_the_domain_record(self):
        with self.assertRaises(frappe.LinkValidationError):
            setup_mod.setup_verenigingen()

    def test_execute_after_install_swallows_the_failure(self):
        """It must not propagate (that would abort `bench install-app`), but it
        also reports nothing to the caller - hence the silent half-install.

        Asserts an OBSERVABLE post-condition, not the return value: an earlier
        version did `assertIsNone(execute_after_install())`, which cannot fail
        because the function has no `return <value>` on any path. It was also
        non-deterministic — `execute_after_install` early-returns when
        `_is_initial_setup_complete()`, so on a seeded site it was a pure no-op
        that still went green.
        """
        if setup_mod._is_initial_setup_complete():
            self.skipTest("setup already marked complete on this site; the abort path is unreachable")

        setup_mod.execute_after_install()

        # It aborted on the Domain step, so it never reached
        # _mark_initial_setup_complete() at the end of the sequence.
        self.assertFalse(
            setup_mod._is_initial_setup_complete(),
            "execute_after_install() completed despite the Domain abort - the "
            "silent half-install this test documents no longer happens, so "
            "re-verify the rest of this class.",
        )

    def test_run_complete_setup_reports_success_despite_the_abort(self):
        """The whitelisted wrapper only sees "no exception" and reports success,
        so an operator re-running setup gets a green result for a run that
        stopped at step four.

        `assertTrue(result["success"])` alone would be a test of a literal —
        run_complete_setup() returns {"success": True} unconditionally because
        execute_after_install() has its own blanket except. So the point is the
        CONTRADICTION: success is reported while setup demonstrably did not
        complete.
        """
        if setup_mod._is_initial_setup_complete():
            self.skipTest("setup already marked complete on this site; the abort path is unreachable")

        result = setup_mod.run_complete_setup()

        self.assertTrue(result["success"])
        self.assertFalse(
            setup_mod._is_initial_setup_complete(),
            "run_complete_setup() reported success AND setup actually completed - "
            "the misreporting this test documents is gone.",
        )


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
        setup_mod.create_default_eboekhouden_settings()
        self.assertTrue(frappe.db.exists("E-Boekhouden Settings", "E-Boekhouden Settings"))
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
