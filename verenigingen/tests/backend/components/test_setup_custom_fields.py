# Integration tests for the custom-field + app-setup-orchestration cluster of
# verenigingen/setup/__init__.py.
#
# Covered functions:
#   - get_custom_fields()                  (the big definition dict)
#   - make_custom_fields(update=True)      (installs the dict via create_custom_fields)
#   - create_eboekhouden_custom_fields()   (now a no-op informational stub)
#   - make_custom_records()                (Party Type / Customer Group / Item seeds)
#   - validate_app_dependencies()          (required-app check; swallows failures)
#   - _is_initial_setup_complete()         (reads Verenigingen Settings flag)
#   - _mark_initial_setup_complete()       (sets the flag)
#   - execute_after_install() early-return guard ONLY (never run end-to-end)
#
# These are install-time, idempotent functions. On an installed test site the
# custom fields / seed records already exist, so the assertions focus on the
# *post-condition* (the field exists with the expected fieldtype/options) and on
# idempotency (calling twice does not duplicate or error).

import contextlib
import io

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen import setup as setup_mod


class TestGetCustomFields(FrappeTestCase):
    """The get_custom_fields() definition dict — structure assertions."""

    def test_returns_dict_keyed_by_doctype(self):
        cf = setup_mod.get_custom_fields()
        self.assertIsInstance(cf, dict)
        # Always-present keys (Donation is conditional, asserted separately).
        for dt in ["Company", "Customer", "Sales Invoice", "Membership"]:
            self.assertIn(dt, cf)
            self.assertIsInstance(cf[dt], list)
            self.assertGreater(len(cf[dt]), 0)

    def test_customer_donor_field_definition(self):
        cf = setup_mod.get_custom_fields()
        donor = next(f for f in cf["Customer"] if f["fieldname"] == "donor")
        self.assertEqual(donor["fieldtype"], "Link")
        self.assertEqual(donor["options"], "Donor")
        self.assertEqual(donor["insert_after"], "customer_group")

    def test_sales_invoice_btw_fields_present(self):
        cf = setup_mod.get_custom_fields()
        fieldnames = {f["fieldname"] for f in cf["Sales Invoice"]}
        for fn in [
            "exempt_from_tax",
            "btw_exemption_type",
            "btw_exemption_reason",
            "btw_reporting_category",
            "custom_donation_section",
            "custom_source_donation",
        ]:
            self.assertIn(fn, fieldnames)

    def test_sales_invoice_btw_exemption_type_options_match_btw_codes(self):
        """The Select options for btw_exemption_type must enumerate the BTW
        code keys, leading-newline-prefixed (empty first choice)."""
        cf = setup_mod.get_custom_fields()
        sel = next(f for f in cf["Sales Invoice"] if f["fieldname"] == "btw_exemption_type")
        self.assertEqual(sel["fieldtype"], "Select")
        options = sel["options"].split("\n")
        # leading "" then the seven BTW code keys
        self.assertEqual(options[0], "")
        expected_codes = {
            "EXEMPT_NONPROFIT",
            "EXEMPT_MEMBERSHIP",
            "EXEMPT_FUNDRAISING",
            "EXEMPT_SMALL_BUSINESS",
            "OUTSIDE_SCOPE",
            "EXEMPT_WITH_INPUT",
            "EXEMPT_NO_INPUT",
        }
        self.assertEqual(set(o for o in options if o), expected_codes)

    def test_source_donation_field_definition(self):
        cf = setup_mod.get_custom_fields()
        src = next(f for f in cf["Sales Invoice"] if f["fieldname"] == "custom_source_donation")
        self.assertEqual(src["fieldtype"], "Link")
        self.assertEqual(src["options"], "Donation")

    def test_membership_btw_exemption_type_default(self):
        cf = setup_mod.get_custom_fields()
        m = next(f for f in cf["Membership"] if f["fieldname"] == "btw_exemption_type")
        self.assertEqual(m["fieldtype"], "Select")
        self.assertEqual(m["default"], "EXEMPT_MEMBERSHIP")
        self.assertEqual(m["insert_after"], "membership_type")

    def test_company_section_break_definition(self):
        cf = setup_mod.get_custom_fields()
        sec = cf["Company"][0]
        self.assertEqual(sec["fieldname"], "verenigingen_section")
        self.assertEqual(sec["fieldtype"], "Section Break")
        self.assertEqual(int(sec["collapsible"]), 1)

    def test_donation_key_present_when_doctype_exists(self):
        """The Donation key is added only if the Donation DocType exists.
        On this site Donation exists, so the key (with its default
        EXEMPT_FUNDRAISING) must be present."""
        if not frappe.db.exists("DocType", "Donation"):
            self.skipTest("Donation DocType not installed on this site")
        cf = setup_mod.get_custom_fields()
        self.assertIn("Donation", cf)
        d = next(f for f in cf["Donation"] if f["fieldname"] == "btw_exemption_type")
        self.assertEqual(d["default"], "EXEMPT_FUNDRAISING")
        self.assertEqual(d["insert_after"], "donation_category")


