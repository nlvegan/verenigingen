"""
#2931: the history cleanup helpers decide WHAT to delete from the data, never from error text.

Frappe translates a LinkValidationError per user language ("Kon Rij #2: ... niet vinden")
and lists the parent's dead links before the child rows'. A matcher on English substrings
therefore never fires under nl, or fires/skips depending on message order. Both helpers
below must act on the exception TYPE plus what the database says is dead.

The seam is the same as test_history_manager_utils: only the framework method
``Document.update_child_table`` is patched, to raise what a full save raises on a dead link.
"""

from unittest.mock import patch

import frappe
from frappe.model.document import Document

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.history_manager_utils import safe_child_table_update
from verenigingen.utils.member_financial_history_manager import MemberFinancialHistoryManager

CHILD_TABLE = "chapter_membership_history"
GHOST_CHAPTER = "GHOST-CHAPTER-DOES-NOT-EXIST-2931"

# What Frappe raises under language "nl" (no English substring of the old matchers present).
DUTCH_LINK_ERROR = "Kon Rij #2: Hoofdstuk Lidmaatschap Geschiedenis: {ghost} niet vinden"
# English, but the PARENT's dead link is listed first, so "Could not find Row" is not a substring
# and "Chapter:" is absent.
PARENT_FIRST_ERROR = "Could not find Customer Group: GONE-GROUP, Row #2: Chapter Membership History: {ghost}"


class _HistoryCleanupBase(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="Hist", last_name="Data2931")
        self.chapter = self.create_test_chapter()

    def _doc_with_good_and_ghost_row(self):
        doc = frappe.get_doc("Member", self.member.name)
        for chapter_name in (self.chapter.name, GHOST_CHAPTER):
            doc.append(
                CHILD_TABLE,
                {
                    "chapter_name": chapter_name,
                    "assignment_type": "Member",
                    "start_date": frappe.utils.today(),
                    "status": "Active",
                },
            )
        return doc

    def _chapters_in(self, doc):
        return [row.chapter_name for row in doc.get(CHILD_TABLE)]

    def _fail_first_call(self, exc):
        """update_child_table raising ``exc`` on its first call and working afterwards."""
        real_update = Document.update_child_table
        state = {"calls": 0}

        def flaky(doc, fieldname, df=None):
            state["calls"] += 1
            if state["calls"] == 1:
                raise exc
            return real_update(doc, fieldname, df)

        return flaky, state


class TestSafeChildTableUpdateDecidesFromData(_HistoryCleanupBase):
    def _run(self, exc):
        doc = self._doc_with_good_and_ghost_row()
        flaky, state = self._fail_first_call(exc)
        with patch.object(Document, "update_child_table", flaky):
            result = safe_child_table_update(
                doc, CHILD_TABLE, "2931", "Member:write", auto_cleanup=True
            )
        return doc, result, state

    def test_translated_link_error_still_cleans_the_dead_row(self):
        doc, result, state = self._run(
            frappe.LinkValidationError(DUTCH_LINK_ERROR.format(ghost=GHOST_CHAPTER))
        )
        self.assertTrue(result.success, msg=result.errors)
        self.assertEqual(self._chapters_in(doc), [self.chapter.name])
        self.assertEqual(state["calls"], 2)

    def test_parent_dead_link_listed_first_still_cleans_the_dead_row(self):
        doc, result, _ = self._run(
            frappe.LinkValidationError(PARENT_FIRST_ERROR.format(ghost=GHOST_CHAPTER))
        )
        self.assertTrue(result.success, msg=result.errors)
        self.assertEqual(self._chapters_in(doc), [self.chapter.name])

    def test_english_text_naming_the_child_table_does_not_delete_when_no_row_is_dead(self):
        """Control: the old matcher fired on this text. Our rows are all alive, so nothing may go."""
        doc = frappe.get_doc("Member", self.member.name)
        doc.append(
            CHILD_TABLE,
            {
                "chapter_name": self.chapter.name,
                "assignment_type": "Member",
                "start_date": frappe.utils.today(),
                "status": "Active",
            },
        )
        flaky, _ = self._fail_first_call(
            frappe.LinkValidationError("Could not find Row #1: Chapter Membership History: Chapter: X")
        )
        with patch.object(Document, "update_child_table", flaky):
            result = safe_child_table_update(doc, CHILD_TABLE, "2931", "Member:write", auto_cleanup=True)
        self.assertEqual(self._chapters_in(doc), [self.chapter.name])
        self.assertFalse(result.success)

    def test_plain_validation_error_removes_dead_row_and_keeps_original_error(self):
        """A plain ValidationError (non-link text) with a dead row: the dead row goes, and when
        the cause persists the ORIGINAL error is still reported."""
        original = "Status moet ingesteld zijn"

        def always_raise(doc, fieldname, df=None):
            raise frappe.ValidationError(original)

        doc = self._doc_with_good_and_ghost_row()
        with patch.object(Document, "update_child_table", always_raise):
            result = safe_child_table_update(doc, CHILD_TABLE, "2931", "Member:write", auto_cleanup=True)
        self.assertFalse(result.success)
        self.assertEqual(result.message, "Update failed even after cleanup")
        self.assertEqual(result.errors[0], f"Original: {original}")
        self.assertEqual(self._chapters_in(doc), [self.chapter.name])

    def test_non_link_exception_never_triggers_cleanup(self):
        """Control for an 'always clean up' fix: a dead row exists, the failure is not a link error."""
        doc, result, _ = self._run(frappe.DocumentLockedError("locked"))
        self.assertFalse(result.success)
        self.assertEqual(self._chapters_in(doc), [self.chapter.name, GHOST_CHAPTER])


