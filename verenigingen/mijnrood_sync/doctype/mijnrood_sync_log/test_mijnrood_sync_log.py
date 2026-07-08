# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""Tests for the MijnRood Sync Log doctype.

MijnRood Sync Log is a write-only sync-run audit record with no controller
logic (the controller is a bare ``Document`` subclass). Coverage here is
therefore inherently shallow: there is no ``validate``/hook branch to exercise.
These tests instead pin the framework-level contracts the doctype JSON declares
and that downstream code relies on — autoname-from-fieldname (``name`` ==
``sync_run_id``), the unique constraint on ``sync_run_id``, the mandatory
``sync_run_id`` field, and a full create+persist+reload roundtrip of the
statistics fields.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMijnRoodSyncLog(EnhancedTestCase):
    def _make_log(self, **overrides):
        data = {
            "doctype": "MijnRood Sync Log",
            "sync_run_id": overrides.pop("sync_run_id", "test-log-run-0001"),
            "status": "Success",
            "rows_scanned": 42,
            "new_events": 3,
            "changed_events": 2,
            "deleted_events": 1,
            "unchanged_rows": 36,
        }
        data.update(overrides)
        doc = frappe.get_doc(data)
        doc.insert(ignore_permissions=True)
        self.factory.track_document("MijnRood Sync Log", doc.name)
        return doc

    def _make_raw(self, data):
        """Insert an arbitrary (possibly invalid) doc for negative-path tests."""
        return frappe.get_doc(data).insert(ignore_permissions=True)

    def test_autoname_from_sync_run_id_and_roundtrip(self):
        """name is set from sync_run_id and all stats persist across reload."""
        doc = self._make_log(sync_run_id="test-log-run-roundtrip")

        # autoname: "field:sync_run_id" -> document name equals the run id
        self.assertEqual(doc.name, "test-log-run-roundtrip")

        reloaded = frappe.get_doc("MijnRood Sync Log", doc.name)
        self.assertEqual(reloaded.status, "Success")
        self.assertEqual(reloaded.rows_scanned, 42)
        self.assertEqual(reloaded.new_events, 3)
        self.assertEqual(reloaded.changed_events, 2)
        self.assertEqual(reloaded.deleted_events, 1)
        self.assertEqual(reloaded.unchanged_rows, 36)

    def test_sync_run_id_is_mandatory(self):
        """Omitting the mandatory sync_run_id (the autoname field) is rejected."""
        # sync_run_id drives autoname ("field:sync_run_id"), so its absence is
        # caught during naming and surfaces as a ValidationError.
        with self.assertRaises(frappe.ValidationError):
            self._make_raw({"doctype": "MijnRood Sync Log", "status": "Running"})

    def test_sync_run_id_is_unique(self):
        """Two logs with the same sync_run_id collide (unique constraint)."""
        self._make_log(sync_run_id="test-log-run-dup")
        with self.assertRaises((frappe.DuplicateEntryError, frappe.UniqueValidationError)):
            self._make_log(sync_run_id="test-log-run-dup")
