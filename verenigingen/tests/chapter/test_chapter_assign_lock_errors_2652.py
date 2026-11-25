"""#2652: ``assign_member_to_chapter`` and ``MemberManager.add_member`` must not flatten 1213/1205.

``ChapterMembershipManager.assign_member_to_chapter`` ended in ``except Exception: return
{"success": False}``, and the audit-comment / tracking-field writes beneath it swallowed too. A
deadlock (1213) means the server already rolled the transaction back, so every caller reading the
dict carried on against a transaction that no longer held its earlier writes; a lock wait
timeout (1205) leaves the unit of work half-applied. Both must propagate (#2700, ruling on #2652).
Every ordinary failure keeps the dict contract, which the control tests pin.

The lock error is injected at the DRIVER (``Cursor.execute`` raises ``OperationalError(1213|1205)``
on one statement, which frappe's dispatch wraps into ``QueryDeadlockError`` / ``QueryTimeoutError``),
so it passes through every real layer. Probe shortcut, stated: it is injected, not provoked (a real
deadlock needs a second connection), so the server does not actually roll back; these tests pin
WHO sees the error, not the database state afterwards. Each test asserts the injection fired.
"""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import frappe

from verenigingen.services.chapter.chapter_membership_manager import ChapterMembershipManager
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

LOCK_CODES = ((1213, frappe.QueryDeadlockError), (1205, frappe.QueryTimeoutError))
ROSTER_INSERT = "`tabChapter Member`"
COMMENT_INSERT = "`tabComment`"
MEMBER_TRACKING_UPDATE = ("`tabMember`", "chapter_change_reason")


