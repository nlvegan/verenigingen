"""
Real-integration tests for the *Pending Membership Applications* script report
(``verenigingen/verenigingen/report/pending_membership_applications/``).

The report lists Membership Application Submissions in status "Pending Review" (#1765: an application
is its own record, not a Pending Member), computes days-pending / aging indicators, and returns
columns, data, summary statistics and a bar chart. The rows come from ``frappe.get_list``, so the MAS
permission query scopes them; tests/member/test_application_review_surfaces.py covers that scope.

Fixture shortcut, stated: each application is an inserted row given ``chapter``, ``confirmed_on`` and
``set_status("Pending Review")`` (the writes confirmation makes) rather than a driven confirmation flow.
Tests run as Administrator (see all).
"""

import frappe
from frappe.utils import add_days, now_datetime, today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.report.pending_membership_applications import (
    pending_membership_applications as report,
)

SUBMISSION = "Membership Application Submission"


class TestPendingMembershipApplicationsReport(VereningingenTestCase):
    # ------------------------------------------------------------- helpers

    def _pending_application(self, days_ago=0, chapter=False, membership_type=None, status="Pending Review"):
        """A Pending Review application confirmed N days ago."""
        application = frappe.get_doc(
            {
                "doctype": SUBMISSION,
                "email": f"applicant.{frappe.generate_hash(length=6)}@test.invalid",
                "source": "Full Form",
                "applicant_name": f"Applicant Report{frappe.generate_hash(length=4)}",
                "payload": "{}",
            }
        )
        application.insert()
        self.track_doc(SUBMISSION, application.name)
        application.db_set("confirmed_on", add_days(now_datetime(), -days_ago))
        if chapter:
            application.db_set("chapter", chapter)
        if membership_type:
            application.db_set("membership_type", membership_type)
        application.set_status("Pending Review")
        if status != "Pending Review":
            application.set_status(status)
        return application

    # ------------------------------------------------------------- columns

    def test_get_columns_structure(self):
        columns = report.get_columns()
        fieldnames = [c["fieldname"] for c in columns]
        self.assertEqual(len(columns), 9)
        self.assertEqual(columns[0]["fieldname"], "name")
        self.assertEqual(columns[0]["options"], SUBMISSION)
        for fn in ("days_pending", "chapter", "status_indicator", "applicant_name"):
            self.assertIn(fn, fieldnames)

    # ----------------------------------------------------- execute / shape

    def test_execute_returns_five_tuple(self):
        with self.assertNoErrorLog():
            result = report.execute({})
        self.assertEqual(len(result), 5)
        columns, data, _, chart, summary = result
        self.assertIsInstance(data, list)

    def test_execute_none_filters(self):
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute(None)
        self.assertEqual(len(columns), 9)

    # ----------------------------------------------------- core inclusion

    def test_pending_application_appears(self):
        application = self._pending_application(days_ago=5)
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({})
        row = next((r for r in data if r["name"] == application.name), None)
        self.assertIsNotNone(row, "a Pending application must appear")
        # days_pending derives from a server-side DATEDIFF; allow a 1-day skew
        # between the bench's today() (site tz) and MySQL CURDATE() (server tz).
        self.assertGreaterEqual(row["days_pending"], 4)
        self.assertEqual(row["chapter"], "Unassigned")
        self.assertIn("indicator", row["status_indicator"])

    def test_non_pending_applications_are_excluded(self):
        approved = self._pending_application(days_ago=2, status="Approved")
        unconfirmed = frappe.get_doc(
            {
                "doctype": SUBMISSION,
                "email": f"unconfirmed.{frappe.generate_hash(length=6)}@test.invalid",
                "source": "Full Form",
                "payload": "{}",
            }
        ).insert()
        self.track_doc(SUBMISSION, unconfirmed.name)
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({})
        ids = {r["name"] for r in data}
        self.assertNotIn(approved.name, ids, "only Pending Review applications are listed")
        self.assertNotIn(unconfirmed.name, ids)

    # ------------------------------------------------- status indicators

    def test_recent_application_gets_recent_indicator(self):
        application = self._pending_application(days_ago=2)
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({})
        row = next(r for r in data if r["name"] == application.name)
        self.assertIn("Recent", row["status_indicator"])

    def test_aging_application_gets_aging_indicator(self):
        application = self._pending_application(days_ago=10)  # 7 < days <= 14
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({})
        row = next(r for r in data if r["name"] == application.name)
        self.assertIn("Aging", row["status_indicator"])

    def test_overdue_application_gets_overdue_indicator(self):
        application = self._pending_application(days_ago=20)  # > 14
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({})
        row = next(r for r in data if r["name"] == application.name)
        self.assertIn("Overdue", row["status_indicator"])

    # --------------------------------------------------------- date filters

    def test_from_date_filter_excludes_older_applications(self):
        old = self._pending_application(days_ago=30)
        recent = self._pending_application(days_ago=1)
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute(
                {"from_date": add_days(today(), -10)}
            )
        ids = {r["name"] for r in data}
        self.assertIn(recent.name, ids)
        self.assertNotIn(old.name, ids)

    def test_to_date_filter_excludes_newer_applications(self):
        old = self._pending_application(days_ago=30)
        recent = self._pending_application(days_ago=1)
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute(
                {"to_date": add_days(today(), -10)}
            )
        ids = {r["name"] for r in data}
        self.assertIn(old.name, ids)
        self.assertNotIn(recent.name, ids)

    # --------------------------------------------------------- aging filters

    def test_overdue_only_filter(self):
        overdue = self._pending_application(days_ago=20)
        recent = self._pending_application(days_ago=2)
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({"overdue_only": 1})
        ids = {r["name"] for r in data}
        self.assertIn(overdue.name, ids)
        self.assertNotIn(recent.name, ids)

    def test_aging_only_filter(self):
        aging = self._pending_application(days_ago=10)
        recent = self._pending_application(days_ago=2)
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({"aging_only": 1})
        ids = {r["name"] for r in data}
        self.assertIn(aging.name, ids)
        self.assertNotIn(recent.name, ids)

    def test_days_filter(self):
        old = self._pending_application(days_ago=20)
        recent = self._pending_application(days_ago=2)
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({"days_filter": "14"})
        ids = {r["name"] for r in data}
        self.assertIn(old.name, ids)
        self.assertNotIn(recent.name, ids)

    # ----------------------------------------------------- membership type

    def test_membership_type_filter(self):
        gold = self.create_test_membership_type()
        silver = self.create_test_membership_type()
        matched = self._pending_application(days_ago=2, membership_type=gold.name)
        other = self._pending_application(days_ago=2, membership_type=silver.name)
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({"membership_type": gold.name})
        ids = {r["name"] for r in data}
        self.assertIn(matched.name, ids)
        self.assertNotIn(other.name, ids)

    # ------------------------------------------------------ chapter filter

    def test_chapter_filter_restricts_to_the_applications_chapter(self):
        chapter = self.create_test_chapter()
        in_chapter = self._pending_application(days_ago=2, chapter=chapter.name)
        out_chapter = self._pending_application(days_ago=2, chapter=False)
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({"chapter": chapter.name})
        ids = {r["name"] for r in data}
        self.assertIn(in_chapter.name, ids)
        self.assertNotIn(out_chapter.name, ids)
        row = next(r for r in data if r["name"] == in_chapter.name)
        self.assertEqual(row["chapter"], chapter.name)

    # ----------------------------------------------------- summary / chart

    def test_summary_counts(self):
        self._pending_application(days_ago=20)
        self._pending_application(days_ago=2)
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({})
        labels = {s["label"]: s["value"] for s in summary}
        self.assertIn("Total Pending", labels)
        self.assertEqual(labels["Total Pending"], len(data))
        self.assertGreaterEqual(labels["Overdue (>14 days)"], 1)
        self.assertIn("Average Days Pending", labels)

    def test_summary_empty_when_no_data(self):
        self.assertEqual(report.get_summary([]), [])

    def test_chart_none_when_no_data(self):
        self.assertIsNone(report.get_chart_data([]))

    def test_chart_groups_by_chapter(self):
        self._pending_application(days_ago=2, chapter=False)
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({})
        self.assertIsNotNone(chart)
        self.assertEqual(chart["type"], "bar")
        self.assertIn("Unassigned", chart["data"]["labels"])

    # ------------------------------------------------- pure helper coverage

    def test_get_summary_counts_and_average(self):
        rows = [{"days_pending": 20}, {"days_pending": 5}]
        summary = report.get_summary(rows)
        labels = {s["label"]: s["value"] for s in summary}
        self.assertEqual(labels["Total Pending"], 2)
        self.assertEqual(labels["Overdue (>14 days)"], 1)
        self.assertEqual(labels["Average Days Pending"], 12.5)

    def test_get_chart_data_counts_chapters(self):
        rows = [
            {"chapter": "Chap A"},
            {"chapter": "Chap A"},
            {"chapter": "Unassigned"},
        ]
        chart = report.get_chart_data(rows)
        labels = chart["data"]["labels"]
        values = chart["data"]["datasets"][0]["values"]
        mapping = dict(zip(labels, values))
        self.assertEqual(mapping["Chap A"], 2)
        self.assertEqual(mapping["Unassigned"], 1)