class TestFinancialHistoryRetryDecidesFromData(_HistoryCleanupBase):
    def _run(self, exc):
        doc = self._doc_with_good_and_ghost_row()
        flaky, state = self._fail_first_call(exc)
        manager = MemberFinancialHistoryManager(doc, "payment_history")
        with patch.object(Document, "update_child_table", flaky), patch("time.sleep"):
            saved = manager._save_with_retry()
        return doc, saved, state

    def test_translated_link_error_cleans_the_dead_chapter_reference(self):
        doc, saved, _ = self._run(frappe.LinkValidationError(DUTCH_LINK_ERROR.format(ghost=GHOST_CHAPTER)))
        self.assertTrue(saved)
        self.assertEqual(self._chapters_in(doc), [self.chapter.name])

    def test_parent_dead_link_listed_first_cleans_the_dead_chapter_reference(self):
        doc, saved, _ = self._run(frappe.LinkValidationError(PARENT_FIRST_ERROR.format(ghost=GHOST_CHAPTER)))
        self.assertTrue(saved)
        self.assertEqual(self._chapters_in(doc), [self.chapter.name])

    def test_non_link_failure_never_touches_the_chapter_rows(self):
        """Control: a dead row is present but the failure is not a link error, so it stays."""
        doc, saved, _ = self._run(RuntimeError("Could not find Row #2: Chapter: " + GHOST_CHAPTER))
        self.assertTrue(saved)  # plain retry succeeds
        self.assertEqual(self._chapters_in(doc), [self.chapter.name, GHOST_CHAPTER])

    def test_dead_link_in_another_table_does_not_take_the_chapter_cleanup_path(self):
        """Control for the data check: a LinkValidationError whose cause is NOT a chapter row
        (every chapter row is alive) must go through the ordinary retry path, with no
        chapter-validation Error Log entry."""
        doc = frappe.get_doc("Member", self.member.name)
        doc.append(
            CHILD_TABLE,
            {
                "chapter_name": self.chapter.name,
                "assignment_type": "Member",
                "start_date": frappe.utils.today(),
                "status": "Active",
            },
        )

        def always_raise(d, fieldname, df=None):
            raise frappe.LinkValidationError("Kon Rij #1: Klantgroep: GONE niet vinden")

        manager = MemberFinancialHistoryManager(doc, "payment_history")
        real_log_error = frappe.log_error
        logged = []

        def spy(*args, **kwargs):
            logged.append(" ".join(str(a) for a in (*args, *kwargs.values())))
            return real_log_error(*args, **kwargs)

        with (
            patch.object(Document, "update_child_table", always_raise),
            patch("time.sleep"),
            patch.object(frappe, "log_error", spy),
        ):
            saved = manager._save_with_retry()
        self.assertFalse(saved)
        self.assertFalse([m for m in logged if "Chapter Validation Error" in m], logged)
        self.assertTrue([m for m in logged if "Financial History Save Error" in m], logged)
        self.assertEqual(self._chapters_in(doc), [self.chapter.name])
