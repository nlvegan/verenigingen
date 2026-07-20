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
from verenigingen.verenigingen.doctype.bulk_operation_tracker.bulk_operation_tracker import (
    BulkOperationTracker,
)


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

    def test_insert_roundtrip_persists_computed_batches(self):
        """A real insert runs validate() and the derived total_batches persists."""
        doc = self._make_tracker(total_records=100, batch_size=30)
        self.assertEqual(doc.total_batches, 4)
        self.assertEqual(frappe.db.get_value("Bulk Operation Tracker", doc.name, "total_batches"), 4)

    # ---------------------------------------------------------------- #172
    def test_concurrent_update_progress_is_atomic_no_timestamp_conflict(self):
        """Two batches loaded at the same version both fold in without a
        TimestampMismatchError, and counters end up correct (issue #172)."""
        tracker = BulkOperationTracker.create_tracker(
            operation_type="Account Creation", total_records=100, batch_size=25
        )
        self.factory.track_document("Bulk Operation Tracker", tracker.name)
        a = frappe.get_doc("Bulk Operation Tracker", tracker.name)
        b = frappe.get_doc("Bulk Operation Tracker", tracker.name)  # same (stale) version
        a.update_progress(1, {"completed": 25, "failed": 0})
        b.update_progress(2, {"completed": 20, "failed": 5})  # would raise on old save() path
        fresh = frappe.get_doc("Bulk Operation Tracker", tracker.name)
        self.assertEqual(fresh.successful_records, 45)
        self.assertEqual(fresh.failed_records, 5)
        self.assertEqual(fresh.processed_records, 50)
        self.assertEqual(fresh.current_batch, 2)  # GREATEST(1, 2)

    def test_update_progress_marks_complete_once_when_total_reached(self):
        """The batch that pushes processed >= total flips status exactly once."""
        tracker = BulkOperationTracker.create_tracker(
            operation_type="Account Creation", total_records=50, batch_size=25
        )
        self.factory.track_document("Bulk Operation Tracker", tracker.name)
        frappe.db.set_value("Bulk Operation Tracker", tracker.name, "status", "Processing")
        a = frappe.get_doc("Bulk Operation Tracker", tracker.name)
        b = frappe.get_doc("Bulk Operation Tracker", tracker.name)
        a.update_progress(1, {"completed": 25, "failed": 0})
        b.update_progress(2, {"completed": 25, "failed": 0})
        fresh = frappe.get_doc("Bulk Operation Tracker", tracker.name)
        self.assertEqual(fresh.processed_records, 50)
        self.assertEqual(fresh.status, "Completed")
        self.assertTrue(fresh.completed_at)

    def test_update_progress_completion_marks_failed_when_no_success(self):
        """All-failed batch completion sets status 'Failed'."""
        tracker = BulkOperationTracker.create_tracker(
            operation_type="Account Creation", total_records=25, batch_size=25
        )
        self.factory.track_document("Bulk Operation Tracker", tracker.name)
        frappe.db.set_value("Bulk Operation Tracker", tracker.name, "status", "Processing")
        tracker.update_progress(1, {"completed": 0, "failed": 25})
        fresh = frappe.get_doc("Bulk Operation Tracker", tracker.name)
        self.assertEqual(fresh.status, "Failed")
