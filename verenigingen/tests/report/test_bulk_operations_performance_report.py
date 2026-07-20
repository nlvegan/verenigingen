"""
Real-integration tests for the *Bulk Operations Performance Report* script
report (``verenigingen/verenigingen/report/bulk_operations_performance_report/``).

This report was at 0% coverage. It is a LIVE standard Script Report
(ref_doctype Bulk Operation Tracker, roles System Manager / Verenigingen
Administrator) that aggregates ``Bulk Operation Tracker`` rows of
operation_type 'Account Creation' into duration / success-rate / throughput
metrics. The tests seed real Bulk Operation Tracker documents and exercise the
column structure, the data rows, the date filters, the summary, the chart and
the empty-result branches.
"""

import frappe
from frappe.utils import add_days, add_to_date, now_datetime, today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.report.bulk_operations_performance_report import (
    bulk_operations_performance_report as report,
)


class TestBulkOperationsPerformanceReport(VereningingenTestCase):
    # ------------------------------------------------------------- helpers

    def _make_tracker(
        self,
        *,
        status="Completed",
        operation_type="Account Creation",
        total=100,
        successful=90,
        failed=10,
        started=None,
        completed=None,
        rate=12.5,
        retry_queue=None,
        retry_queue_raw=None,
    ):
        """Create a real Bulk Operation Tracker row (auto-cleaned).

        The report derives retry_queue_count from linked Failed Account Creation
        Requests and the processing rate from started_at + processed_records
        (#172); ``retry_queue``/``retry_queue_raw`` are accepted only to express
        *how many* failed requests to seed (list length; raw string => 0)."""
        started = started or add_to_date(now_datetime(), hours=-2)
        tracker = frappe.get_doc(
            {
                "doctype": "Bulk Operation Tracker",
                "operation_type": operation_type,
                "status": status,
                "total_records": total,
                "successful_records": successful,
                "failed_records": failed,
                "processed_records": (successful or 0) + (failed or 0),
                "started_at": started,
                "completed_at": completed,
                "batch_size": 50,
                "total_batches": 1,
            }
        )
        tracker.insert(ignore_permissions=True)
        self.track_doc("Bulk Operation Tracker", tracker.name)

        # Seed Failed ACRs so the derived retry_queue_count reflects reality.
        n_failed = len(retry_queue) if isinstance(retry_queue, list) else 0
        for _i in range(n_failed):
            self._make_failed_acr(tracker.name)
        return tracker

    def _make_failed_acr(self, tracker_name):
        """Insert a Failed Account Creation Request linked to a tracker."""
        member = self.create_test_member(first_name="Rpt", last_name="Fail", birth_date="1990-01-01")
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
        acr.insert(ignore_permissions=True)  # before_insert forces status 'Requested'
        self.track_doc("Account Creation Request", acr.name)
        frappe.db.set_value("Account Creation Request", acr.name, "status", "Failed", update_modified=False)
        return acr.name

    # ------------------------------------------------------------- columns

    def test_get_columns_structure(self):
        columns = report.get_columns()
        fieldnames = [c["fieldname"] for c in columns]
        self.assertEqual(len(columns), 12)
        for expected in (
            "name",
            "operation_type",
            "duration_hours",
            "success_rate",
            "status",
            "retry_queue_count",
        ):
            self.assertIn(expected, fieldnames)

    # --------------------------------------------------------- data + metrics

    def test_completed_tracker_metrics(self):
        started = add_to_date(now_datetime(), hours=-3)
        completed = add_to_date(started, hours=1)  # 1h duration
        tracker = self._make_tracker(
            status="Completed",
            total=200,
            successful=180,
            failed=20,
            started=started,
            completed=completed,
            retry_queue=[{"id": 1}, {"id": 2}, {"id": 3}],
        )

        with self.assertNoErrorLog():
            columns, data, _none1, _none2, summary = report.execute({})

        self.assertEqual(len(columns), 12)
        row = next((r for r in data if r["name"] == tracker.name), None)
        self.assertIsNotNone(row, "the seeded tracker must appear in the report")
        self.assertAlmostEqual(row["duration_hours"], 1.0, places=1)
        self.assertEqual(row["success_rate"], 90.0)  # 180/200
        self.assertEqual(row["total_records"], 200)
        self.assertEqual(row["retry_queue_count"], 3)

    def test_zero_total_records_no_division_error(self):
        """A tracker with 0 total records must not raise ZeroDivisionError."""
        tracker = self._make_tracker(total=0, successful=0, failed=0, status="Failed")
        with self.assertNoErrorLog():
            _columns, data, _n1, _n2, _summary = report.execute({})
        row = next((r for r in data if r["name"] == tracker.name), None)
        self.assertIsNotNone(row)
        self.assertEqual(row["success_rate"], 0)

    def test_incomplete_tracker_has_zero_duration(self):
        tracker = self._make_tracker(status="Processing", completed=None)
        with self.assertNoErrorLog():
            _columns, data, _n1, _n2, _summary = report.execute({})
        row = next((r for r in data if r["name"] == tracker.name), None)
        self.assertIsNotNone(row)
        self.assertEqual(row["duration_hours"], 0)

    def test_malformed_retry_queue_is_tolerated(self):
        """Non-JSON retry_queue must not crash; count falls back to 0."""
        tracker = self._make_tracker(
            status="Completed",
            total=10,
            successful=10,
            failed=0,
            started=now_datetime(),
            retry_queue_raw="this-is-not-json",
        )

        with self.assertNoErrorLog():
            _columns, data, _n1, _n2, _summary = report.execute({})
        row = next((r for r in data if r["name"] == tracker.name), None)
        self.assertIsNotNone(row)
        self.assertEqual(row["retry_queue_count"], 0)

    def test_non_account_creation_operations_excluded(self):
        """Only 'Account Creation' operations are reported."""
        other = self._make_tracker(operation_type="Data Import")
        with self.assertNoErrorLog():
            _columns, data, _n1, _n2, _summary = report.execute({})
        self.assertFalse(
            any(r["name"] == other.name for r in data),
            "non Account Creation trackers must be excluded",
        )

    # --------------------------------------------------------- date filters

    def test_from_date_filter(self):
        old = self._make_tracker(started=add_to_date(now_datetime(), days=-40))
        recent = self._make_tracker(started=add_to_date(now_datetime(), days=-1))

        with self.assertNoErrorLog():
            _columns, data, _n1, _n2, _summary = report.execute({"from_date": add_days(today(), -10)})
        names = {r["name"] for r in data}
        self.assertIn(recent.name, names)
        self.assertNotIn(old.name, names, "trackers before from_date are excluded")

    def test_to_date_filter(self):
        old = self._make_tracker(started=add_to_date(now_datetime(), days=-40))
        recent = self._make_tracker(started=now_datetime())

        with self.assertNoErrorLog():
            _columns, data, _n1, _n2, _summary = report.execute({"to_date": add_days(today(), -10)})
        names = {r["name"] for r in data}
        self.assertIn(old.name, names)
        self.assertNotIn(recent.name, names, "trackers after to_date are excluded")

    # --------------------------------------------------------- summary

    def test_summary_aggregates(self):
        self._make_tracker(
            status="Completed",
            total=100,
            successful=100,
            failed=0,
            started=add_to_date(now_datetime(), hours=-2),
            completed=add_to_date(now_datetime(), hours=-1),
        )
        with self.assertNoErrorLog():
            _columns, data, _n1, _n2, summary = report.execute({})
        labels = {s["label"] for s in summary}
        self.assertIn("Performance Summary", labels)
        self.assertIn("Record Processing", labels)
        self.assertIn("Average Performance", labels)
        self.assertIn("Retry Queue", labels)

    def test_summary_empty_when_no_data(self):
        self.assertEqual(report.get_summary([]), [])

    # --------------------------------------------------------- chart

    def test_chart_none_when_no_data(self):
        # get_chart_data re-queries get_data; a from_date in the far future
        # matches no trackers, so the no-data branch must return None.
        chart = report.get_chart_data({"from_date": add_to_date(today(), years=50)})
        self.assertIsNone(chart)

    def test_chart_reflects_seeded_data(self):
        self._make_tracker(
            status="Completed",
            total=50,
            successful=45,
            failed=5,
            started=now_datetime(),
            completed=add_to_date(now_datetime(), hours=1),
        )
        chart = report.get_chart_data({})
        self.assertIsNotNone(chart)
        self.assertEqual(chart["type"], "line")
        self.assertEqual(chart["data"]["datasets"][0]["name"], "Success Rate (%)")