class TestMakeCustomFields(FrappeTestCase):
    """make_custom_fields() installs the get_custom_fields() dict as real
    Custom Field rows."""

    def test_installs_expected_custom_fields(self):
        setup_mod.make_custom_fields(update=True)
        expected = [
            ("Customer", "donor", "Link", "Donor"),
            ("Sales Invoice", "exempt_from_tax", "Check", None),
            ("Sales Invoice", "btw_exemption_type", "Select", None),
            ("Sales Invoice", "custom_source_donation", "Link", "Donation"),
            ("Membership", "btw_exemption_type", "Select", None),
            ("Company", "verenigingen_section", "Section Break", None),
        ]
        for dt, fieldname, fieldtype, options in expected:
            cf_name = frappe.db.exists("Custom Field", {"dt": dt, "fieldname": fieldname})
            self.assertTrue(cf_name, f"Custom Field {dt}.{fieldname} should exist")
            row = frappe.db.get_value(
                "Custom Field",
                {"dt": dt, "fieldname": fieldname},
                ["fieldtype", "options"],
                as_dict=True,
            )
            self.assertEqual(row.fieldtype, fieldtype, f"{dt}.{fieldname} fieldtype")
            if options is not None:
                self.assertEqual(row.options, options, f"{dt}.{fieldname} options")

    def test_donor_field_links_to_donor_doctype(self):
        setup_mod.make_custom_fields(update=True)
        options = frappe.db.get_value(
            "Custom Field", {"dt": "Customer", "fieldname": "donor"}, "options"
        )
        self.assertEqual(options, "Donor")

    def test_make_custom_fields_idempotent(self):
        """Running the installer twice must not create duplicate Custom Field
        rows for the same (dt, fieldname)."""
        setup_mod.make_custom_fields(update=True)
        before = frappe.db.count("Custom Field")
        setup_mod.make_custom_fields(update=True)
        after = frappe.db.count("Custom Field")
        self.assertEqual(before, after)
        # Spot-check that a representative field is still single-rowed.
        rows = frappe.get_all(
            "Custom Field", filters={"dt": "Sales Invoice", "fieldname": "btw_exemption_type"}
        )
        self.assertEqual(len(rows), 1)


class TestMakeCustomRecords(FrappeTestCase):
    """make_custom_records() seeds Party Type, Customer Group, and the
    DONATION item (after ensuring prerequisites)."""

    def test_seeds_party_type_and_donation_item(self):
        setup_mod.make_custom_records()
        self.assertTrue(frappe.db.exists("Party Type", "Member"))
        self.assertEqual(
            frappe.db.get_value("Party Type", "Member", "account_type"), "Receivable"
        )
        self.assertTrue(frappe.db.exists("Customer Group", "Donors"))
        self.assertTrue(frappe.db.exists("Item", "DONATION"))
        donation = frappe.get_doc("Item", "DONATION")
        self.assertEqual(int(donation.is_stock_item), 0)
        self.assertEqual(int(donation.is_sales_item), 1)

    def test_make_custom_records_idempotent(self):
        setup_mod.make_custom_records()
        before_items = frappe.db.count("Item")
        before_party = frappe.db.count("Party Type")
        setup_mod.make_custom_records()
        self.assertEqual(frappe.db.count("Item"), before_items)
        self.assertEqual(frappe.db.count("Party Type"), before_party)


class TestEboekhoudenCustomFields(FrappeTestCase):
    """create_eboekhouden_custom_fields() is now an informational no-op stub
    (fields moved to fixtures). It must run without error."""

    def test_runs_without_error(self):
        # No return value / no side effects expected; just must not raise.
        result = setup_mod.create_eboekhouden_custom_fields()
        self.assertIsNone(result)


