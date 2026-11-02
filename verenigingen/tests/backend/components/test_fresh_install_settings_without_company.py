# Fresh-install settings without a Company (#1957).
#
# `frappe.installer.install_app` runs `after_install` BEFORE `sync_fixtures` and `after_sync`
# after it, and a fresh site has no Company. CI sites are fresh installs, so both showed up as
# failed `execute_after_install` steps on every shard.
#
# Every test works inside one transaction that is rolled back; the setup code commits, so
# `frappe.db.commit` is replaced by a no-op for the duration (Mock justified: the commit is
# the only thing that would make these deliberate deletions permanent).

import contextlib
import io
from unittest import mock

import frappe

from verenigingen import setup as setup_mod
from verenigingen.tests.backend.components.test_fresh_install_fixture_ordering import _RolledBackCase


class TestSettingsWithAStraySinglesRowAndNoCompany(_RolledBackCase):
    """#1957. The CI log shows `Failed to create Verenigingen Settings: ...: company, creation_user`
    on a site with no Company: the only path that raises exactly that is a Singles row that is
    present while `company` is not (the guard `get_singles_dict` is truthy for ANY row). What
    writes that row on a fresh install was not established; the row is planted here directly
    (a probe shortcut), so these tests prove the guards, not the origin of the row."""

    def setUp(self):
        super().setUp()
        frappe.db.delete("Singles", {"doctype": "Verenigingen Settings"})
        frappe.db.sql(
            "insert into `tabSingles` (doctype, field, value) values (%s, %s, %s)",
            ("Verenigingen Settings", "last_member_id", "1000"),
        )
        frappe.clear_cache(doctype="Verenigingen Settings")
        self.assertTrue(frappe.db.get_singles_dict("Verenigingen Settings"))
        self.assertFalse(frappe.db.get_single_value("Verenigingen Settings", "company"))

    def test_configuring_creation_user_skips_instead_of_failing(self):
        from verenigingen.setup.public_document_creator_setup import configure_creation_user_in_settings

        with contextlib.redirect_stdout(io.StringIO()):
            result = configure_creation_user_in_settings("Administrator")
        self.assertTrue(result["success"], result["message"])

    def test_the_whole_public_creator_step_succeeds_without_a_company(self):
        from verenigingen.setup.public_document_creator_setup import setup_public_document_creator

        with contextlib.redirect_stdout(io.StringIO()):
            result = setup_public_document_creator()
        self.assertTrue(result["success"], result["message"])

    def test_creating_settings_defers_quietly_without_a_company(self):
        out = io.StringIO()
        with mock.patch.object(setup_mod, "_resolve_install_company", return_value=None):
            with contextlib.redirect_stdout(out):
                result = setup_mod.create_default_verenigingen_settings()
        self.assertIsNone(result)
        self.assertNotIn("Failed to create", out.getvalue())
        self.assertIn("no Company exists yet", out.getvalue())

    def test_after_migrate_creates_settings_once_a_company_exists(self):
        from verenigingen.tests.support.sepa_test_company import get_eur_test_company

        get_eur_test_company()  # guarantees a Company exists; the hook resolves its own choice
        with contextlib.redirect_stdout(io.StringIO()):
            setup_mod.ensure_default_verenigingen_settings()
        saved = frappe.db.get_single_value("Verenigingen Settings", "company")
        self.assertTrue(saved, "Settings were not created although a Company exists")
        self.assertTrue(frappe.db.exists("Company", saved))

    def test_a_saved_settings_single_is_left_alone(self):
        # Control with a real saved row: a Single that HAS a company is not recreated.
        frappe.db.sql(
            "insert into `tabSingles` (doctype, field, value) values (%s, %s, %s)",
            ("Verenigingen Settings", "company", "Keep Me"),
        )
        with mock.patch.object(setup_mod, "create_default_verenigingen_settings") as create:
            setup_mod.ensure_default_verenigingen_settings()
        create.assert_not_called()

    def test_a_row_without_company_is_completed_not_overwritten(self):
        """Opposite harm: Document.insert on a Single deletes its rows first, so creating over a
        partial row wiped the admin's values (support_email went to '')."""
        from verenigingen.tests.support.sepa_test_company import get_eur_test_company

        get_eur_test_company()
        frappe.db.sql(
            "insert into `tabSingles` (doctype, field, value) values (%s, %s, %s)",
            ("Verenigingen Settings", "support_email", "keep@example.org"),
        )
        frappe.clear_cache(doctype="Verenigingen Settings")
        with contextlib.redirect_stdout(io.StringIO()):
            setup_mod.ensure_default_verenigingen_settings()
        self.assertEqual(
            frappe.db.get_single_value("Verenigingen Settings", "support_email"), "keep@example.org"
        )
        company = frappe.db.get_single_value("Verenigingen Settings", "company")
        self.assertTrue(company)
        self.assertTrue(frappe.db.exists("Company", company))
