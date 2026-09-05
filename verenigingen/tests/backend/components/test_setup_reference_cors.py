# Integration tests for the reference-data / CORS / payment-mode / manual-wrapper
# functions in verenigingen/setup/__init__.py.
#
# These exercise the install/migrate seed functions against a real site database.
# All of the seed functions are guarded by `if not frappe.db.exists(...)` (or are
# otherwise recovery/idempotent), so they are safe to call repeatedly on an
# already-installed test site. Tests assert on the *post-condition* (record exists /
# wrapper returns the documented shape) and on idempotency (calling twice does not
# grow the table), never on "created N new records" (the records already exist on an
# installed test site).
#
# IMPORTANT (documented production behaviour, NOT asserted as desired):
#  - configure_website_cors() writes CORS fields that do not exist on the Website
#    Settings doctype in this Frappe version. Frappe silently drops unknown fields,
#    so the call succeeds but persists nothing. The tests only assert it runs without
#    raising and is idempotent.

from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen import setup as setup_mod


class TestSetupReferenceData(FrappeTestCase):
    """Membership items, the reference-data orchestrator, and the service user."""

    # ----- membership items: group + item branches --------------------------

    def test_create_membership_items_creates_group_and_item(self):
        setup_mod.create_membership_items()
        self.assertTrue(frappe.db.exists("Item Group", "Memberships"))
        self.assertTrue(frappe.db.exists("Item", "MEMBERSHIP"))

    def test_membership_item_field_values(self):
        setup_mod.create_membership_items()
        item = frappe.get_doc("Item", "MEMBERSHIP")
        # The seed places the item under the Memberships group it just created.
        self.assertEqual(item.item_group, "Memberships")
        self.assertEqual(item.item_name, "Membership")
        self.assertEqual(item.stock_uom, "Nos")
        self.assertEqual(int(item.is_stock_item), 0)
        self.assertEqual(int(item.is_sales_item), 1)
        # NOTE: the seed also passes is_service_item=1, but that field does not
        # exist on the Item doctype in this ERPNext version, so Frappe silently
        # drops it. We do not assert it (it would AttributeError).

    def test_create_membership_items_idempotent(self):
        setup_mod.create_membership_items()
        before_items = frappe.db.count("Item")
        before_groups = frappe.db.count("Item Group")
        setup_mod.create_membership_items()
        self.assertEqual(frappe.db.count("Item"), before_items)
        self.assertEqual(frappe.db.count("Item Group"), before_groups)

    # ----- reference-data orchestrator --------------------------------------

    def test_create_all_reference_data_seeds_everything(self):
        """The orchestrator calls every individual seeder; assert the union of
        their post-conditions holds afterwards."""
        setup_mod.create_all_reference_data()

        # Membership types
        self.assertTrue(frappe.db.exists("Membership Type", "Lid"))
        # Team roles
        self.assertTrue(frappe.db.exists("Team Role", "Team Leader"))
        # Teams
        self.assertTrue(frappe.db.exists("Team", "Kascommissie"))
        # Regions
        self.assertTrue(frappe.db.exists("Region", "Noord-Holland"))
        # Payment modes
        self.assertTrue(frappe.db.exists("Mode of Payment", "Mollie"))
        # Membership items
        self.assertTrue(frappe.db.exists("Item", "MEMBERSHIP"))
        # Background service user
        self.assertTrue(frappe.db.exists("User", "background.service@verenigingen.local"))

    def test_create_all_reference_data_idempotent(self):
        # Prime once, then assert a second full run grows nothing.
        setup_mod.create_all_reference_data()
        before = {
            dt: frappe.db.count(dt)
            for dt in ["Membership Type", "Team Role", "Team", "Region", "Mode of Payment"]
        }
        setup_mod.create_all_reference_data()
        for dt, count in before.items():
            self.assertEqual(frappe.db.count(dt), count, f"{dt} count grew on second orchestrator run")

    # ----- background service user (error/branch coverage) ------------------

    def test_create_background_service_user_creates_and_assigns_role(self):
        setup_mod.create_background_service_user()
        email = "background.service@verenigingen.local"
        self.assertTrue(frappe.db.exists("User", email))
        user = frappe.get_doc("User", email)
        self.assertEqual(int(user.enabled), 1)
        roles = {r.role for r in user.roles}
        self.assertIn("Verenigingen Webhook User", roles)

    def test_create_background_service_user_idempotent(self):
        setup_mod.create_background_service_user()
        before = frappe.db.count("User")
        # Second call must hit the early-return "already exists" branch.
        setup_mod.create_background_service_user()
        self.assertEqual(frappe.db.count("User"), before)


