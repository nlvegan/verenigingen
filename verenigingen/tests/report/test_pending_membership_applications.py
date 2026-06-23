"""
Real-integration tests for the *Pending Membership Applications* script report
(``verenigingen/verenigingen/report/pending_membership_applications/``).

The report lists Members whose ``application_status`` is "Pending", computes
days-pending / aging indicators, attaches each applicant's chapter and returns
columns, data, summary statistics and a bar chart.

These tests seed real Members (with Pending applications), Chapters and
Memberships via the factory and call ``execute(filters)`` / ``get_data`` /
the pure summary/chart helpers directly. No business logic is mocked; tests
run as Administrator (so ``get_user_chapter_filter`` returns None -> see all).
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.report.pending_membership_applications import (
    pending_membership_applications as report,
)


class TestPendingMembershipApplicationsReport(VereningingenTestCase):
    # ------------------------------------------------------------- helpers

    def _pending_member(self, days_ago=0, chapter=False, **kwargs):
        """Create a Member with a Pending application N days in the past."""
        member = self.create_test_member(
            first_name="Applicant",
            last_name=f"Member{frappe.generate_hash(length=4)}",
            email=f"applicant.{frappe.generate_hash(length=6)}@test.invalid",
            status="Pending",
            application_status="Pending",
            chapter=chapter,
            **kwargs,
        )
        # application_date drives days_pending; set it directly so the SQL
        # DATEDIFF is deterministic.
        app_date = add_days(today(), -days_ago)
        frappe.db.set_value("Member", member.name, "application_date", app_date)
        member.reload()
        return member

    # ------------------------------------------------------------- columns

    def test_get_columns_structure(self):
        columns = report.get_columns()
        fieldnames = [c["fieldname"] for c in columns]
        self.assertEqual(len(columns), 11)
        self.assertEqual(columns[0]["fieldname"], "name")
        self.assertEqual(columns[0]["options"], "Member")
        for fn in ("days_pending", "chapter", "status_indicator", "age"):
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
        self.assertEqual(len(columns), 11)

    # ----------------------------------------------------- core inclusion

    def test_pending_member_appears(self):
        member = self._pending_member(days_ago=5)
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({})
        row = next((r for r in data if r["name"] == member.name), None)
        self.assertIsNotNone(row, "a Pending application must appear")
        # days_pending derives from a server-side DATEDIFF; allow a 1-day skew
        # between the bench's today() (site tz) and MySQL CURDATE() (server tz).
        self.assertGreaterEqual(row["days_pending"], 4)
        self.assertEqual(row["chapter"], "Unassigned")
        self.assertIn("indicator", row["status_indicator"])

    def test_non_pending_member_is_excluded(self):
        # The Member controller forces application_status to "Pending" on create,
        # so flip it directly in the DB to model an already-processed application.
        member = self._pending_member(days_ago=2)
        frappe.db.set_value("Member", member.name, "application_status", "Approved")
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({})
        self.assertNotIn(
            member.name, {r["name"] for r in data}, "non-Pending applications must be excluded"
        )

    # ------------------------------------------------- status indicators

    def test_recent_application_gets_recent_indicator(self):
        member = self._pending_member(days_ago=2)
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({})
        row = next(r for r in data if r["name"] == member.name)
        self.assertIn("Recent", row["status_indicator"])

    def test_aging_application_gets_aging_indicator(self):
        member = self._pending_member(days_ago=10)  # 7 < days <= 14
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({})
        row = next(r for r in data if r["name"] == member.name)
        self.assertIn("Aging", row["status_indicator"])

    def test_overdue_application_gets_overdue_indicator(self):
        member = self._pending_member(days_ago=20)  # > 14
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({})
        row = next(r for r in data if r["name"] == member.name)
        self.assertIn("Overdue", row["status_indicator"])

    # --------------------------------------------------------- date filters

    def test_from_date_filter_excludes_older_applications(self):
        old = self._pending_member(days_ago=30)
        recent = self._pending_member(days_ago=1)
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute(
                {"from_date": add_days(today(), -10)}
            )
        ids = {r["name"] for r in data}
        self.assertIn(recent.name, ids)
        self.assertNotIn(old.name, ids)

    def test_to_date_filter_excludes_newer_applications(self):
        old = self._pending_member(days_ago=30)
        recent = self._pending_member(days_ago=1)
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute(
                {"to_date": add_days(today(), -10)}
            )
        ids = {r["name"] for r in data}
        self.assertIn(old.name, ids)
        self.assertNotIn(recent.name, ids)

    # --------------------------------------------------------- aging filters

    def test_overdue_only_filter(self):
        overdue = self._pending_member(days_ago=20)
        recent = self._pending_member(days_ago=2)
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({"overdue_only": 1})
        ids = {r["name"] for r in data}
        self.assertIn(overdue.name, ids)
        self.assertNotIn(recent.name, ids)

    def test_aging_only_filter(self):
        aging = self._pending_member(days_ago=10)
        recent = self._pending_member(days_ago=2)
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({"aging_only": 1})
        ids = {r["name"] for r in data}
        self.assertIn(aging.name, ids)
        self.assertNotIn(recent.name, ids)

    def test_days_filter(self):
        old = self._pending_member(days_ago=20)
        recent = self._pending_member(days_ago=2)
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({"days_filter": "14"})
        ids = {r["name"] for r in data}
        self.assertIn(old.name, ids)
        self.assertNotIn(recent.name, ids)

    # ----------------------------------------------------- membership type

    def test_membership_type_filter(self):
        matched = self._pending_member(days_ago=2, current_membership_type="GoldXYZ")
        other = self._pending_member(days_ago=2, current_membership_type="SilverXYZ")
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({"membership_type": "GoldXYZ"})
        ids = {r["name"] for r in data}
        self.assertIn(matched.name, ids)
        self.assertNotIn(other.name, ids)

    # ------------------------------------------------------ chapter filter

    def test_chapter_filter_restricts_to_chapter_members(self):
        chapter = self.create_test_chapter()
        in_chapter = self._pending_member(days_ago=2, chapter=chapter.name)
        # A Pending member's auto-created Chapter Member row is Inactive; the
        # report only counts Active rows, so activate it to model an assigned
        # applicant.
        frappe.db.set_value(
            "Chapter Member",
            {"member": in_chapter.name, "parent": chapter.name},
            {"status": "Active", "enabled": 1},
        )
        out_chapter = self._pending_member(days_ago=2, chapter=False)
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({"chapter": chapter.name})
        ids = {r["name"] for r in data}
        self.assertIn(in_chapter.name, ids)
        self.assertNotIn(out_chapter.name, ids)
        row = next(r for r in data if r["name"] == in_chapter.name)
        self.assertEqual(row["chapter"], chapter.name)

    # ----------------------------------------------------- summary / chart

    def test_summary_counts(self):
        self._pending_member(days_ago=20)
        self._pending_member(days_ago=2)
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
        self._pending_member(days_ago=2, chapter=False)
        with self.assertNoErrorLog():
            columns, data, _, chart, summary = report.execute({})
        self.assertIsNotNone(chart)
        self.assertEqual(chart["type"], "bar")
        self.assertIn("Unassigned", chart["data"]["labels"])

    # ------------------------------------------------- pure helper coverage

    def test_get_summary_volunteer_interest_rate(self):
        rows = [
            {"days_pending": 20, "interested_in_volunteering": True},
            {"days_pending": 5, "interested_in_volunteering": False},
        ]
        summary = report.get_summary(rows)
        labels = {s["label"]: s["value"] for s in summary}
        self.assertEqual(labels["Total Pending"], 2)
        self.assertEqual(labels["Overdue (>14 days)"], 1)
        self.assertEqual(labels["Average Days Pending"], 12.5)
        self.assertEqual(labels["Volunteer Interest Rate"], "50.0%")

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

    def test_get_user_chapter_filter_returns_none_for_admin(self):
        # Administrator has unrestricted access -> no SQL chapter filter.
        self.assertIsNone(report.get_user_chapter_filter())
