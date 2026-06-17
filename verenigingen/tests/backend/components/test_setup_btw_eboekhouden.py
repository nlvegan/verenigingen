# Integration tests for the BTW (Dutch VAT) / eBoekhouden / tax-settings
# install helpers in verenigingen/setup/__init__.py.
#
# These exercise install-time idempotent functions against a real site database:
#   - install_missing_btw_fields()  -> creates BTW Custom Fields
#   - verify_btw_installation()     -> read-only status verifier
#   - fix_btw_installation()        -> reinstall fields + optional tax templates
#   - create_default_eboekhouden_settings() -> seeds the E-Boekhouden Settings single
#   - setup_tax_exemption_on_install()      -> conditional tax-template setup
#
# Strategy: these are idempotent install helpers guarded by create_custom_fields(
# update=True) or `if not exists`. On an installed test site the fields/records
# may already exist, so we assert on the *post-condition* (field/record exists,
# verifier reports installed) rather than "N created". Idempotency is asserted by
# running twice and confirming counts do not grow.

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen import setup as setup_mod

# The BTW custom fields the install helper is contractually required to create.
# (doctype, fieldname) pairs mirror verify_btw_installation's required_fields list
# plus the reporting-category field the Sales Invoice install adds.
_BTW_FIELDS = [
    ("Sales Invoice", "btw_exemption_type"),
    ("Sales Invoice", "btw_exemption_reason"),
    ("Sales Invoice", "btw_reporting_category"),
    ("Membership", "btw_exemption_type"),
]


class TestInstallMissingBtwFields(FrappeTestCase):
    """install_missing_btw_fields() must materialize the BTW custom fields."""

    def test_install_creates_all_btw_fields(self):
        result = setup_mod.install_missing_btw_fields()
        self.assertTrue(result, "install_missing_btw_fields should return True on success")
        for doctype, fieldname in _BTW_FIELDS:
            self.assertTrue(
                frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": fieldname}),
                f"Custom Field {doctype}.{fieldname} should exist after install",
            )

    def test_installed_sales_invoice_btw_type_is_select(self):
        """The Sales Invoice BTW exemption type must be installed as a Select
        carrying the Dutch BTW codes (i.e. real field config, not a stub)."""
        setup_mod.install_missing_btw_fields()
        cf_name = frappe.db.get_value(
            "Custom Field", {"dt": "Sales Invoice", "fieldname": "btw_exemption_type"}, "name"
        )
        self.assertIsNotNone(cf_name)
        cf = frappe.get_doc("Custom Field", cf_name)
        self.assertEqual(cf.fieldtype, "Select")
        # Options come from BTW_CODES keys in get_custom_fields().
        self.assertIn("EXEMPT_MEMBERSHIP", cf.options)
        self.assertIn("EXEMPT_NONPROFIT", cf.options)

    def test_membership_btw_field_has_default(self):
        """The Membership BTW field must default to EXEMPT_MEMBERSHIP."""
        setup_mod.install_missing_btw_fields()
        default = frappe.db.get_value(
            "Custom Field", {"dt": "Membership", "fieldname": "btw_exemption_type"}, "default"
        )
        self.assertEqual(default, "EXEMPT_MEMBERSHIP")

    def test_install_is_idempotent(self):
        """Re-running install must not create duplicate Custom Fields."""
        setup_mod.install_missing_btw_fields()
        before = frappe.db.count("Custom Field")
        result = setup_mod.install_missing_btw_fields()
        after = frappe.db.count("Custom Field")
        self.assertTrue(result)
        self.assertEqual(before, after, "install_missing_btw_fields must be idempotent")