class TestEnsureRequiredPaymentModes(FrappeTestCase):
    """ensure_required_payment_modes() — the after_migrate hook."""

    REQUIRED = ["Bank Transfer", "SEPA Direct Debit", "Mollie", "Manual", "Cash"]

    def test_ensure_required_payment_modes_creates_all(self):
        setup_mod.ensure_required_payment_modes()
        for name in self.REQUIRED:
            self.assertTrue(
                frappe.db.exists("Mode of Payment", name),
                f"Mode of Payment '{name}' should exist after the after_migrate hook runs",
            )

    def test_manual_mode_is_general_type(self):
        """'Manual' is intentionally type=General (not Bank/Cash) so it skips
        bank-account validation. Guard that design decision."""
        setup_mod.ensure_required_payment_modes()
        self.assertEqual(frappe.db.get_value("Mode of Payment", "Manual", "type"), "General")

    def test_ensure_required_payment_modes_idempotent(self):
        setup_mod.ensure_required_payment_modes()
        before = frappe.db.count("Mode of Payment")
        setup_mod.ensure_required_payment_modes()
        self.assertEqual(frappe.db.count("Mode of Payment"), before)


class TestConfigureWebsiteCors(FrappeTestCase):
    """configure_website_cors().

    On this Frappe version the Website Settings doctype has no CORS fields, so the
    function runs its full body without raising but persists nothing (Frappe drops
    unknown keys). We therefore assert it is safe (no exception) and idempotent
    rather than asserting persisted CORS values.
    """

    def test_configure_website_cors_runs_without_error(self):
        # Must not raise regardless of whether the doctype carries CORS fields.
        setup_mod.configure_website_cors()
        # Sanity: the single still loads and the function did not corrupt it.
        ws = frappe.get_single("Website Settings")
        self.assertEqual(ws.doctype, "Website Settings")

    def test_configure_website_cors_idempotent(self):
        setup_mod.configure_website_cors()
        # A second call must also be safe (either skip-branch if persisted, or the
        # same no-op path on a version without CORS fields).
        setup_mod.configure_website_cors()

    def test_skip_branch_when_origins_already_set(self):
        """If cors_allowed_origins is already populated, the function returns
        early WITHOUT saving Website Settings.

        configure_website_cors() reads frappe.get_single("Website Settings"),
        short-circuits when cors_allowed_origins is truthy, and otherwise calls
        website_settings.save(). On this Frappe version get_single returns a fresh
        single loaded from the DB (and the CORS fields don't exist on the doctype,
        so they can't be pre-populated via the DB), so we steer the guard by
        patching get_single to hand back a real Website Settings doc with the
        guard field forced truthy. We then spy on that doc's .save to prove the
        early-return fired: on the skip path save must NOT be called."""
        ws = frappe.get_single("Website Settings")
        # Force the guard truthy on the doc the function will read.
        ws.cors_allowed_origins = "https://example.test"
        save_spy = mock.MagicMock(name="save")
        ws.save = save_spy

        with mock.patch.object(frappe, "get_single", return_value=ws) as get_single_spy:
            setup_mod.configure_website_cors()

        # The function did consult Website Settings via get_single...
        get_single_spy.assert_called_once_with("Website Settings")
        # ...and, seeing origins already set, returned early without saving.
        save_spy.assert_not_called()


