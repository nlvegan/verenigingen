"""
Real-integration tests for the *Chapter Members* script report
(``verenigingen/verenigingen/report/chapter_members/``).

The report lists the members of a chapter (from the ``Chapter Member`` child
table), joined to the member record and the active membership for the grace
period columns. Access is restricted: only Administrator / System Manager /
Verenigingen Administrator (or a board member of that chapter) may run it,
and only privileged users may apply the ``status`` filter or see pending /
disabled rows.

These tests run as Administrator (the privileged branch) and seed real
Chapters with ``Chapter Member`` rows of varying ``status`` / ``enabled``
values to exercise the status-filter branches and the required-parameter
guard. All data is auto-cleaned.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.report.chapter_members import chapter_members as report


class TestChapterMembersReport(VereningingenTestCase):
    # ------------------------------------------------------------- helpers

    def _member(self):
        return self.create_test_member(
            first_name="Chap",
            last_name=f"Member{frappe.generate_hash(length=4)}",
            email=f"chap.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )

    def _add_to_chapter(self, chapter, member, status="Active", enabled=1, leave_reason=None):
        chapter.append(
            "members",
            {
                "member": member.name,
                "chapter_join_date": today(),
                "status": status,
                "enabled": enabled,
                "leave_reason": leave_reason,
            },
        )
        chapter.save()

    # ------------------------------------------------------------- guards

    def test_missing_chapter_raises(self):
        with self.assertRaises(frappe.ValidationError):
            report.execute({})

    def test_missing_chapter_none_filters_raises(self):
        with self.assertRaises(frappe.ValidationError):
            report.execute(None)

    # ------------------------------------------------------------- columns

    def test_columns_structure(self):
        chapter = self.create_test_chapter()
        with self.assertNoErrorLog():
            columns, _ = report.execute({"chapter": chapter.name})
        fieldnames = [c["fieldname"] for c in columns]
        self.assertEqual(len(columns), 9)
        self.assertIn("member", fieldnames)
        self.assertIn("grace_period_status", fieldnames)
        self.assertIn("leave_reason", fieldnames)

    # ------------------------------------------------------------- data rows

    def test_active_member_appears(self):
        chapter = self.create_test_chapter()
        member = self._member()
        self._add_to_chapter(chapter, member, status="Active")

        with self.assertNoErrorLog():
            _, data = report.execute({"chapter": chapter.name})
        row = next((r for r in data if r["member"] == member.name), None)
        self.assertIsNotNone(row, "active chapter member must appear")
        self.assertEqual(row["status"], "Active")
        self.assertEqual(row["enabled"], 1)

    def test_null_status_defaults_to_active(self):
        chapter = self.create_test_chapter()
        member = self._member()
        self._add_to_chapter(chapter, member, status="Active")
        # Force the stored status to NULL to exercise the COALESCE(..,'Active').
        cm_name = frappe.db.get_value("Chapter Member", {"parent": chapter.name, "member": member.name})
        frappe.db.set_value("Chapter Member", cm_name, "status", None, update_modified=False)

        with self.assertNoErrorLog():
            _, data = report.execute({"chapter": chapter.name})
        row = next((r for r in data if r["member"] == member.name), None)
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "Active", "NULL status must surface as 'Active'")

    def test_other_chapter_members_excluded(self):
        chapter_a = self.create_test_chapter()
        chapter_b = self.create_test_chapter()
        member_a = self._member()
        member_b = self._member()
        self._add_to_chapter(chapter_a, member_a)
        self._add_to_chapter(chapter_b, member_b)

        with self.assertNoErrorLog():
            _, data = report.execute({"chapter": chapter_a.name})
        ids = {r["member"] for r in data}
        self.assertIn(member_a.name, ids)
        self.assertNotIn(member_b.name, ids, "members of another chapter must not appear")

    # ------------------------------------------------------------- status filter (privileged)

    def test_status_filter_pending(self):
        chapter = self.create_test_chapter()
        active = self._member()
        pending = self._member()
        self._add_to_chapter(chapter, active, status="Active")
        self._add_to_chapter(chapter, pending, status="Pending")

        with self.assertNoErrorLog():
            _, data = report.execute({"chapter": chapter.name, "status": "Pending"})
        ids = {r["member"] for r in data}
        self.assertIn(pending.name, ids)
        self.assertNotIn(active.name, ids)

    def test_status_filter_active_includes_null(self):
        chapter = self.create_test_chapter()
        member = self._member()
        self._add_to_chapter(chapter, member, status="Active")
        cm_name = frappe.db.get_value("Chapter Member", {"parent": chapter.name, "member": member.name})
        frappe.db.set_value("Chapter Member", cm_name, "status", None, update_modified=False)

        with self.assertNoErrorLog():
            _, data = report.execute({"chapter": chapter.name, "status": "Active"})
        ids = {r["member"] for r in data}
        self.assertIn(member.name, ids, "Active filter must also match NULL status rows")

    def test_status_filter_inactive(self):
        chapter = self.create_test_chapter()
        active = self._member()
        inactive = self._member()
        self._add_to_chapter(chapter, active, status="Active")
        self._add_to_chapter(chapter, inactive, status="Inactive", enabled=0, leave_reason="Moved away")

        with self.assertNoErrorLog():
            _, data = report.execute({"chapter": chapter.name, "status": "Inactive"})
        ids = {r["member"] for r in data}
        self.assertIn(inactive.name, ids)
        self.assertNotIn(active.name, ids)
        row = next(r for r in data if r["member"] == inactive.name)
        self.assertEqual(row["leave_reason"], "Moved away")

    # ------------------------------------------------------------- empty result

    def test_empty_chapter_returns_no_rows(self):
        chapter = self.create_test_chapter()
        with self.assertNoErrorLog():
            _, data = report.execute({"chapter": chapter.name})
        self.assertEqual(data, [])
