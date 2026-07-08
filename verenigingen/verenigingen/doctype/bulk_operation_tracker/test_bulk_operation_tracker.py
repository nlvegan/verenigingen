# Copyright (c) 2025, Verenigingen and Contributors
# See license.txt
"""Tests for the Bulk Operation Tracker controller.

Exercises the real, pure-computation controller branches (no business logic is
mocked): ``validate`` total-batches derivation, ``get_progress_percentage``,
the ``_complete_operation`` status logic, and the ``get_retry_requests`` JSON
parsing (including the corrupted-JSON fallback). A create+persist+reload
roundtrip pins that ``validate`` runs and its computed values survive.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestBulkOperationTracker(EnhancedTestCase):
    def _make_tracker(self, **overrides):
        """Insert a Bulk Operation Tracker fixture (seeding helper)."""
        data = {
            "doctype": "Bulk Operation Tracker",
            "operation_type": "Account Creation",
            "total_records": 100,
            "batch_size": 30,
            "status": "Queued",
        }
        data.update(overrides)
        doc = frappe.get_doc(data)
        doc.insert(ignore_permissions=True)
        self.factory.track_document("Bulk Operation Tracker", doc.name)
        return doc

    def test_validate_autocalculates_total_batches(self):
        """validate() fills total_batches with ceil(total_records / batch_size)."""
        doc = frappe.new_doc("Bulk Operation Tracker")
        doc.operation_type = "Account Creation"
        doc.status = "Queued"
        doc.total_records = 100
        doc.batch_size = 30
        # total_batches deliberately left unset
        doc.validate()
        # ceil(100 / 30) == 4
        self.assertEqual(doc.total_batches, 4)

    def test_get_progress_percentage_happy(self):
        """get_progress_percentage returns processed/total * 100 rounded to 2dp."""
        doc = frappe.new_doc("Bulk Operation Tracker")
        doc.total_records = 200
        doc.processed_records = 50
        self.assertEqual(doc.get_progress_percentage(), 25.0)

    def test_get_progress_percentage_zero_total_guard(self):
        """With no total_records the method returns 0.0 (division guard)."""
        doc = frappe.new_doc("Bulk Operation Tracker")
        doc.total_records = 0
        doc.processed_records = 5
        self.assertEqual(doc.get_progress_percentage(), 0.0)

    def test_complete_operation_marks_failed_when_no_success(self):
        """_complete_operation -> 'Failed' when there were failures and zero successes."""
        doc = frappe.new_doc("Bulk Operation Tracker")
        doc.total_records = 10
        doc.total_batches = 1
        doc.successful_records = 0
        doc.failed_records = 10
        doc._complete_operation()
        self.assertEqual(doc.status, "Failed")

    def test_complete_operation_marks_completed_with_partial_success(self):
        """_complete_operation -> 'Completed' when at least one record succeeded."""
        doc = frappe.new_doc("Bulk Operation Tracker")
        doc.total_records = 10
        doc.total_batches = 1
        doc.successful_records = 7
        doc.failed_records = 3
        doc._complete_operation()
        self.assertEqual(doc.status, "Completed")

    def test_get_retry_requests_parses_json_and_falls_back(self):
        """get_retry_requests parses a JSON list and returns [] on corrupt JSON."""
        doc = frappe.new_doc("Bulk Operation Tracker")
        doc.retry_queue = '["REQ-1", "REQ-2"]'
        self.assertEqual(doc.get_retry_requests(), ["REQ-1", "REQ-2"])

        doc.retry_queue = "{not valid json"
        self.assertEqual(doc.get_retry_requests(), [])

    def test_insert_roundtrip_persists_computed_batches(self):
        """A real insert runs validate() and the derived total_batches persists."""
        doc = self._make_tracker(total_records=100, batch_size=30)
        self.assertEqual(doc.total_batches, 4)
        self.assertEqual(frappe.db.get_value("Bulk Operation Tracker", doc.name, "total_batches"), 4)
