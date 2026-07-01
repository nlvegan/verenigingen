# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""Real-DB integration tests for EBoekhoudenMigration controller helpers.

Covers the PURE / DB-only helper surface of
``verenigingen/e_boekhouden/doctype/e_boekhouden_migration/e_boekhouden_migration.py``:

* lazy service init / caching (``_get_account_migration_service``,
  ``_get_error_logger``, ``_get_data_quality_service``) incl. the
  company-from-settings fallback.
* ``log_error`` (error_details / failed_record_details sync, record_type /
  record_data variations).
* ``save_failed_records_log`` (appends a log reference to ``migration_summary``).

None of these methods hit the eBoekhouden REST API.
"""

import frappe

from verenigingen.e_boekhouden.services.account_migration_service import AccountMigrationService
from verenigingen.e_boekhouden.services.migration_data_quality_service import MigrationDataQualityService
from verenigingen.e_boekhouden.utils.migration_error_logger import MigrationErrorLogger
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMigrationControllerHelpers(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.company = frappe.db.get_value("Company", {}, "name")
        self.assertTrue(self.company, "Test site must have at least one Company")

    def _make_migration(self, **kwargs):
        doc = frappe.new_doc("E-Boekhouden Migration")
        doc.migration_name = kwargs.pop("migration_name", f"Test Migration {frappe.generate_hash()[:8]}")
        doc.migration_status = kwargs.pop("migration_status", "Draft")
        doc.company = kwargs.pop("company", self.company)
        doc.update(kwargs)
        return doc

    def test_get_error_logger_is_cached(self):
        doc = self._make_migration()
        logger1 = doc._get_error_logger()
        logger2 = doc._get_error_logger()
        self.assertIsInstance(logger1, MigrationErrorLogger)
        self.assertIs(logger1, logger2)
        # Carries the migration identity through.
        self.assertEqual(logger1.migration_name, doc.migration_name)

    def test_get_account_migration_service_is_cached(self):
        doc = self._make_migration()
        svc1 = doc._get_account_migration_service()
        svc2 = doc._get_account_migration_service()
        self.assertIsInstance(svc1, AccountMigrationService)
        self.assertIs(svc1, svc2)
        self.assertEqual(svc1.company, self.company)

    def test_get_account_migration_service_company_from_settings(self):
        """Company-from-settings fallback (~840-842): when the doc has no company
        the service is initialised with settings.default_company."""
        doc = self._make_migration()
        doc.company = None

        class _Settings:
            default_company = self.company

        svc = doc._get_account_migration_service(settings=_Settings())
        self.assertIsInstance(svc, AccountMigrationService)
        self.assertEqual(svc.company, self.company)

    def test_get_data_quality_service_is_cached(self):
        doc = self._make_migration()
        svc1 = doc._get_data_quality_service()
        svc2 = doc._get_data_quality_service()
        self.assertIsInstance(svc1, MigrationDataQualityService)
        self.assertIs(svc1, svc2)
        self.assertEqual(svc1.company, self.company)

    # ------------------------------------------------------------------
    # log_error
    # ------------------------------------------------------------------
    def test_log_error_populates_error_details(self):
        self.expectErrorLog("first failure", "second failure")
        doc = self._make_migration()
        doc.log_error("first failure")
        self.assertEqual(doc.error_details, "first failure")
        # Accumulates across calls (newline-joined).
        doc.log_error("second failure")
        self.assertIn("first failure", doc.error_details)
        self.assertIn("second failure", doc.error_details)

    def test_log_error_with_record_data_populates_failed_record_details(self):
        """With record_type + record_data, the underlying logger tracks a failed
        record, and the doc syncs failed_record_details once the attribute exists.

        The controller only syncs ``failed_record_details`` onto the doc when the
        attribute is already present (``hasattr`` guard). We seed it first so the
        documented sync behaviour is exercised end-to-end.
        """
        self.expectErrorLog("E-Boekhouden account Error")
        doc = self._make_migration()
        doc.failed_record_details = []  # enable the sync branch
        record = {"id": 42, "code": "X"}
        doc.log_error("bad account", record_type="account", record_data=record)

        self.assertIn("bad account", doc.error_details)
        self.assertEqual(len(doc.failed_record_details), 1)
        entry = doc.failed_record_details[0]
        self.assertEqual(entry["record_type"], "account")
        self.assertEqual(entry["error_message"], "bad account")
        self.assertEqual(entry["record_data"], record)

    def test_log_error_record_type_only_does_not_track_failed_record(self):
        """record_type without record_data must NOT create a failed-record entry
        (the logger requires BOTH)."""
        self.expectErrorLog("E-Boekhouden transaction Error")
        doc = self._make_migration()
        doc.failed_record_details = []
        doc.log_error("type only", record_type="transaction")
        self.assertIn("type only", doc.error_details)
        self.assertEqual(doc.failed_record_details, [])
        # The logger itself agrees.
        self.assertEqual(doc._get_error_logger().get_failed_records(), [])

    # ------------------------------------------------------------------
    # save_failed_records_log
    # ------------------------------------------------------------------
    def test_save_failed_records_log_appends_to_migration_summary(self):
        self.expectErrorLog("E-Boekhouden account Error")
        doc = self._make_migration()
        doc.failed_record_details = []
        doc.migration_summary = "Summary start"
        # Drive a failed record through log_error first.
        doc.log_error("bad row", record_type="account", record_data={"id": 1})
        doc.failed_records = 1

        doc.save_failed_records_log()

        self.assertIn("Failed records log saved to:", doc.migration_summary)
        self.assertIn("Summary start", doc.migration_summary)
        # The appended reference points at a failed_records JSON file.
        self.assertIn("failed_records_", doc.migration_summary)
