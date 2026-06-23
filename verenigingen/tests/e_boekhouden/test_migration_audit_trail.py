"""
Coverage tests for verenigingen/utils/migration/migration_audit_trail.py

MigrationAuditTrail records every migration operation (starts/ends, record
creations, skips, validation errors, API calls, rollbacks) to an in-memory list
that is periodically flushed to a private JSON file. The statistics roll-ups,
operation timing, recommendations and the AuditedMigrationOperation context
manager are all pure logic over a real saved E-Boekhouden Migration document.

Run with:
    bench --site test_site_1 run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_migration_audit_trail
"""

import json
import os
import unittest

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.migration.migration_audit_trail import (
    AuditedMigrationOperation,
    MigrationAuditTrail,
)


def _persist_company(name="AuditTrail Co", abbr="ATCO"):
    if frappe.db.exists("Company", name):
        return name
    company = frappe.new_doc("Company")
    company.company_name = name
    company.abbr = abbr
    company.default_currency = "EUR"
    company.country = "Netherlands"
    company.insert(ignore_permissions=True)
    return name


def _make_migration_doc(company):
    doc = frappe.new_doc("E-Boekhouden Migration")
    doc.migration_name = "Audit Trail Coverage"
    doc.company = company
    doc.migration_status = "Draft"
    doc.date_from = "2024-01-01"
    doc.date_to = "2024-12-31"
    doc.insert(ignore_permissions=True)
    return doc


