"""
Real-integration tests for the *New Members* script report
(``verenigingen/verenigingen/report/new_members/``).

The report lists Active members who became members within a recency window
(default 30 days), keyed on the earliest membership ``start_date`` (falling
back to the member ``creation`` date). It exposes ``days_threshold`` /
``from_date`` / ``to_date`` / ``chapter`` / ``membership_type`` filters, a
summary block and a weekly-trend chart.

These tests run as Administrator (so ``get_user_accessible_chapters`` returns
None -> see-all) and seed real Members / Memberships / Chapter Member rows to
exercise the recency window, the filter branches and the status-indicator /
summary / chart pure helpers.
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.report.new_members import new_members as report


class TestNewMembersReport(VereningingenTestCase):
    # ------------------------------------------------------------- helpers

    def _new_member(self, days_ago=2, membership_type=None, chapter=None):
        # chapter=False skips the factory's default-chapter auto-assignment so
        # the only Chapter Member row is the one we explicitly append (the
        # report's primary_chapter is the most recent Chapter Member row).
        member = self.create_test_member(
            chapter=False,
            first_name="Newbie",
            last_name=f"Member{frappe.generate_hash(length=4)}",
            email=f"newbie.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        mtype = membership_type or self.create_test_membership_type()
        membership = self.create_test_membership(member=member.name, membership_type=mtype.name)
        membership.submit()
        start = add_days(today(), -days_ago)
        frappe.db.set_value(
            "Membership",
            membership.name,
            {"start_date": start, "status": "Active"},
            update_modified=False,
        )
        if chapter:
            chapter.append(
                "members",
                {"member": member.name, "chapter_join_date": today(), "status": "Active", "enabled": 1},
            )
            chapter.save()
        return member, membership, mtype

    # ------------------------------------------------------------- columns

    def test_columns_structure(self):
        columns = report.get_columns()
        fieldnames = [c["fieldname"] for c in columns]
        self.assertEqual(len(columns), 9)
        self.assertIn("member_name", fieldnames)
        self.assertIn("member_since", fieldnames)
        self.assertIn("days_active", fieldnames)

    def test_execute_returns_five_tuple(self):
        with self.assertNoErrorLog():
            result = report.execute({})
        self.assertEqual(len(result), 5)
        columns, data, _none, chart, summary = result
        self.assertEqual(_none, None)
        self.assertIsInstance(data, list)

    # ------------------------------------------------------------- recency window

    def test_recent_member_appears(self):
        member, _, _ = self._new_member(days_ago=3)
        with self.assertNoErrorLog():
            _, data, _, _, _ = report.execute({})
        ids = {r["member_name"] for r in data}
        self.assertIn(member.name, ids, "member who joined 3 days ago must appear")

    def test_old_member_excluded_by_default_window(self):
        member, _, _ = self._new_member(days_ago=120)
        with self.assertNoErrorLog():
            _, data, _, _, _ = report.execute({})
        ids = {r["member_name"] for r in data}
        self.assertNotIn(member.name, ids, "member who joined 120 days ago is outside the 30-day window")

    def test_days_threshold_widens_window(self):
        member, _, _ = self._new_member(days_ago=60)
        with self.assertNoErrorLog():
            _, data, _, _, _ = report.execute({"days_threshold": 90})
        ids = {r["member_name"] for r in data}
        self.assertIn(member.name, ids, "a 90-day threshold must include a 60-day-old member")

    # ------------------------------------------------------------- filters

    def test_membership_type_filter(self):
        type_a = self.create_test_membership_type()
        type_b = self.create_test_membership_type()
        member_a, _, _ = self._new_member(days_ago=2, membership_type=type_a)
        member_b, _, _ = self._new_member(days_ago=2, membership_type=type_b)

        with self.assertNoErrorLog():
            _, data, _, _, _ = report.execute({"membership_type": type_a.name})
        ids = {r["member_name"] for r in data}
        self.assertIn(member_a.name, ids)
        self.assertNotIn(member_b.name, ids)

    def test_chapter_filter(self):
        chapter = self.create_test_chapter()
        in_chapter, _, _ = self._new_member(days_ago=2, chapter=chapter)
        out_chapter, _, _ = self._new_member(days_ago=2)

        with self.assertNoErrorLog():
            _, data, _, _, _ = report.execute({"chapter": chapter.name})
        ids = {r["member_name"] for r in data}
        self.assertIn(in_chapter.name, ids)
        self.assertNotIn(out_chapter.name, ids)

    def test_to_date_filter_excludes_later_joiners(self):
        # Member joined ~5 days ago; a to_date 10 days ago must exclude them.
        member, _, _ = self._new_member(days_ago=5)
        with self.assertNoErrorLog():
            _, data, _, _, _ = report.execute({"to_date": add_days(today(), -10)})
        ids = {r["member_name"] for r in data}
        self.assertNotIn(member.name, ids)

    def test_from_date_narrows_window(self):
        member, _, _ = self._new_member(days_ago=20)
        # from_date 5 days ago is more restrictive than the default 30-day window.
        with self.assertNoErrorLog():
            _, data, _, _, _ = report.execute({"from_date": add_days(today(), -5)})
        ids = {r["member_name"] for r in data}
        self.assertNotIn(member.name, ids, "from_date later than join date must exclude the member")

    # ------------------------------------------------------------- chapter display

    def test_primary_chapter_displayed(self):
        chapter = self.create_test_chapter()
        member, _, _ = self._new_member(days_ago=2, chapter=chapter)
        with self.assertNoErrorLog():
            _, data, _, _, _ = report.execute({})
        row = next((r for r in data if r["member_name"] == member.name), None)
        self.assertIsNotNone(row)
        self.assertEqual(row["primary_chapter"], chapter.name)

    # ------------------------------------------------------------- summary / chart

    def test_summary_and_chart_present_with_data(self):
        member, _, _ = self._new_member(days_ago=2)
        with self.assertNoErrorLog():
            _, data, _, chart, summary = report.execute({})
        labels = {s["label"]: s["value"] for s in summary}
        self.assertIn("Total New Members", labels)
        self.assertGreaterEqual(labels["Total New Members"], 1)
        self.assertEqual(labels["Total New Members"], len(data))
        self.assertIsNotNone(chart)
        self.assertEqual(chart["type"], "line")

    def test_summary_empty_when_no_data(self):
        self.assertEqual(report.get_summary([]), [])

    def test_chart_none_when_no_data(self):
        self.assertIsNone(report.get_chart_data([]))

    # ------------------------------------------------------------- status indicator

    def test_status_indicator_buckets(self):
        self.assertIn("Very New", report.get_status_indicator(3, False))
        self.assertIn("New", report.get_status_indicator(10, False))
        self.assertIn("Recent", report.get_status_indicator(20, False))
        self.assertIn("Established", report.get_status_indicator(90, False))
        self.assertIn("Chapter Change", report.get_status_indicator(1, True))
