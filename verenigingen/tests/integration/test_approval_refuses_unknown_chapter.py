# -*- coding: utf-8 -*-
"""#1860 / #1908 (maintainer rulings 2026-10-31), on the application-keyed flow (#1765).

#1860: an approval that names a chapter that does not exist is REFUSED before anything is written. It
used to approve the member with no chapter row.
#1908: a chapter-scoped approver may NOT assign a chapter it does not manage, and is refused IDENTICALLY
to a nonexistent chapter, so the refusal does not reveal which (unpublished) chapter names exist.
Ruling AR (#1765): approve_application uses the one shared helper, so a scoped approver MAY assign any
chapter it manages, including one other than the application's own.

Real flow: submit_application as Guest -> confirm link -> approve_application (ApprovalCase's staging).
Probe shortcut, stated: the second board seat in test_a_scoped_approver_may_assign_another_chapter_it_manages
is a Chapter Board Member row appended to the chapter, exactly as create_test_board_member builds the
first one.
"""

import frappe

from verenigingen.tests.integration.test_application_record_approval import (
    SUBMISSION,
    ApprovalCase,
    _message_log_without_exc_id,
)


class _ChapterRefusalCase(ApprovalCase):
    """Shared helpers; holds no tests of its own, so subclasses do not re-run each other's."""

    def _approve_into(self, application, chapter, user=None):
        return self._approve_as(
            application, user=user, membership_type=self.membership_type.name, chapter=chapter
        )

    def _assert_nothing_written(self, application):
        self.assertEqual(frappe.db.get_value(SUBMISSION, application, "status"), "Pending Review")
        self.assertEqual(frappe.db.count("Member", {"email": self.email}), 0)


class TestApprovalRefusesUnknownChapter(_ChapterRefusalCase):
    def test_an_unknown_chapter_is_refused_before_anything_is_written(self):
        ghost = f"No Such Chapter {frappe.generate_hash(length=6)}"
        application = self._stage_and_confirm()
        rows_before = frappe.db.count("Chapter Member")

        with self.assertRaisesRegex(frappe.ValidationError, "cannot be assigned"):
            self._approve_into(application, ghost)

        self._assert_nothing_written(application)
        self.assertEqual(frappe.db.count("Chapter Member"), rows_before)

    def test_an_existing_chapter_still_approves(self):
        """Control: the refusal must not catch a real chapter."""
        chapter = self.create_test_chapter(published=1)
        application = self._stage_and_confirm()

        result = self._approve_into(application, chapter.name)

        self.assertTrue(result["success"], result)
        self.assertEqual(frappe.db.get_value("Member", result["member"], "status"), "Active")
        self.assertTrue(
            frappe.db.exists("Chapter Member", {"parent": chapter.name, "member": result["member"]})
        )

    def test_an_unpublished_existing_chapter_is_not_refused(self):
        """Control for the ruling's boundary: only a chapter that does not EXIST is refused (an
        administrator may assign an unpublished one)."""
        chapter = self.create_test_chapter(published=0)
        application = self._stage_and_confirm()

        result = self._approve_into(application, chapter.name)

        self.assertEqual(frappe.db.get_value("Member", result["member"], "status"), "Active")

    def test_no_chapter_still_approves(self):
        """Control: an approval naming no chapter is not refused."""
        application = self._stage_without_chapter()

        result = self._approve_into(application, None)

        self.assertEqual(frappe.db.get_value("Member", result["member"], "status"), "Active")

    def test_the_review_dialogs_default_chapter_still_approves(self):
        """The review dialog pre-fills the application's own chapter and posts it back as `chapter`."""
        application = self._stage_and_confirm()
        default = frappe.db.get_value(SUBMISSION, application, "chapter")
        self.assertEqual(default, self.chapter.name)

        result = self._approve_into(application, default)

        self.assertEqual(frappe.db.get_value("Member", result["member"], "status"), "Active")


class TestScopedApproverMayOnlyAssignManagedChapters(_ChapterRefusalCase):
    def setUp(self):
        super().setUp()
        self.own = self.chapter  # the application's chapter, and the one the board member holds a seat in
        self.foreign = self.create_test_chapter(published=0)
        self.board = self.create_test_board_member(self.own.name)

    def _refusal_as_board(self, application, chapter):
        """(type, message, message_log delta, Error Log delta) of the refusal, with the chapter name masked."""
        errors = frappe.db.count("Error Log")
        frappe.clear_messages()
        before = len(frappe.local.message_log)
        with self.assertRaises(frappe.ValidationError) as ctx:
            self._approve_into(application, chapter, user=self.board.user)
        log = [
            {k: str(v).replace(chapter, "<C>") for k, v in entry.items()}
            for entry in _message_log_without_exc_id(list(frappe.local.message_log)[before:])
        ]
        del frappe.local.message_log[before:]
        return (
            type(ctx.exception),
            str(ctx.exception).replace(chapter, "<C>"),
            log,
            frappe.db.count("Error Log") - errors,
        )

    def test_a_foreign_chapter_is_refused_exactly_like_an_unknown_one(self):
        application = self._stage_and_confirm()
        foreign_rows = frappe.db.count("Chapter Member", {"parent": self.foreign.name})
        # Warm the permission caches: the first call of a process reads cold.
        self._refusal_as_board(application, f"No Such Chapter {frappe.generate_hash(length=6)}")

        foreign = self._refusal_as_board(application, self.foreign.name)
        unknown = self._refusal_as_board(application, f"No Such Chapter {frappe.generate_hash(length=6)}")

        self.assertIn("cannot be assigned", foreign[1])
        self.assertEqual(foreign, unknown)
        self._assert_nothing_written(application)
        self.assertEqual(frappe.db.count("Chapter Member", {"parent": self.foreign.name}), foreign_rows)

    def test_the_approvers_own_chapter_is_still_assignable(self):
        """Control: the scoped approver can approve into the chapter they manage."""
        application = self._stage_and_confirm()

        result = self._approve_into(application, self.own.name, user=self.board.user)

        self.assertEqual(frappe.db.get_value("Member", result["member"], "status"), "Active")

    def test_a_scoped_approver_may_assign_another_chapter_it_manages(self):
        """Ruling AR: a scoped approver holding Admin seats on A and B approves an application of A
        into B. The branch's earlier guard ("only an admin may place the member in another chapter")
        refused this with a PermissionError."""
        other = self.create_test_chapter(published=1)
        other_doc = frappe.get_doc("Chapter", other.name)
        other_doc.append(
            "board_members",
            {
                "volunteer": self.board.volunteer,
                "chapter_role": self.board.chapter_role,
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        other_doc.save()  # as Administrator
        application = self._stage_and_confirm()

        result = self._approve_into(application, other.name, user=self.board.user)

        self.assertEqual(frappe.db.get_value("Member", result["member"], "status"), "Active")
        self.assertTrue(frappe.db.exists("Chapter Member", {"parent": other.name, "member": result["member"]}))