class TestValidateAppDependencies(FrappeTestCase):
    """validate_app_dependencies() checks required apps but deliberately
    swallows any failure (it must never abort an install)."""

    def test_does_not_raise_even_with_missing_apps(self):
        # 'banking' is generally NOT installed on the test site; the function
        # internally frappe.throw()s for missing apps but catches it and only
        # prints a warning, so the call must return without raising.
        try:
            result = setup_mod.validate_app_dependencies()
        except Exception as e:  # pragma: no cover - this is the failure we guard against
            self.fail(f"validate_app_dependencies must not raise, but raised: {e}")
        # The function has no explicit return value.
        self.assertIsNone(result)

    def test_reports_banking_as_missing_when_not_installed(self):
        """Assert validate_app_dependencies() actually DETECTS a missing required
        app. When 'banking' is absent the function frappe.throw()s internally,
        catches it, and prints a warning naming the missing app to stdout. We
        capture stdout and assert the warning fired and mentions 'banking'.

        If 'banking' is installed on this site there is nothing to detect, so the
        test skips rather than asserting a vacuous truth."""
        if "banking" in frappe.get_installed_apps():
            self.skipTest("'banking' is installed on this site; missing-app branch not exercisable")

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            result = setup_mod.validate_app_dependencies()
        output = buffer.getvalue()

        # The function must stay non-fatal (the throw is swallowed).
        self.assertIsNone(result)
        # It must have reported the dependency problem and named the missing app.
        self.assertIn("Warning", output, f"expected a warning on stdout, got: {output!r}")
        self.assertIn("banking", output, f"missing 'banking' app should be named in the warning: {output!r}")


class TestInitialSetupCompleteFlag(FrappeTestCase):
    """_is_initial_setup_complete() / _mark_initial_setup_complete() manage the
    Verenigingen Settings.initial_setup_complete flag used to make
    execute_after_install() idempotent."""

    def setUp(self):
        # Preserve the live flag so this test never permanently changes install
        # state on the shared test site.
        self._had_settings = bool(
            frappe.db.exists("Verenigingen Settings", "Verenigingen Settings")
        )
        if self._had_settings:
            self._original_flag = frappe.db.get_value(
                "Verenigingen Settings", "Verenigingen Settings", "initial_setup_complete"
            )
        else:
            self._original_flag = None

    def tearDown(self):
        if self._had_settings:
            frappe.db.set_value(
                "Verenigingen Settings",
                "Verenigingen Settings",
                "initial_setup_complete",
                self._original_flag,
            )
            frappe.db.commit()

    def test_mark_then_is_complete_roundtrip(self):
        if not self._had_settings:
            self.skipTest("Verenigingen Settings single doc not present on this site")
        # Force the flag off, confirm reader sees False.
        frappe.db.set_value(
            "Verenigingen Settings", "Verenigingen Settings", "initial_setup_complete", 0
        )
        frappe.db.commit()
        self.assertFalse(setup_mod._is_initial_setup_complete())

        # Mark complete, confirm reader sees True.
        setup_mod._mark_initial_setup_complete()
        self.assertTrue(setup_mod._is_initial_setup_complete())

    def test_is_complete_returns_bool(self):
        result = setup_mod._is_initial_setup_complete()
        self.assertIsInstance(result, bool)


class TestExecuteAfterInstallGuard(FrappeTestCase):
    """execute_after_install() must short-circuit (do nothing heavy) when
    initial setup is already complete. We assert ONLY the early-return guard —
    we never run the real install."""

    def test_early_return_when_already_complete(self):
        # Patch the completion check to report "already done" so the function
        # short-circuits at its very first statement. This proves the guard is
        # wired up without mutating the site. (Mocking is used solely to steer
        # control flow into the early-return branch, not to fake business logic.)
        import unittest.mock as mock

        with mock.patch.object(setup_mod, "_is_initial_setup_complete", return_value=True):
            # If the guard works, this returns immediately and raises nothing.
            # If the guard were removed, this would attempt a full site install
            # and very likely raise / mutate state — so a regression fails here.
            with mock.patch.object(setup_mod, "validate_app_dependencies") as guarded:
                setup_mod.execute_after_install()
                # The first heavy step after the guard must NOT have been reached.
                guarded.assert_not_called()
