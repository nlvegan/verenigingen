# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""Real-DB coverage for the config / validation surface of the
E-Boekhouden Migration controller
(``verenigingen/e_boekhouden/doctype/e_boekhouden_migration/e_boekhouden_migration.py``).

Complements the existing migration-controller suites (guards / costcenter /
accounts / sweep / endpoints) by covering branches those do NOT touch, all
without a live eBoekhouden REST call:

* ``validate`` (~35-49): the date-range business rules
  (partial-range rejection gated on ``migrate_transactions``; from>to rejection;
  the import-all empty-date allowance).
* ``onload`` (~23-33): the "seed company from E-Boekhouden Settings default"
  default-value path (and the no-op when a company is already set).
* ``parse_account_group_mappings`` (~295-325): the LEGACY text-field fallback
  (``balance_sheet_group_mappings`` / ``pl_group_mappings``) that is only reached
  when the structured ``group_type_mappings`` table is empty -- the accounts
  suite only covers the structured-table path.
* ``check_migration_data_quality`` (~1773-1788): the whitelisted endpoint that
  runs the real MigrationDataQualityService and stores the report on the doc.
* ``start_migration_background`` (~80-89): the exception handler that flips the
  doc to Failed and re-raises when queuing fails.

Business logic is never mocked. The only patch is ``frappe.enqueue`` (framework
infra) in the single start_migration_background failure test, forced to raise so
the controller's OWN except handler is exercised.
"""

from unittest.mock import patch

import frappe

from verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration import (
    check_migration_data_quality,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

SETTINGS = "E-Boekhouden Settings"


class _MigrationConfigBase(EnhancedTestCase):
    """Base with committed-doc cleanup.

    Several paths under test call ``frappe.db.commit()`` (start_migration_background
    commits its status writes; check_migration_data_quality persists via db_set),
    so inserted migration docs can outlive FrappeTestCase's per-test rollback. We
    therefore track and force-delete every migration we insert.
    """

    def setUp(self):
        super().setUp()
        self.company = frappe.db.get_value("Company", {}, "name")
        self.assertTrue(self.company, "Test site must have at least one Company")
        self._created_migrations = []

    def tearDown(self):
        frappe.db.rollback()
        for name in self._created_migrations:
            if frappe.db.exists("E-Boekhouden Migration", name):
                doc = frappe.get_doc("E-Boekhouden Migration", name)
                if doc.docstatus == 1:
                    doc.cancel()
                frappe.delete_doc(
                    "E-Boekhouden Migration", name, force=True, delete_permanently=True
                )
        frappe.db.commit()
        super().tearDown()

    def _make_migration(self, insert=False, **kwargs):
        doc = frappe.new_doc("E-Boekhouden Migration")
        doc.migration_name = kwargs.pop(
            "migration_name", f"Test Migration {frappe.generate_hash()[:8]}"
        )
        doc.migration_status = kwargs.pop("migration_status", "Draft")
        doc.company = kwargs.pop("company", self.company)
        doc.update(kwargs)
        if insert:
            doc.insert(ignore_permissions=True)
            self._created_migrations.append(doc.name)
        return doc


class TestValidateDateRules(_MigrationConfigBase):
    """EBoekhoudenMigration.validate date-range business rules."""

    def test_partial_date_range_rejected_when_migrating_transactions(self):
        """migrate_transactions on + only ONE of date_from/date_to set -> throw.

        A half-specified range is ambiguous, so the controller refuses it.
        """
        doc = self._make_migration(migrate_transactions=1, date_from="2024-01-01", date_to=None)
        with self.assertRaises(frappe.exceptions.ValidationError) as ctx:
            doc.validate()
        self.assertIn("both Date From and Date To", str(ctx.exception))

    def test_partial_date_allowed_when_not_migrating_transactions(self):
        """The partial-range guard is gated on migrate_transactions: with it OFF a
        lone date_from must NOT raise (the range only matters for transactions)."""
        doc = self._make_migration(migrate_transactions=0, date_from="2024-01-01", date_to=None)
        # Must not raise -- only the from>to rule could still apply, and it does not here.
        doc.validate()

    def test_from_after_to_rejected(self):
        """date_from later than date_to -> throw, regardless of migrate flags."""
        doc = self._make_migration(migrate_transactions=1, date_from="2024-06-01", date_to="2024-01-01")
        with self.assertRaises(frappe.exceptions.ValidationError) as ctx:
            doc.validate()
        self.assertIn("Date From cannot be after Date To", str(ctx.exception))

    def test_full_valid_range_accepted(self):
        """A complete, correctly-ordered range validates cleanly."""
        doc = self._make_migration(migrate_transactions=1, date_from="2024-01-01", date_to="2024-06-01")
        doc.validate()  # no raise

    def test_import_all_empty_dates_accepted(self):
        """migrate_transactions on with BOTH dates empty means 'import everything'
        and is explicitly allowed."""
        doc = self._make_migration(migrate_transactions=1, date_from=None, date_to=None)
        doc.validate()  # no raise


class TestOnloadDefaultCompany(_MigrationConfigBase):
    """EBoekhoudenMigration.onload seeds company from settings default."""

    def _set_settings_default_company(self, value):
        original = frappe.db.get_single_value(SETTINGS, "default_company")
        frappe.db.set_value(SETTINGS, SETTINGS, "default_company", value, update_modified=False)
        frappe.clear_document_cache(SETTINGS, SETTINGS)
        return original

    def test_onload_seeds_company_from_settings_default(self):
        """A brand-new doc with no company adopts E-Boekhouden Settings.default_company."""
        original = self._set_settings_default_company(self.company)
        try:
            doc = frappe.new_doc("E-Boekhouden Migration")
            doc.company = None
            self.assertTrue(doc.is_new())
            doc.onload()
            self.assertEqual(doc.company, self.company)
        finally:
            self._set_settings_default_company(original)

    def test_onload_keeps_existing_company(self):
        """onload only defaults when company is unset -- an existing value is kept
        even if a different settings default exists."""
        # Point the settings default at nothing meaningful; the doc already has one.
        original = self._set_settings_default_company("")
        try:
            doc = frappe.new_doc("E-Boekhouden Migration")
            doc.company = self.company
            doc.onload()
            self.assertEqual(doc.company, self.company)
        finally:
            self._set_settings_default_company(original)


class TestParseAccountGroupMappingsLegacy(_MigrationConfigBase):
    """parse_account_group_mappings LEGACY text-field fallback.

    The structured ``group_type_mappings`` table takes precedence (covered in
    test_migration_controller_accounts_coverage). Here we drive the text-field
    parser by handing the method a settings stand-in whose structured table is
    empty. The settings argument is a plain data object (a frappe._dict), not a
    mocked collaborator -- the parsing logic under test is 100% real.
    """

    def test_legacy_text_fields_parsed_into_simple_mapping(self):
        """Both balance-sheet and P/L text blocks are parsed into ``code -> name``.

        The legacy format has no root_type, so values are plain strings (not the
        structured dicts the table path produces).
        """
        doc = self._make_migration()
        settings = frappe._dict(
            group_type_mappings=[],
            balance_sheet_group_mappings="001 Vaste activa\n002 Vlottende activa",
            pl_group_mappings="800 Netto-omzet",
        )
        result = doc.parse_account_group_mappings(settings)
        self.assertEqual(
            result,
            {"001": "Vaste activa", "002": "Vlottende activa", "800": "Netto-omzet"},
        )

    def test_malformed_line_without_space_is_skipped(self):
        """A line with no space cannot be split into code+name and is dropped;
        well-formed sibling lines still parse."""
        doc = self._make_migration()
        settings = frappe._dict(
            group_type_mappings=[],
            balance_sheet_group_mappings="001 Vaste activa\nNOSPACE\n\n002 Vlottende activa",
            pl_group_mappings="",
        )
        result = doc.parse_account_group_mappings(settings)
        self.assertEqual(result, {"001": "Vaste activa", "002": "Vlottende activa"})
        self.assertNotIn("NOSPACE", result)

    def test_no_mappings_configured_returns_empty(self):
        """Neither the structured table nor the text fields configured -> {}."""
        doc = self._make_migration()
        settings = frappe._dict(group_type_mappings=[])
        self.assertEqual(doc.parse_account_group_mappings(settings), {})


class TestCheckMigrationDataQualityEndpoint(_MigrationConfigBase):
    """check_migration_data_quality whitelisted endpoint (~1773-1788)."""

    def test_returns_report_and_stores_summary(self):
        """The endpoint runs the real MigrationDataQualityService against the
        migration's company and persists the JSON report on migration_summary.

        On a site with no imported eBoekhouden data the report is well-formed but
        carries no issues -- we assert its SHAPE (the service ran) and that the
        report was stored back on the document.
        """
        migration = self._make_migration(insert=True)
        result = check_migration_data_quality(migration.name)

        self.assertTrue(result["success"])
        report = result["report"]
        # The service's report shape (proves the real service executed, not a stub).
        for key in ("timestamp", "company", "issues", "statistics", "recommendations"):
            self.assertIn(key, report)
        self.assertEqual(report["company"], self.company)

        # The endpoint stores the serialized report back on the doc.
        stored = frappe.db.get_value("E-Boekhouden Migration", migration.name, "migration_summary")
        self.assertTrue(stored)
        import json

        self.assertEqual(json.loads(stored)["company"], self.company)


class TestStartMigrationBackgroundFailure(_MigrationConfigBase):
    """start_migration_background exception handler (~80-89)."""

    def test_enqueue_failure_marks_failed_and_reraises(self):
        """If queuing the background job raises, the controller flips the doc to
        Failed, records the error in error_log, and re-raises.

        frappe.enqueue (framework infra) is forced to raise; the status/db_set
        writes that precede it have already committed In Progress, so the except
        handler must overwrite the status to Failed.
        """
        self.expectErrorLog("E-Boekhouden Migration")
        migration = self._make_migration(insert=True, migration_status="Draft")

        with patch("frappe.enqueue", side_effect=RuntimeError("queue is down")):
            with self.assertRaises(RuntimeError):
                migration.start_migration_background()

        self.assertEqual(
            frappe.db.get_value("E-Boekhouden Migration", migration.name, "migration_status"),
            "Failed",
        )
        self.assertIn(
            "queue is down",
            frappe.db.get_value("E-Boekhouden Migration", migration.name, "error_log") or "",
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
