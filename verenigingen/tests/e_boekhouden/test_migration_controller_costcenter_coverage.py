# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""Real-DB integration tests for EBoekhoudenMigration controller (CLUSTER B).

Covers the PURE / DB-only surface of
``verenigingen/e_boekhouden/doctype/e_boekhouden_migration/e_boekhouden_migration.py``:

* ``create_cost_center`` (all branches: missing description, missing company,
  existing cost center, new-cost-center creation incl. the
  ``ensure_root_cost_center`` resolution path, the ``disabled`` flag, and the
  parent-by-group-id path).
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


class TestMigrationControllerCostCenter(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.company = frappe.db.get_value("Company", {}, "name")
        self.assertTrue(self.company, "Test site must have at least one Company")
        # Track cost centers we create so we can clean up the tree-doctype rows.
        self._created_cost_centers = []

    def tearDown(self):
        for cc_name in reversed(self._created_cost_centers):
            if frappe.db.exists("Cost Center", cc_name):
                try:
                    frappe.delete_doc("Cost Center", cc_name, force=True)
                except Exception:
                    pass
        super().tearDown()

    def _make_migration(self, **kwargs):
        doc = frappe.new_doc("E-Boekhouden Migration")
        doc.migration_name = kwargs.pop("migration_name", f"Test Migration {frappe.generate_hash()[:8]}")
        doc.migration_status = kwargs.pop("migration_status", "Draft")
        doc.company = kwargs.pop("company", self.company)
        doc.update(kwargs)
        return doc

    def _track_created(self, description, company):
        """Record the cost center created for ``description`` so tearDown removes it."""
        name = frappe.db.get_value(
            "Cost Center", {"cost_center_name": description, "company": company}, "name"
        )
        if name:
            self._created_cost_centers.append(name)
        return name

    # ------------------------------------------------------------------
    # create_cost_center
    # ------------------------------------------------------------------
    def test_create_cost_center_no_description_returns_false_and_logs(self):
        """Branch (a): empty/absent description -> False, and an error is logged."""
        self.expectErrorLog("Invalid cost center data")
        doc = self._make_migration()
        result = doc.create_cost_center({"description": "", "parentId": 0, "active": True})
        self.assertFalse(result)
        # log_error was invoked -> error_details populated on the doc.
        self.assertIn("no description", doc.error_details)

    def test_create_cost_center_missing_description_key(self):
        """Branch (a): description key absent entirely -> False."""
        self.expectErrorLog("Invalid cost center data")
        doc = self._make_migration()
        result = doc.create_cost_center({"parentId": 0})
        self.assertFalse(result)
        self.assertIn("no description", doc.error_details)

    def test_create_cost_center_no_company_returns_false(self):
        """Branch (b): no company on doc and no default_company in settings -> False.

        The method falls back to E-Boekhouden Settings.default_company when the
        doc has no company. We force that fallback to be empty so the
        "no company" guard is reached.
        """
        original = frappe.db.get_single_value("E-Boekhouden Settings", "default_company")
        frappe.db.set_value(
            "E-Boekhouden Settings",
            "E-Boekhouden Settings",
            "default_company",
            "",
            update_modified=False,
        )
        frappe.clear_document_cache("E-Boekhouden Settings", "E-Boekhouden Settings")
        self.expectErrorLog("No company set")
        try:
            doc = self._make_migration()
            doc.company = None  # force the settings fallback
            result = doc.create_cost_center({"description": "Whatever", "parentId": 0})
            self.assertFalse(result)
            self.assertIn("No company set", doc.error_details)
        finally:
            frappe.db.set_value(
                "E-Boekhouden Settings",
                "E-Boekhouden Settings",
                "default_company",
                original,
                update_modified=False,
            )
            frappe.clear_document_cache("E-Boekhouden Settings", "E-Boekhouden Settings")

    def test_create_cost_center_company_from_settings_fallback(self):
        """Branch (b inverse): doc has no company but settings.default_company is set.

        Confirms the settings fallback actually resolves a company and the
        cost center is created against it.
        """
        original = frappe.db.get_single_value("E-Boekhouden Settings", "default_company")
        frappe.db.set_value(
            "E-Boekhouden Settings",
            "E-Boekhouden Settings",
            "default_company",
            self.company,
            update_modified=False,
        )
        frappe.clear_document_cache("E-Boekhouden Settings", "E-Boekhouden Settings")
        try:
            doc = self._make_migration()
            doc.company = None  # must be resolved from settings
            description = f"CC settings fallback {frappe.generate_hash()[:6]}"
            result = doc.create_cost_center({"description": description, "parentId": 0, "active": True})
            self.assertTrue(result)
            name = self._track_created(description, self.company)
            self.assertTrue(name, "Cost center should have been created against the settings company")
        finally:
            frappe.db.set_value(
                "E-Boekhouden Settings",
                "E-Boekhouden Settings",
                "default_company",
                original,
                update_modified=False,
            )
            frappe.clear_document_cache("E-Boekhouden Settings", "E-Boekhouden Settings")

    def test_create_cost_center_existing_returns_false_without_error(self):
        """Branch (c): cost center with same name already exists -> False, NO error logged."""
        description = f"CC existing {frappe.generate_hash()[:6]}"
        doc = self._make_migration()

        # First creation succeeds.
        self.assertTrue(doc.create_cost_center({"description": description, "parentId": 0, "active": True}))
        self._track_created(description, self.company)

        # Fresh doc to get a clean error_details accumulator.
        doc2 = self._make_migration()
        result = doc2.create_cost_center({"description": description, "parentId": 0, "active": True})
        self.assertFalse(result)
        # Existing-data skip must NOT be logged as an error. log_error is what first
        # sets error_details on the doc, so if it was never called the attribute is
        # absent (or empty if the framework defaults it).
        self.assertEqual(getattr(doc2, "error_details", ""), "")

    def test_create_cost_center_creates_new_via_root_resolution(self):
        """Branch (d): a NEW cost center is created; the parent resolves through the
        ensure_root_cost_center path (parentId == 0 means the empty-string root
        lookup misses on a NULL-parent root, so ensure_root_cost_center is used)."""
        description = f"CC new root {frappe.generate_hash()[:6]}"
        doc = self._make_migration()
        result = doc.create_cost_center({"description": description, "parentId": 0, "active": True})
        self.assertTrue(result)

        name = self._track_created(description, self.company)
        self.assertTrue(name)
        created = frappe.get_doc("Cost Center", name)
        self.assertEqual(created.cost_center_name, description)
        self.assertEqual(created.company, self.company)
        self.assertEqual(created.is_group, 0)
        # Parent must be a real group cost center of this company.
        self.assertTrue(created.parent_cost_center)
        self.assertEqual(frappe.db.get_value("Cost Center", created.parent_cost_center, "is_group"), 1)

    def test_create_cost_center_disabled_flag_from_active(self):
        """Branch (e): the ``disabled`` field is the inverse of the data ``active`` flag."""
        # active False -> disabled True
        desc_inactive = f"CC inactive {frappe.generate_hash()[:6]}"
        doc = self._make_migration()
        self.assertTrue(
            doc.create_cost_center({"description": desc_inactive, "parentId": 0, "active": False})
        )
        name_inactive = self._track_created(desc_inactive, self.company)
        self.assertEqual(frappe.db.get_value("Cost Center", name_inactive, "disabled"), 1)

        # active True -> disabled False
        desc_active = f"CC active {frappe.generate_hash()[:6]}"
        self.assertTrue(doc.create_cost_center({"description": desc_active, "parentId": 0, "active": True}))
        name_active = self._track_created(desc_active, self.company)
        self.assertEqual(frappe.db.get_value("Cost Center", name_active, "disabled"), 0)

    def test_create_cost_center_active_defaults_true(self):
        """Branch (e): when ``active`` is absent it defaults to True -> disabled False."""
        description = f"CC default active {frappe.generate_hash()[:6]}"
        doc = self._make_migration()
        self.assertTrue(doc.create_cost_center({"description": description, "parentId": 0}))
        name = self._track_created(description, self.company)
        self.assertEqual(frappe.db.get_value("Cost Center", name, "disabled"), 0)

    def test_create_cost_center_parent_by_group_id(self):
        """Branch (f): a nonzero parentId selects an existing group cost center as parent."""
        existing_group = frappe.db.get_value("Cost Center", {"company": self.company, "is_group": 1}, "name")
        self.assertTrue(existing_group, "Company must have a group cost center")

        description = f"CC by group {frappe.generate_hash()[:6]}"
        doc = self._make_migration()
        result = doc.create_cost_center({"description": description, "parentId": 5, "active": True})
        self.assertTrue(result)
        name = self._track_created(description, self.company)
        # The branch picks the first group cost center for the company as parent.
        self.assertEqual(frappe.db.get_value("Cost Center", name, "parent_cost_center"), existing_group)

    # ------------------------------------------------------------------
    # lazy service init / caching
    # ------------------------------------------------------------------
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
