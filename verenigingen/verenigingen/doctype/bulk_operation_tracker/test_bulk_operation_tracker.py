# Copyright (c) 2025, Verenigingen and Contributors
# See license.txt
"""Tests for the Bulk Operation Tracker controller.

Exercises the real controller branches (no business logic mocked): ``validate``
total-batches derivation, ``get_progress_percentage``, the atomic
``update_progress`` counter/completion path, the ACR-derived retry list / error
summary / read-time rate & ETA, the ``clear_retry_queue`` cancel behaviour, and
the bounded save-conflict backoff (all #172). A create+persist+reload roundtrip
pins that ``validate`` runs and its computed values survive.
"""

from unittest.mock import patch

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

    def _make_acr(self, member, tracker_name, status="Failed", failure_reason=None):
        """Insert a minimal Account Creation Request linked to a tracker."""
        acr = frappe.get_doc(
            {
                "doctype": "Account Creation Request",
                "request_type": "Member",
                "source_record": member.name,
                "email": member.email or f"{member.name}@example.invalid",
                "full_name": member.full_name or member.name,
                "bulk_operation_tracker": tracker_name,
            }
        )
        acr.insert(ignore_permissions=True)  # before_insert forces status='Requested'
        self.factory.track_document("Account Creation Request", acr.name)
        # Set the terminal status directly (bypasses the before_insert override).
        frappe.db.set_value(
            "Account Creation Request",
            acr.name,
            {"status": status, "failure_reason": failure_reason},
            update_modified=False,
        )
        return acr.name

    # ---------------------------------------------------------------- #172
    def test_get_retry_requests_derives_from_failed_acrs(self):
        """Retry list is the Failed ACRs linked to the tracker (ACR is source of truth)."""
        tracker = BulkOperationTracker.create_tracker(
            operation_type="Account Creation", total_records=2, batch_size=25
        )
        self.factory.track_document("Bulk Operation Tracker", tracker.name)
        m1 = self.create_test_member(first_name="Rq1", last_name="X", birth_date="1990-01-01")
        m2 = self.create_test_member(first_name="Rq2", last_name="Y", birth_date="1990-01-01")
        failed = self._make_acr(m1, tracker.name, status="Failed", failure_reason="boom-1")
        self._make_acr(m2, tracker.name, status="Completed")
        self.assertEqual(tracker.get_retry_requests(), [failed])
        summary = tracker.get_error_summary()
        self.assertTrue(any("boom-1" in line for line in summary))

    def test_retry_processor_discovers_trackers_by_failed_records(self):
        """bulk_retry_processor must find trackers via failed_records (the retry
        list is derived now), not the never-written retry_queue field (#172)."""
        from verenigingen.utils import bulk_retry_processor as brp

        tracker = BulkOperationTracker.create_tracker(
            operation_type="Account Creation", total_records=1, batch_size=25
        )
        self.factory.track_document("Bulk Operation Tracker", tracker.name)
        frappe.db.set_value(
            "Bulk Operation Tracker",
            tracker.name,
            {"failed_records": 1, "status": "Completed", "completed_at": frappe.utils.now()},
            update_modified=False,
        )
        m = self.create_test_member(first_name="Rp", last_name="X", birth_date="1990-01-01")
        self._make_acr(m, tracker.name, status="Failed", failure_reason="retry-me")

        # Tests run as Administrator (break-glass for @critical_api), so no explicit
        # user switch is needed to call the admin endpoint.
        result = brp.get_retry_queue_status()
        rows = result.get("data", result.get("message", result)) if isinstance(result, dict) else result
        by_name = {r["tracker_name"]: r for r in rows}
        self.assertIn(tracker.name, by_name)
        self.assertEqual(by_name[tracker.name]["retry_queue_count"], 1)

    def test_tracker_save_conflict_uses_bounded_short_backoff(self):
        """A tracker save conflict retries with a short, bounded sleep — the old
        32s lock-holding backoff amplifier is gone (#172)."""
        from verenigingen.utils import secure_operations

        tracker = self._make_tracker(status="Processing")
        sleeps = []
        calls = {"n": 0}
        real_save = type(tracker).save

        def flaky_save(doc, *a, **k):
            # Force 3 consecutive conflicts (== new max_retries). The OLD policy's
            # 3rd-retry backoff already exceeds the bound (base 4 + jitter), so an
            # unbounded/32s-style policy is detectable; the new bounded one is not.
            calls["n"] += 1
            if calls["n"] <= 3:
                raise frappe.TimestampMismatchError("forced conflict")
            return real_save(doc, *a, **k)

        with (
            patch.object(type(tracker), "save", flaky_save),
            patch("time.sleep", side_effect=lambda s: sleeps.append(s)),
        ):
            result = secure_operations.secure_document_operation(
                operation="save",
                doc=tracker,
                justification="Test bounded backoff on tracker save conflict for issue 172",
                required_permissions=["Bulk Operation Tracker:write"],
            )
        self.assertTrue(result.success)
        self.assertTrue(sleeps, "expected at least one retry sleep")
        self.assertTrue(all(s <= 3.0 for s in sleeps), f"backoff not bounded: {sleeps}")

    def test_update_progress_does_not_write_batch_details_blob(self):
        """The contended per-batch batch_details JSON write is gone (#172)."""
        tracker = BulkOperationTracker.create_tracker(
            operation_type="Account Creation", total_records=25, batch_size=25
        )
        self.factory.track_document("Bulk Operation Tracker", tracker.name)
        frappe.db.set_value("Bulk Operation Tracker", tracker.name, "status", "Processing")
        tracker.update_progress(1, {"completed": 25, "failed": 0})
        self.assertFalse(frappe.db.get_value("Bulk Operation Tracker", tracker.name, "batch_details"))

    def test_processing_rate_and_eta_computed_at_read_time(self):
        """Rate/ETA are derived from started_at + processed_records at read-time,
        since update_progress no longer runs validate() (#172)."""
        from frappe.utils import add_to_date

        tracker = BulkOperationTracker.create_tracker(
            operation_type="Account Creation", total_records=100, batch_size=25
        )
        self.factory.track_document("Bulk Operation Tracker", tracker.name)
        frappe.db.set_value(
            "Bulk Operation Tracker",
            tracker.name,
            {"status": "Processing", "started_at": add_to_date(frappe.utils.now(), minutes=-2)},
            update_modified=False,
        )
        t = frappe.get_doc("Bulk Operation Tracker", tracker.name)
        t.update_progress(1, {"completed": 50, "failed": 0})
        t.reload()
        # 50 records over ~2 minutes -> ~25/min, and a future ETA.
        self.assertGreater(t.get_processing_rate(), 0)
        self.assertTrue(t.get_estimated_completion())

    def test_clear_retry_queue_cancels_failed_acrs(self):
        """clear_retry_queue moves Failed ACRs to Cancelled so the derived retry
        list empties and the scheduler stops re-attempting them (#172, S3)."""
        tracker = BulkOperationTracker.create_tracker(
            operation_type="Account Creation", total_records=1, batch_size=25
        )
        self.factory.track_document("Bulk Operation Tracker", tracker.name)
        m = self.create_test_member(first_name="Clr", last_name="X", birth_date="1990-01-01")
        acr = self._make_acr(m, tracker.name, status="Failed", failure_reason="x")
        self.assertEqual(tracker.get_retry_requests(), [acr])

        cancelled = tracker.clear_retry_queue()
        self.assertEqual(cancelled, 1)
        self.assertEqual(tracker.get_retry_requests(), [])
        self.assertEqual(frappe.db.get_value("Account Creation Request", acr, "status"), "Cancelled")

    def test_update_progress_folds_stale_copies_without_conflict(self):
        """Two doc copies loaded at the SAME version both fold their batch in
        without a TimestampMismatchError, and the counters are correct (#172).

        This proves the increments are applied DB-side (SET x = x + n) rather than
        driven by the stale in-memory copies — the old save() path would raise on
        the second write. (True parallel-connection safety comes from the InnoDB
        row lock on the single UPDATE; this test exercises the stale-copy path,
        not two live connections.)
        """
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
        """The batch that pushes processed >= total flips status exactly once;
        a later completing call must NOT rewrite the terminal state (#172)."""
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
        won_at = fresh.completed_at

        # Once-ness: a further update_progress after completion must not re-stamp
        # completed_at (the conditional WHERE excludes already-terminal rows).
        c = frappe.get_doc("Bulk Operation Tracker", tracker.name)
        c.update_progress(3, {"completed": 0, "failed": 0})
        again = frappe.db.get_value("Bulk Operation Tracker", tracker.name, "completed_at")
        self.assertEqual(str(again), str(won_at), "completion must be stamped exactly once")

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