class _AuditBase(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = _persist_company()

    def setUp(self):
        super().setUp()
        self.migration = _make_migration_doc(self.company)
        self.audit = MigrationAuditTrail(self.migration)

    def tearDown(self):
        # Clean up audit files this test created.
        path = getattr(self.audit, "audit_file_path", None)
        if path and os.path.exists(path):
            os.remove(path)
        super().tearDown()


class TestAuditFileInit(_AuditBase):
    def test_audit_file_created_with_header(self):
        self.assertTrue(os.path.exists(self.audit.audit_file_path))
        with open(self.audit.audit_file_path) as f:
            data = json.load(f)
        self.assertEqual(data["header"]["migration_id"], self.migration.name)
        self.assertEqual(data["header"]["company"], self.company)
        self.assertEqual(data["entries"], [])


class TestOperationTracking(_AuditBase):
    def test_start_and_end_operation_records_stats_and_timing(self):
        op_id = self.audit.start_operation("import_accounts", {"batch": 1})
        self.assertEqual(len(self.audit.operation_stack), 1)
        # operation_id must be interpolated (regression: was a literal f-less str).
        self.assertTrue(op_id.startswith("import_accounts_"))
        self.assertNotIn("{", op_id)

        self.audit.end_operation(op_id, status="success")
        self.assertEqual(len(self.audit.operation_stack), 0)
        self.assertEqual(self.audit.statistics["import_accounts"]["success"], 1)
        self.assertEqual(len(self.audit.performance_metrics), 1)
        self.assertEqual(self.audit.performance_metrics[0]["status"], "success")

    def test_end_unknown_operation_logs_audit_error(self):
        self.audit.end_operation("does-not-exist", status="success")
        # No crash; an audit_error event is logged.
        event_types = [e["event_type"] for e in self.audit.audit_entries]
        self.assertIn("error", event_types)

    def test_failed_operation_recorded_in_error_summary(self):
        op_id = self.audit.start_operation("create_invoice")
        self.audit.end_operation(op_id, status="failed", error="boom")
        self.assertEqual(self.audit.statistics["create_invoice"]["failed"], 1)
        self.assertEqual(len(self.audit.error_summary["create_invoice"]), 1)

    def test_nested_operations_track_parent(self):
        outer = self.audit.start_operation("outer")
        inner = self.audit.start_operation("inner")
        self.assertEqual(self.audit.operation_stack[-1]["parent_operation"], outer)
        self.audit.end_operation(inner)
        self.audit.end_operation(outer)


class TestRecordLogging(_AuditBase):
    def test_record_creation_increments_stats(self):
        self.audit.log_record_creation("Customer", "CUST-001", {"customer_name": "ACME"})
        self.assertEqual(self.audit.statistics["records_created"]["Customer"], 1)

    def test_record_skip_tracks_reason(self):
        self.audit.log_record_skipped("Sales Invoice", "INV-1", "duplicate")
        self.assertEqual(self.audit.statistics["records_skipped"]["Sales Invoice"], 1)
        self.assertEqual(self.audit.statistics["skip_reasons"]["duplicate"], 1)

    def test_api_params_are_sanitized(self):
        self.audit.log_api_call(
            "fetch", {"username": "joe", "password": "secret", "api_key": "k"}, {"count": 3}
        )
        # The logged event must redact sensitive fields.
        api_event = next(e for e in self.audit.audit_entries if e["event_type"] == "api_call")
        params = api_event["data"]["params"]
        self.assertEqual(params["password"], "***REDACTED***")
        self.assertEqual(params["api_key"], "***REDACTED***")
        self.assertEqual(params["username"], "joe")

    def test_data_preview_truncates_and_filters(self):
        preview = self.audit._get_data_preview({"customer_name": "X" * 200, "irrelevant": "drop me"})
        self.assertIn("customer_name", preview)
        self.assertNotIn("irrelevant", preview)
        self.assertLessEqual(len(preview["customer_name"]), 100)

    def test_duplicate_detection_logged(self):
        self.audit.log_duplicate_detected("Payment Entry", {"name": "PE-1"}, ["PE-1", "PE-2"])
        self.assertEqual(self.audit.statistics["duplicates_detected"]["Payment Entry"], 1)


class TestSummaryReport(_AuditBase):
    def test_summary_report_aggregates_and_writes_file(self):
        # Build some history.
        self.audit.log_record_creation("Account", "ACC-1")
        self.audit.log_record_creation("Account", "ACC-2")
        op = self.audit.start_operation("import_accounts")
        self.audit.end_operation(op, status="success")

        with self.assertNoErrorLog():
            summary = self.audit.generate_summary_report()

        self.assertEqual(summary["migration_id"], self.migration.name)
        self.assertEqual(summary["overall_statistics"]["records_created"]["Account"], 2)
        self.assertIn("import_accounts", summary["performance_metrics"])
        # Summary file path must be a real interpolated path (regression: f-less).
        self.assertTrue(os.path.exists(summary["audit_file"]))
        # Clean up the summary file too.
        for fn in os.listdir(os.path.dirname(self.audit.audit_file_path)):
            if fn.startswith(f"summary_{self.migration.name}"):
                os.remove(os.path.join(os.path.dirname(self.audit.audit_file_path), fn))

    def test_recommendations_flag_high_failure_rate(self):
        # 3 failures, 1 success -> 75% > 5% threshold.
        for i in range(3):
            op = self.audit.start_operation("create_invoice")
            self.audit.end_operation(op, status="failed", error="x")
        op = self.audit.start_operation("create_invoice")
        self.audit.end_operation(op, status="success")

        recs = self.audit._generate_recommendations()
        types = [r["type"] for r in recs]
        self.assertIn("high_failure_rate", types)
        # Message must be interpolated (regression: was f-less).
        msg = next(r["message"] for r in recs if r["type"] == "high_failure_rate")
        self.assertNotIn("{", msg)


class TestAuditedOperationContextManager(_AuditBase):
    def test_success_path_marks_success(self):
        with AuditedMigrationOperation(self.audit, "bulk_import") as op:
            op.set_result({"count": 5})
        self.assertEqual(self.audit.statistics["bulk_import"]["success"], 1)

    def test_exception_path_marks_failed_and_reraises(self):
        with self.assertRaises(ValueError):
            with AuditedMigrationOperation(self.audit, "bulk_import"):
                raise ValueError("kaboom")
        # Exception is recorded as a failure and NOT suppressed.
        self.assertEqual(self.audit.statistics["bulk_import"]["failed"], 1)
        self.assertEqual(len(self.audit.error_summary["bulk_import"]), 1)


if __name__ == "__main__":
    unittest.main()
