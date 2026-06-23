"""
Real-integration tests for the *Recent Chapter Changes* script report
(``verenigingen/verenigingen/report/recent_chapter_changes/``).

The report lists members modified within a recency window (default 30 days),
showing their ``previous_chapter`` vs current chapter and classifying the
change (initial assignment / transfer / removal). It exposes
``days_threshold`` / ``from_date`` / ``to_date`` / ``previous_chapter`` /
``current_chapter`` / ``changed_by`` filters, a summary block and a
change-type donut chart.

Tests run as Administrator (``get_user_accessible_chapters`` -> None ->
see-all) and seed real Members + Chapter Member rows + ``previous_chapter``
values to exercise the change-type classification, the filter branches and
the pure summary / chart / change-type helpers.
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.report.recent_chapter_changes import recent_chapter_changes as report


class TestRecentChapterChangesReport(VereningingenTestCase):
    # ------------------------------------------------------------- helpers

    def _member(self, previous_chapter=None, chapter=None, changed_by=None, reason=None):
        member = self.create_test_member(
            chapter=False,
            first_name="Mover",
            last_name=f"Member{frappe.generate_hash(length=4)}",
            email=f"mover.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        updates = {}
        if previous_chapter is not None:
            updates["previous_chapter"] = previous_chapter
        if changed_by is not None:
            updates["chapter_assigned_by"] = changed_by
        if reason is not None:
            updates["chapter_change_reason"] = reason
        if updates:
            frappe.db.set_value("Member", member.name, updates, update_modified=False)
        if chapter:
            chapter.append(
                "members",
                {"member": member.name, "chapter_join_date": today(), "status": "Active", "enabled": 1},
            )
            chapter.save()
        member.reload()
        return member

    # ------------------------------------------------------------- columns

    def test_columns_structure(self):
        columns = report.get_columns()
        fieldnames = [c["fieldname"] for c in columns]
        self.assertEqual(len(columns), 9)
        self.assertIn("previous_chapter", fieldnames)
        self.assertIn("current_chapter", fieldnames)
        self.assertIn("change_type", fieldnames)

    def test_execute_returns_five_tuple(self):
        with self.assertNoErrorLog():
            result = report.execute({})
        self.assertEqual(len(result), 5)
        columns, data, _none, chart, summary = result
        self.assertEqual(_none, None)
        self.assertIsInstance(data, list)

    # ------------------------------------------------------------- change types

    def test_initial_assignment_change_type(self):
        chapter = self.create_test_chapter()
        member = self._member(chapter=chapter)  # no previous chapter -> initial
        with self.assertNoErrorLog():
            _, data, _, _, _ = report.execute({})
        row = next((r for r in data if r["member_name"] == member.name), None)
        self.assertIsNotNone(row, "recently-modified member must appear")
        self.assertIn("Initial Assignment", row["change_type"])
        self.assertEqual(row["current_chapter"], chapter.name)

    def test_transfer_change_type(self):
        prev_chapter = self.create_test_chapter()
        new_chapter = self.create_test_chapter()
        member = self._member(previous_chapter=prev_chapter.name, chapter=new_chapter)
        with self.assertNoErrorLog():
            _, data, _, _, _ = report.execute({})
        row = next((r for r in data if r["member_name"] == member.name), None)
        self.assertIsNotNone(row)
        self.assertIn("Chapter Transfer", row["change_type"])
        self.assertEqual(row["previous_chapter"], prev_chapter.name)

    def test_removed_from_chapter_change_type(self):
        prev_chapter = self.create_test_chapter()
        member = self._member(previous_chapter=prev_chapter.name)  # no current chapter
        with self.assertNoErrorLog():
            _, data, _, _, _ = report.execute({})
        row = next((r for r in data if r["member_name"] == member.name), None)
        self.assertIsNotNone(row)
        self.assertIn("Removed from Chapter", row["change_type"])

    # ------------------------------------------------------------- get_change_type helper

    def test_get_change_type_helper_branches(self):
        self.assertIn("Initial Assignment", report.get_change_type(None, "Chap-A"))
        self.assertIn("Removed from Chapter", report.get_change_type("Chap-A", None))
        self.assertIn("Chapter Transfer", report.get_change_type("Chap-A", "Chap-B"))
        self.assertIn("Unknown", report.get_change_type(None, None))

    # ------------------------------------------------------------- filters

    def test_previous_chapter_filter(self):
        prev_chapter = self.create_test_chapter()
        matching = self._member(previous_chapter=prev_chapter.name)
        other = self._member(previous_chapter=self.create_test_chapter().name)

        with self.assertNoErrorLog():
            _, data, _, _, _ = report.execute({"previous_chapter": prev_chapter.name})
        ids = {r["member_name"] for r in data}
        self.assertIn(matching.name, ids)
        self.assertNotIn(other.name, ids)

    def test_changed_by_filter(self):
        actor = "Administrator"
        member = self._member(changed_by=actor)
        with self.assertNoErrorLog():
            _, data, _, _, _ = report.execute({"changed_by": actor})
        ids = {r["member_name"] for r in data}
        self.assertIn(member.name, ids)
        self.assertTrue(all(r["chapter_assigned_by"] == actor for r in data))

    def test_current_chapter_filter(self):
        chapter = self.create_test_chapter()
        in_chapter = self._member(chapter=chapter)
        out_chapter = self._member(chapter=self.create_test_chapter())

        with self.assertNoErrorLog():
            _, data, _, _, _ = report.execute({"current_chapter": chapter.name})
        ids = {r["member_name"] for r in data}
        self.assertIn(in_chapter.name, ids)
        self.assertNotIn(out_chapter.name, ids)

    def test_days_threshold_excludes_old_modifications(self):
        # A 0-day threshold means "modified after today" -> nothing recent
        # qualifies (modified timestamps are < the threshold boundary). The
        # report must not crash and must return a list.
        with self.assertNoErrorLog():
            _, data, _, _, _ = report.execute({"days_threshold": 0})
        self.assertIsInstance(data, list)

    def test_to_date_with_from_date_builds_between_filter(self):
        # Exercise the between-filter branch (both from_date and to_date set).
        with self.assertNoErrorLog():
            _, data, _, _, _ = report.execute(
                {"from_date": add_days(today(), -10), "to_date": today()}
            )
        self.assertIsInstance(data, list)

    # ------------------------------------------------------------- reason / days_ago

    def test_reason_and_days_ago_populated(self):
        member = self._member(reason="Relocated", chapter=self.create_test_chapter())
        with self.assertNoErrorLog():
            _, data, _, _, _ = report.execute({})
        row = next((r for r in data if r["member_name"] == member.name), None)
        self.assertIsNotNone(row)
        self.assertEqual(row["chapter_change_reason"], "Relocated")
        self.assertGreaterEqual(row["days_ago"], 0)

    # ------------------------------------------------------------- summary / chart

    def test_summary_and_chart_present_with_data(self):
        member = self._member(chapter=self.create_test_chapter())
        with self.assertNoErrorLog():
            _, data, _, chart, summary = report.execute({})
        labels = {s["label"]: s["value"] for s in summary}
        self.assertIn("Total Chapter Changes", labels)
        self.assertEqual(labels["Total Chapter Changes"], len(data))
        self.assertIsNotNone(chart)
        self.assertEqual(chart["type"], "donut")

    def test_summary_empty_when_no_data(self):
        self.assertEqual(report.get_summary([]), [])

    def test_chart_none_when_no_data(self):
        self.assertIsNone(report.get_chart_data([]))