class TestChapterAssignLockErrors2652(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self.member = self.create_test_member(
            first_name="Lock2652", last_name="Member", birth_date="1990-01-01", status="Active"
        )
        self.chapter = self.create_test_chapter()
        self.expectErrorLog(
            "Chapter Manager Error: Failed to add member",
            "Chapter Manager Error: Failed to create comment",
            "ChapterMembershipManager",
            "Chapter Roster Update Error",
            "Approval Chapter Assignment Failed",
            "Bulk Assignment Error",
            "Secure Operation Failed",
        )

    def _driver_raising_2652(self, code, fragment, *, startswith=("INSERT", "UPDATE")):
        """``Cursor.execute`` raises OperationalError(code) on a write containing *fragment*."""
        hits = []
        cursor_cls = frappe.db._cursor.__class__
        real_execute = cursor_cls.execute
        fragments = (fragment,) if isinstance(fragment, str) else fragment

        def execute(cursor, query, *args, **kwargs):
            if (
                isinstance(query, str)
                and query.lstrip().upper().startswith(startswith)
                and all(f in query for f in fragments)
            ):
                hits.append(query)
                raise frappe.db.OperationalError(code, "injected at the driver")
            return real_execute(cursor, query, *args, **kwargs)

        # Mock justified: fault injection at the driver; calls through for every other statement
        return patch.object(cursor_cls, "execute", execute), hits

    @contextmanager
    def _undone_2652(self):
        """Undo what the faulted call already wrote (the roster row precedes the comment), so the
        next subTest starts clean; a savepoint, not a rollback, which would drop the fixtures."""
        name = f"t2652_{frappe.generate_hash(length=8)}"
        frappe.db.savepoint(name)
        try:
            yield
        finally:
            frappe.db.rollback(save_point=name)

    def _assign_2652(self):
        return ChapterMembershipManager.assign_member_to_chapter(
            member_id=self.member.name, chapter_name=self.chapter.name, notify=False
        )

    def _member_manager_2652(self):
        return frappe.get_doc("Chapter", self.chapter.name).member_manager

    def _on_roster_2652(self):
        return frappe.db.exists("Chapter Member", {"parent": self.chapter.name, "member": self.member.name})

    # -- assign_member_to_chapter -------------------------------------------------------------

    def test_assign_raises_a_lock_error_on_the_roster_write(self):
        for code, error in LOCK_CODES:
            with self.subTest(code=code):
                inject, hits = self._driver_raising_2652(code, ROSTER_INSERT, startswith=("INSERT",))
                with inject, self.assertRaises(error):
                    self._assign_2652()
                self.assertTrue(hits, "the injection must have fired on the Chapter Member insert")

    def test_assign_raises_a_lock_error_on_the_audit_comment(self):
        for code, error in LOCK_CODES:
            with self.subTest(code=code):
                with self._undone_2652():
                    inject, hits = self._driver_raising_2652(code, COMMENT_INSERT, startswith=("INSERT",))
                    with inject, self.assertRaises(error):
                        self._assign_2652()
                    self.assertTrue(hits, "the injection must have fired on the Comment insert")

    def test_assign_raises_a_lock_error_on_the_member_tracking_update(self):
        for code, error in LOCK_CODES:
            with self.subTest(code=code):
                with self._undone_2652():
                    inject, hits = self._driver_raising_2652(
                        code, MEMBER_TRACKING_UPDATE, startswith=("UPDATE",)
                    )
                    with inject, self.assertRaises(error):
                        self._assign_2652()
                    self.assertTrue(hits, "the injection must have fired on the Member tracking update")

    def test_control_an_ordinary_failure_keeps_the_dict_contract(self):
        """A non-lock OperationalError (1054) at the same statement is an error dict, as before."""
        inject, hits = self._driver_raising_2652(1054, ROSTER_INSERT, startswith=("INSERT",))
        with inject:
            result = self._assign_2652()
        self.assertTrue(hits, "the injection must have fired on the Chapter Member insert")
        self.assertFalse(result["success"], result)
        self.assertTrue(result.get("error"), result)

    def test_control_unknown_chapter_and_member_keep_the_dict_contract(self):
        missing_chapter = ChapterMembershipManager.assign_member_to_chapter(
            member_id=self.member.name, chapter_name="No Such Chapter 2652", notify=False
        )
        self.assertFalse(missing_chapter["success"])
        self.assertIn("not found", missing_chapter["error"])
        missing_member = ChapterMembershipManager.assign_member_to_chapter(
            member_id="NO-SUCH-MEMBER-2652", chapter_name=self.chapter.name, notify=False
        )
        self.assertFalse(missing_member["success"])

    def test_control_a_clean_assignment_still_succeeds(self):
        result = self._assign_2652()
        self.assertTrue(result["success"], result)
        self.assertTrue(self._on_roster_2652())

    # -- MemberManager.add_member -------------------------------------------------------------

    def test_add_member_raises_a_lock_error_on_the_roster_write(self):
        """Already true on develop (add_member's outer handler logs and re-raises): pins it."""
        for code, error in LOCK_CODES:
            with self.subTest(code=code):
                inject, hits = self._driver_raising_2652(code, ROSTER_INSERT, startswith=("INSERT",))
                with inject, self.assertRaises(error):
                    self._member_manager_2652().add_member(self.member.name, notify=False)
                self.assertTrue(hits)

    def test_add_member_raises_a_lock_error_on_the_audit_comment(self):
        """The new-row branch writes the audit comment AFTER the roster save; both the comment
        helper and add_member's own wrapper used to swallow a lock error there and report success."""
        for code, error in LOCK_CODES:
            with self.subTest(code=code):
                with self._undone_2652():
                    inject, hits = self._driver_raising_2652(code, COMMENT_INSERT, startswith=("INSERT",))
                    with inject, self.assertRaises(error):
                        self._member_manager_2652().add_member(self.member.name, notify=False)
                    self.assertTrue(hits, "the injection must have fired on the Comment insert")

    def test_add_member_reenable_branch_raises_a_lock_error_on_the_audit_comment(self):
        self.assertTrue(self._member_manager_2652().add_member(self.member.name, notify=False)["success"])
        removed = self._member_manager_2652().remove_member(self.member.name, "2652 setup")
        self.assertTrue(removed["success"], removed)
        self.assertEqual(
            frappe.db.get_value(
                "Chapter Member", {"parent": self.chapter.name, "member": self.member.name}, "enabled"
            ),
            0,
            "setup must leave a DISABLED row so add_member takes the re-enable branch",
        )
        inject, hits = self._driver_raising_2652(1213, COMMENT_INSERT, startswith=("INSERT",))
        with inject, self.assertRaises(frappe.QueryDeadlockError):
            self._member_manager_2652().add_member(self.member.name, notify=False)
        self.assertTrue(hits)

    def test_control_add_member_keeps_its_dict_for_ordinary_refusals(self):
        self.assertTrue(self._member_manager_2652().add_member(self.member.name, notify=False)["success"])
        again = self._member_manager_2652().add_member(self.member.name, notify=False)
        self.assertEqual(again["action"], "already_exists")
        self.assertFalse(again["success"])

    def test_control_an_ordinary_comment_failure_does_not_fail_the_add(self):
        """The comment is best-effort for every non-lock error: a 1054 there still adds the member."""
        inject, hits = self._driver_raising_2652(1054, COMMENT_INSERT, startswith=("INSERT",))
        with inject:
            result = self._member_manager_2652().add_member(self.member.name, notify=False)
        self.assertTrue(hits, "the injection must have fired on the Comment insert")
        self.assertTrue(result["success"], result)

    # -- callers one frame up: none may swallow the propagating error --------------------------

    def test_bulk_add_members_raises_a_lock_error(self):
        for code, error in LOCK_CODES:
            with self.subTest(code=code):
                inject, hits = self._driver_raising_2652(code, ROSTER_INSERT, startswith=("INSERT",))
                with inject, self.assertRaises(error):
                    self._member_manager_2652().bulk_add_members([{"member_id": self.member.name}])
                self.assertTrue(hits)

    def test_control_bulk_add_members_reports_an_ordinary_failure_in_errors(self):
        inject, hits = self._driver_raising_2652(1054, ROSTER_INSERT, startswith=("INSERT",))
        with inject:
            result = self._member_manager_2652().bulk_add_members([{"member_id": self.member.name}])
        self.assertTrue(hits)
        self.assertEqual(result["processed"], 0)
        self.assertEqual(len(result["errors"]), 1, result)

    def test_roster_helper_raises_a_lock_error(self):
        from verenigingen.api.member_management import add_member_to_chapter_roster

        for code, error in LOCK_CODES:
            with self.subTest(code=code):
                inject, hits = self._driver_raising_2652(code, ROSTER_INSERT, startswith=("INSERT",))
                with inject, self.assertRaises(error):
                    add_member_to_chapter_roster(self.member.name, self.chapter.name)
                self.assertTrue(hits)

    def test_application_review_assignment_raises_a_lock_error(self):
        from verenigingen.api.membership_application_review import assign_member_to_chapter

        for code, error in LOCK_CODES:
            with self.subTest(code=code):
                inject, hits = self._driver_raising_2652(code, ROSTER_INSERT, startswith=("INSERT",))
                with inject, self.assertRaises(error):
                    assign_member_to_chapter(self.member, self.chapter.name, notify=False)
                self.assertTrue(hits)

    def test_control_application_review_assignment_logs_an_ordinary_failure(self):
        from verenigingen.api.membership_application_review import assign_member_to_chapter

        inject, hits = self._driver_raising_2652(1054, ROSTER_INSERT, startswith=("INSERT",))
        with inject, self.assertErrorLog("Approval Chapter Assignment Failed"):
            assign_member_to_chapter(self.member, self.chapter.name, notify=False)  # must not raise
        self.assertTrue(hits)

    def test_mijnrood_import_assignment_raises_a_lock_error(self):
        from verenigingen.verenigingen.doctype.mijnrood_csv_import.mijnrood_csv_import import (
            MijnroodCSVImport,
        )

        importer = SimpleNamespace(name="IMPORT-2652", auto_create_chapters=0, default_region=None)
        for code, error in LOCK_CODES:
            with self.subTest(code=code):
                inject, hits = self._driver_raising_2652(code, ROSTER_INSERT, startswith=("INSERT",))
                with inject, self.assertRaises(error):
                    MijnroodCSVImport._assign_member_to_chapter(importer, self.member, self.chapter.name)
                self.assertTrue(hits)

    def test_control_mijnrood_import_assignment_swallows_an_ordinary_failure(self):
        from verenigingen.verenigingen.doctype.mijnrood_csv_import.mijnrood_csv_import import (
            MijnroodCSVImport,
        )

        importer = SimpleNamespace(name="IMPORT-2652", auto_create_chapters=0, default_region=None)
        inject, hits = self._driver_raising_2652(1054, ROSTER_INSERT, startswith=("INSERT",))
        with inject:
            MijnroodCSVImport._assign_member_to_chapter(importer, self.member, self.chapter.name)
        self.assertTrue(hits)

    def test_join_request_approval_surfaces_the_lock_error_and_rolls_back(self):
        """The #1703/#1632 undo path used to receive a ValidationError built from the dict; it
        now receives the real lock error and must still roll the Approved save back."""
        for code, error in LOCK_CODES:
            with self.subTest(code=code):
                request = frappe.get_doc(
                    {
                        "doctype": "Chapter Join Request",
                        "member": self.member.name,
                        "chapter": self.chapter.name,
                        "introduction": "2652",
                        "status": "Pending",
                        "request_date": frappe.utils.today(),
                    }
                ).insert()
                inject, hits = self._driver_raising_2652(code, ROSTER_INSERT, startswith=("INSERT",))
                with inject, self.assertRaises(error):
                    request.approve_request()
                self.assertTrue(hits)
                self.assertEqual(
                    frappe.db.get_value("Chapter Join Request", request.name, "status"),
                    "Pending",
                    "the Approved save must have been rolled back",
                )
                frappe.delete_doc("Chapter Join Request", request.name, force=True)