class TestVerifyBtwInstallation(FrappeTestCase):
    """verify_btw_installation() is a read-only status verifier."""

    def test_reports_all_good_after_install(self):
        setup_mod.install_missing_btw_fields()
        result = setup_mod.verify_btw_installation()
        self.assertIsInstance(result, dict)
        self.assertEqual(result["status"], "All Good")
        self.assertIn("message", result)
        # When all good there should be no missing_fields key in the payload.
        self.assertNotIn("missing_fields", result)

    def test_reports_missing_when_field_absent(self):
        """If a required BTW field is deleted, the verifier must report it as
        missing with the exact 'doctype.fieldname' token. This guards the
        verifier's detection logic (would regress to a false 'All Good')."""
        setup_mod.install_missing_btw_fields()
        cf_name = frappe.db.get_value(
            "Custom Field", {"dt": "Sales Invoice", "fieldname": "btw_reporting_category"}, "name"
        )
        self.assertIsNotNone(cf_name)
        try:
            frappe.delete_doc("Custom Field", cf_name, force=True, ignore_permissions=True)
            frappe.db.commit()
            result = setup_mod.verify_btw_installation()
            self.assertEqual(result["status"], "Missing Fields")
            self.assertIn("Sales Invoice.btw_reporting_category", result["missing_fields"])
            self.assertEqual(len(result["missing_fields"]), 1)
        finally:
            # Restore so we don't leave the site in a broken state.
            setup_mod.install_missing_btw_fields()
            frappe.db.commit()
        # After restore the verifier must be green again.
        self.assertEqual(setup_mod.verify_btw_installation()["status"], "All Good")


class TestFixBtwInstallation(FrappeTestCase):
    """fix_btw_installation() reinstalls BTW fields (and optional templates)."""

    def test_fix_reinstalls_missing_field(self):
        """fix_btw_installation should repair a deleted BTW field so that the
        verifier reports All Good afterwards."""
        setup_mod.install_missing_btw_fields()
        cf_name = frappe.db.get_value(
            "Custom Field", {"dt": "Membership", "fieldname": "btw_exemption_type"}, "name"
        )
        self.assertIsNotNone(cf_name)
        frappe.delete_doc("Custom Field", cf_name, force=True, ignore_permissions=True)
        frappe.db.commit()
        self.assertFalse(
            frappe.db.exists("Custom Field", {"dt": "Membership", "fieldname": "btw_exemption_type"})
        )

        result = setup_mod.fix_btw_installation()
        self.assertTrue(result, "fix_btw_installation should return True on success")
        self.assertTrue(
            frappe.db.exists("Custom Field", {"dt": "Membership", "fieldname": "btw_exemption_type"}),
            "fix_btw_installation must recreate the deleted BTW field",
        )
        self.assertEqual(setup_mod.verify_btw_installation()["status"], "All Good")

    def test_fix_is_idempotent(self):
        setup_mod.fix_btw_installation()
        before = frappe.db.count("Custom Field")
        result = setup_mod.fix_btw_installation()
        after = frappe.db.count("Custom Field")
        self.assertTrue(result)
        self.assertEqual(before, after, "fix_btw_installation must be idempotent")


class TestCreateDefaultEboekhoudenSettings(FrappeTestCase):
    """create_default_eboekhouden_settings() seeds the single doc."""

    def test_settings_single_exists_after_seed(self):
        setup_mod.create_default_eboekhouden_settings()
        self.assertTrue(
            frappe.db.exists("E-Boekhouden Settings", "E-Boekhouden Settings"),
            "E-Boekhouden Settings single should exist after seeding",
        )

    def test_seed_is_idempotent(self):
        # E-Boekhouden Settings is a Single doctype: it has no table, so
        # frappe.db.count is invalid. Idempotency means the second call is a
        # no-op (guarded by `if not exists`) and the single still resolves.
        setup_mod.create_default_eboekhouden_settings()
        self.assertTrue(frappe.db.exists("E-Boekhouden Settings", "E-Boekhouden Settings"))
        setup_mod.create_default_eboekhouden_settings()
        self.assertTrue(frappe.db.exists("E-Boekhouden Settings", "E-Boekhouden Settings"))

    def test_seed_does_not_clobber_existing_source_application(self):
        """Seeding is guarded by `if not exists`, so on an already-installed
        site (where the single doc is present) the seed must be a no-op and NOT
        reset an operator-configured value back to the default."""
        setup_mod.create_default_eboekhouden_settings()
        # Use set_value to write the field directly: the Single has mandatory
        # fields (api_token, default_company) that a full save() would demand,
        # which is orthogonal to what we're testing here (the no-clobber guard).
        frappe.db.set_value(
            "E-Boekhouden Settings",
            "E-Boekhouden Settings",
            "source_application",
            "Operator Configured Value",
        )
        frappe.db.commit()

        # Re-running the seed must not overwrite the operator's value.
        setup_mod.create_default_eboekhouden_settings()
        self.assertEqual(
            frappe.db.get_single_value("E-Boekhouden Settings", "source_application"),
            "Operator Configured Value",
        )