class TestLoadApplicationFixtures(FrappeTestCase):
    """load_application_fixtures() — wrapped in try/except, must never raise."""

    def test_load_application_fixtures_runs_without_error(self):
        # Returns None; the contract is "never raise" (it swallows all errors).
        result = setup_mod.load_application_fixtures()
        self.assertIsNone(result)

    def test_load_application_fixtures_idempotent(self):
        setup_mod.load_application_fixtures()
        # Repeated calls must remain safe (it uses ignore_if_duplicate when files
        # exist, and the not-found branch otherwise).
        setup_mod.load_application_fixtures()


class TestManualWrappers(FrappeTestCase):
    """Whitelisted manual/verify wrappers."""

    # ----- create_email_templates_manual -----------------------------------

    def test_create_email_templates_manual_returns_dict_with_keys(self):
        result = setup_mod.create_email_templates_manual()
        self.assertIsInstance(result, dict)
        self.assertIn("success", result)
        self.assertIn("message", result)

    def test_create_email_templates_manual_returns_int_counts(self):
        """create_email_templates_manual() normalizes the three helper return
        types (int / dict / OperationResult) to integer counts and reports
        success.

        Regression guard for a fixed bug: the wrapper previously did
        ``basic_count + enhanced_count + comprehensive_count`` where two helpers
        returned dicts, so ``int + dict`` raised TypeError and the wrapper always
        returned success=False. With _normalize_template_count() in place it must
        return success=True, expose the three integer *_count keys, and a message
        whose total reflects basic + enhanced + comprehensive.
        """
        result = setup_mod.create_email_templates_manual()
        self.assertTrue(
            result["success"],
            f"manual endpoint should succeed after the count-normalization fix: {result.get('message')}",
        )
        for key in ("basic_count", "enhanced_count", "comprehensive_count"):
            self.assertIn(key, result, f"result must expose '{key}'")
            self.assertIsInstance(result[key], int, f"'{key}' must be an int, got {type(result[key])}")
        # The message reports the sum of the three integer counts.
        total = result["basic_count"] + result["enhanced_count"] + result["comprehensive_count"]
        self.assertIn("Created", result["message"])
        self.assertIn(str(total), result["message"])

    # ----- verify_email_templates -------------------------------------------

    def test_verify_email_templates_structure(self):
        # Ensure at least the basic templates exist first so existing/missing split
        # is meaningful.
        setup_mod.create_application_email_templates()
        result = setup_mod.verify_email_templates()
        self.assertTrue(result["success"])
        for key in (
            "existing_basic_templates",
            "missing_basic_templates",
            "all_related_templates",
            "total_related_count",
            "message",
        ):
            self.assertIn(key, result)
        # Type contract on the structured fields.
        self.assertIsInstance(result["existing_basic_templates"], list)
        self.assertIsInstance(result["missing_basic_templates"], list)
        self.assertIsInstance(result["all_related_templates"], list)
        self.assertIsInstance(result["total_related_count"], int)
        self.assertEqual(result["total_related_count"], len(result["all_related_templates"]))

    def test_verify_email_templates_basic_split_is_consistent(self):
        """existing + missing must cover exactly the 4 known basic templates and
        not overlap."""
        setup_mod.create_application_email_templates()
        result = setup_mod.verify_email_templates()
        existing = set(result["existing_basic_templates"])
        missing = set(result["missing_basic_templates"])
        self.assertEqual(len(existing & missing), 0, "a template cannot be both existing and missing")
        self.assertEqual(len(existing | missing), 4, "the basic-template universe is exactly 4 names")
        # Anything reported as existing must really exist in the DB.
        for name in existing:
            self.assertTrue(frappe.db.exists("Email Template", name))
