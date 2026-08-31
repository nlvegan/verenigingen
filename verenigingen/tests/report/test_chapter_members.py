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


class ChapterMembersFixtures:
    """Fixtures shared by both classes below.

    A mixin rather than a copy in each class: the two classes had a
    byte-identical `_member` and two chapter-row helpers that differed only in
    whether they took a Chapter doc or a docname. That is the shape the
    duplicate-helper ratchet exists to stop, inside one file where the ratchet
    cannot see it (it keys on name-across-FILES).
    """

    def _member(self):
        return self.create_test_member(
            first_name="Chap",
            last_name=f"Member{frappe.generate_hash(length=4)}",
            email=f"chap.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )

    def _add_to_chapter(self, chapter, member, status="Active", enabled=1, leave_reason=None):
        """`chapter` may be a Chapter doc or a docname."""
        doc = chapter if hasattr(chapter, "append") else frappe.get_doc("Chapter", chapter)
        doc.append(
            "members",
            {
                "member": member.name,
                "chapter_join_date": today(),
                "status": status,
                "enabled": enabled,
                "leave_reason": leave_reason,
            },
        )
        doc.save()
        return doc


class TestChapterMembersReport(ChapterMembersFixtures, VereningingenTestCase):
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


class TestChapterMembersReportBoardAccess(ChapterMembersFixtures, VereningingenTestCase):
    """The unprivileged branch: a chapter board member running the report.

    The report's own JSON grants the *Verenigingen Chapter Board Member* role,
    and ``execute`` has a branch that is supposed to let such a user through for
    their own chapter. Every test above runs as Administrator, so that branch was
    never exercised -- and it was dead: the guard asked
    ``frappe.db.exists("Verenigingen Chapter Board Member", ...)``, which is the
    *Role* name, not the DocType. ``frappe.db.exists`` on a doctype whose table is
    absent goes through ``frappe.db.sql(..., ignore=True)``, which swallows
    MariaDB 1146 and returns ``None`` -- indistinguishable from "no such row". So
    the gate always threw and no board member could open the report (#677).

    Both halves are asserted here, because correcting the name *activates* a check
    that had never run: a board member of the chapter must get through, and a
    volunteer who is not on that board must still be refused.
    """

    def _unprivileged_user(self, tag):
        return self.create_test_user(
            email=f"cm_{tag}_{frappe.generate_hash(length=8)}@test.invalid",
            roles=["Verenigingen Chapter Board Member"],
        )

    def _member_with_user(self, user):
        member = self.create_test_member(
            first_name="Board",
            last_name=f"Runner{frappe.generate_hash(length=4)}",
            email=f"board.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        member.user = user.name
        member.save()
        return member

    def _seat_on_board(self, chapter, volunteer):
        role = self.create_test_chapter_role()
        doc = frappe.get_doc("Chapter", chapter.name)
        doc.append(
            "board_members",
            {
                "volunteer": volunteer.name,
                "chapter_role": role.name,
                "from_date": today(),
                "is_active": 1,
            },
        )
        doc.save()
        return doc

    def test_board_member_can_run_the_report_for_their_own_chapter(self):
        """The defect: on develop this throws, for the very chapter they sit on."""
        chapter = self.create_test_chapter()
        user = self._unprivileged_user("board")
        member = self._member_with_user(user)
        volunteer = self.create_test_volunteer(member=member.name)
        self._seat_on_board(chapter, volunteer)

        listed = self._member()
        self._add_to_chapter(chapter.name, listed, status="Active")

        with self.as_user(user.name):
            _, data = report.execute({"chapter": chapter.name})

        self.assertIn(
            listed.name,
            {r["member"] for r in data},
            "a board member must see their own chapter's members",
        )

    def test_non_board_volunteer_is_still_refused(self):
        """Control: correcting the doctype name must not open the report up.

        Same shape as the test above -- member, linked user, volunteer -- with the
        single difference that the volunteer holds no seat on this chapter's board.
        If this passed, the fix would have replaced a gate that never opens with
        one that never closes.
        """
        chapter = self.create_test_chapter()
        user = self._unprivileged_user("outsider")
        member = self._member_with_user(user)
        self.create_test_volunteer(member=member.name)

        with self.as_user(user.name):
            with self.assertRaises(frappe.ValidationError) as ctx:
                report.execute({"chapter": chapter.name})

        self.assertIn("board member", str(ctx.exception))

    def test_board_member_of_another_chapter_is_refused(self):
        """Control: a real, seated board member is still scoped to their chapter."""
        own_chapter = self.create_test_chapter()
        other_chapter = self.create_test_chapter()
        user = self._unprivileged_user("elsewhere")
        member = self._member_with_user(user)
        volunteer = self.create_test_volunteer(member=member.name)
        self._seat_on_board(own_chapter, volunteer)

        with self.as_user(user.name):
            with self.assertRaises(frappe.ValidationError):
                report.execute({"chapter": other_chapter.name})

    def test_board_member_sees_pending_members(self):
        """The second, identical guard 44 lines below governs ``can_view_pending``.

        Without it a board member who *could* open the report would still be served
        the filtered row set, so this pins the sibling site too (#399).
        """
        chapter = self.create_test_chapter()
        user = self._unprivileged_user("pending")
        member = self._member_with_user(user)
        volunteer = self.create_test_volunteer(member=member.name)
        self._seat_on_board(chapter, volunteer)

        pending = self._member()
        self._add_to_chapter(chapter.name, pending, status="Pending")

        with self.as_user(user.name):
            _, data = report.execute({"chapter": chapter.name})

        self.assertIn(
            pending.name,
            {r["member"] for r in data},
            "a board member must be able to see pending members of their chapter",
        )

    def test_user_without_a_member_record_is_refused(self):
        """Control at the outer guard: no Member row -> refused before the board check."""
        chapter = self.create_test_chapter()
        user = self._unprivileged_user("nomember")

        with self.as_user(user.name):
            with self.assertRaises(frappe.ValidationError) as ctx:
                report.execute({"chapter": chapter.name})

        self.assertIn("must be a member", str(ctx.exception))