class TestSetupTaxExemptionOnInstall(FrappeTestCase):
    """setup_tax_exemption_on_install() is conditional on the settings flag."""

    def test_runs_without_error_using_live_setting(self):
        """The function reads the live tax_exempt_for_contributions flag and
        either sets up templates or no-ops. Either way it must not raise:
        it swallows errors and logs them. We assert it completes and that the
        settings single still exists (i.e. it didn't corrupt config)."""
        # Should be safe to call regardless of the flag's current value.
        setup_mod.setup_tax_exemption_on_install()
        self.assertTrue(frappe.db.exists("Verenigingen Settings", "Verenigingen Settings"))

    def test_sets_up_templates_when_flag_enabled(self):
        """When tax_exempt_for_contributions is enabled, the install helper must
        invoke the Dutch tax-exemption setup, which creates one
        'Sales Taxes and Charges Template' per BTW exemption code (named
        'BTW <CODE> - <abbr>'). We toggle the flag, run, then assert the template
        table grew (or stayed level if already seeded) AND that at least one
        concrete BTW exemption template now exists, then restore the flag."""
        from verenigingen.utils.settings_utils import get_verenigingen_settings

        settings = get_verenigingen_settings()
        original = settings.get("tax_exempt_for_contributions")
        try:
            self._enable_tax_exemption_flag()
            count_before = frappe.db.count("Sales Taxes and Charges Template")
            setup_mod.setup_tax_exemption_on_install()
            count_after = frappe.db.count("Sales Taxes and Charges Template")

            # The handler is idempotent: it only ever adds templates, never deletes.
            self.assertGreaterEqual(
                count_after,
                count_before,
                "exemption setup must not remove existing tax templates",
            )
            # A concrete artifact: the handler creates a 'BTW <CODE>' template for
            # each BTW exemption code (e.g. BTW EXEMPT_MEMBERSHIP - <abbr>).
            btw_templates = frappe.get_all(
                "Sales Taxes and Charges Template",
                filters=[["title", "like", "BTW %"]],
                pluck="name",
            )
            self.assertTrue(
                btw_templates,
                "Dutch tax-exemption setup should have created at least one "
                f"'BTW <CODE>' Sales Taxes and Charges Template; found none. Templates: "
                f"{frappe.get_all('Sales Taxes and Charges Template', pluck='name')}",
            )
            # The flag we enabled must still be set (function shouldn't flip it).
            refreshed = get_verenigingen_settings()
            self.assertTrue(refreshed.get("tax_exempt_for_contributions"))
        finally:
            self._restore_tax_exemption_flag(original)

    # ----- helpers (ignore_permissions confined here) -----------------------

    def _enable_tax_exemption_flag(self):
        frappe.db.set_value(
            "Verenigingen Settings",
            "Verenigingen Settings",
            "tax_exempt_for_contributions",
            1,
        )
        frappe.db.commit()

    def _restore_tax_exemption_flag(self, value):
        frappe.db.set_value(
            "Verenigingen Settings",
            "Verenigingen Settings",
            "tax_exempt_for_contributions",
            1 if value else 0,
        )
        frappe.db.commit()
