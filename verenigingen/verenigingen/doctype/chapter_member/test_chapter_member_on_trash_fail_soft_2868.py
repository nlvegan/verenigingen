"""#2868: a failing farewell/board mail must never block deleting a Chapter Member row."""

from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.chapter_member.chapter_member import ChapterMember

# Mock justified: the mail legs are made to raise (that is the premise under test); the
# delete, the row and the Error Log are real. The spies wrap the real method.
FAREWELL = "_send_chapter_farewell_notification"
BOARD = "_notify_board_of_member_left"
# Titles the fix writes (Error Log.method). Rows are counted by these, never by total.
FAREWELL_TITLE = "Chapter Member farewell mail failed on removal"
BOARD_TITLE = "Chapter Member board mail failed on removal"
CLEANUP_TITLE = "Member cleanup could not delete a Chapter Member"


class TestChapterMemberOnTrashFailSoft2868(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="Trash", last_name="FailSoft2868", email="trash.failsoft2868@example.com"
        )
        self.chapter = self.create_test_chapter()
        self.chapter.append(
            "members",
            {"member": self.member.name, "chapter_join_date": frappe.utils.today(), "status": "Active"},
        )
        self.chapter.save()
        self.row_name = frappe.db.get_value("Chapter Member", {"member": self.member.name}, "name")
        self.assertTrue(self.row_name)

    def _logs_titled(self, title):
        return frappe.db.count("Error Log", {"method": title})

    def _delete(self):
        frappe.delete_doc("Chapter Member", self.row_name, force=True)

    def _spy(self, name):
        original = getattr(ChapterMember, name)
        return patch.object(ChapterMember, name, autospec=True, side_effect=original)

    def test_farewell_raising_does_not_block_delete_and_board_mail_still_runs(self):
        self.expectErrorLog(FAREWELL_TITLE)
        before = self._logs_titled(FAREWELL_TITLE)
        board_before = self._logs_titled(BOARD_TITLE)
        with patch.object(ChapterMember, FAREWELL, side_effect=RuntimeError("farewell boom")):
            with self._spy(BOARD) as board_spy, self.assertErrorLog(FAREWELL_TITLE):
                self._delete()
        self.assertFalse(frappe.db.exists("Chapter Member", self.row_name))
        self.assertTrue(board_spy.called, "a farewell failure must not skip the board mail")
        self.assertEqual(self._logs_titled(FAREWELL_TITLE), before + 1)
        self.assertEqual(self._logs_titled(BOARD_TITLE), board_before, "board leg must not log a failure")
        log = frappe.get_all(
            "Error Log",
            filters={"method": FAREWELL_TITLE, "error": ["like", f"%{self.member.name}%"]},
            fields=["error"],
            limit=1,
        )[0]
        self.assertIn(self.chapter.name, log.error)
        self.assertIn("farewell boom", log.error)

    def test_unresolvable_default_company_does_not_block_delete(self):
        from verenigingen.verenigingen_payments.services.mollie_configuration_service import (
            MollieConfigurationService,
        )

        self.expectErrorLog(FAREWELL_TITLE)
        before = self._logs_titled(FAREWELL_TITLE)
        with patch.object(
            MollieConfigurationService, "get_default_company", side_effect=frappe.ValidationError("No Co")
        ), self.assertErrorLog(FAREWELL_TITLE):
            self._delete()
        self.assertFalse(frappe.db.exists("Chapter Member", self.row_name))
        self.assertEqual(self._logs_titled(FAREWELL_TITLE), before + 1)

    def test_board_mail_raising_does_not_block_delete_and_is_logged(self):
        self.expectErrorLog(BOARD_TITLE)
        before = self._logs_titled(BOARD_TITLE)
        farewell_before = self._logs_titled(FAREWELL_TITLE)
        with self._spy(FAREWELL) as farewell_spy:
            with patch.object(ChapterMember, BOARD, side_effect=RuntimeError("board boom")):
                with self.assertErrorLog(BOARD_TITLE):
                    self._delete()
        self.assertFalse(frappe.db.exists("Chapter Member", self.row_name))
        self.assertTrue(farewell_spy.called)
        self.assertEqual(self._logs_titled(BOARD_TITLE), before + 1)
        self.assertEqual(self._logs_titled(FAREWELL_TITLE), farewell_before)

    def test_deadlock_still_propagates_and_row_stays(self):
        before = self._logs_titled(FAREWELL_TITLE)
        with patch.object(ChapterMember, FAREWELL, side_effect=frappe.QueryDeadlockError()):
            with self.assertRaises(frappe.QueryDeadlockError):
                self._delete()
        self.assertTrue(frappe.db.exists("Chapter Member", self.row_name))
        self.assertEqual(self._logs_titled(FAREWELL_TITLE), before, "a deadlock must not be swallowed")

    def test_board_leg_lock_timeout_still_propagates(self):
        before = self._logs_titled(BOARD_TITLE)
        with patch.object(ChapterMember, BOARD, side_effect=frappe.QueryTimeoutError()):
            with self.assertRaises(frappe.QueryTimeoutError):
                self._delete()
        self.assertTrue(frappe.db.exists("Chapter Member", self.row_name))
        self.assertEqual(self._logs_titled(BOARD_TITLE), before, "a lock timeout must not be swallowed")

    def test_cleanup_service_leaves_error_log_row_when_row_delete_still_fails(self):
        from verenigingen.services.member.lifecycle.member_cleanup_service import get_member_cleanup_service

        self.expectErrorLog(CLEANUP_TITLE)
        before = self._logs_titled(CLEANUP_TITLE)
        with patch.object(ChapterMember, "on_trash", side_effect=RuntimeError("delete blocked")):
            with self.assertErrorLog(CLEANUP_TITLE):
                get_member_cleanup_service().handle_member_deletion(self.member)
        self.assertTrue(frappe.db.exists("Chapter Member", self.row_name))
        self.assertEqual(self._logs_titled(CLEANUP_TITLE), before + 1)
