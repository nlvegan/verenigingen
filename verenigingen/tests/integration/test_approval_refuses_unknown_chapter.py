# -*- coding: utf-8 -*-
"""#1860 (maintainer ruling 2026-10-31): an approval that names a chapter that does not exist is
REFUSED before anything is written. It used to approve the member with no chapter row.

Real flow: Guest submit_application, then approve_membership_application as Administrator.
"""

import json

import frappe

from verenigingen.api.membership_application_review import approve_membership_application
from verenigingen.tests.backend.unit.api.test_membership_application_coverage import (
    _ensure_test_membership_type,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.utils.guest_application import submit_application_as_guest


class _ApprovalFixtures(EnhancedTestCase):
    """Shared setup; holds no tests of its own, so subclasses do not re-run each other's."""

    def setUp(self):
        super().setUp()
        from verenigingen.tests.setup import ensure_member_test_masters

        ensure_member_test_masters()
        self.membership_type = _ensure_test_membership_type()

    def _submit_application_as_guest(self, selected_chapter=None):
        return submit_application_as_guest(self, self.membership_type, selected_chapter=selected_chapter)


class TestApprovalRefusesUnknownChapter(_ApprovalFixtures):
    def test_an_unknown_chapter_is_refused_before_anything_is_written(self):
        ghost = f"No Such Chapter {frappe.generate_hash(length=6)}"
        member = self._submit_application_as_guest()

        with self.assertRaisesRegex(frappe.ValidationError, "cannot be assigned"):
            approve_membership_application(
                member_name=member, membership_type=self.membership_type, chapter=ghost
            )

        self.assertEqual(
            frappe.db.get_value("Member", member, ["status", "application_status"]), ("Pending", "Pending")
        )
        self.assertFalse(frappe.db.exists("Membership", {"member": member}))
        self.assertFalse(frappe.db.exists("Chapter Member", {"member": member}))

    def test_an_existing_chapter_still_approves(self):
        """Control: the refusal must not catch a real chapter."""
        chapter = self.create_test_chapter(published=1)
        member = self._submit_application_as_guest()

        approve_membership_application(
            member_name=member, membership_type=self.membership_type, chapter=chapter.name
        )

        self.assertEqual(frappe.db.get_value("Member", member, "status"), "Active")

    def test_an_unpublished_existing_chapter_is_not_refused(self):
        """Control for the ruling's boundary: only a chapter that does not EXIST is refused."""
        chapter = self.create_test_chapter(published=0)
        member = self._submit_application_as_guest()

        approve_membership_application(
            member_name=member, membership_type=self.membership_type, chapter=chapter.name
        )

        self.assertEqual(frappe.db.get_value("Member", member, "status"), "Active")

    def test_no_chapter_still_approves(self):
        """Control: an approval naming no chapter is not refused."""
        member = self._submit_application_as_guest()

        approve_membership_application(member_name=member, membership_type=self.membership_type, chapter=None)

        self.assertEqual(frappe.db.get_value("Member", member, "status"), "Active")


class TestScopedApproverMayOnlyAssignManagedChapters(_ApprovalFixtures):
    """#1908 (maintainer ruling 2026-10-31): a chapter-scoped approver may NOT assign a chapter it
    does not manage, and is refused IDENTICALLY to a nonexistent chapter, so the refusal does not
    reveal which (unpublished) chapter names exist."""

    def setUp(self):
        super().setUp()
        self.own = self.create_test_chapter(published=1)
        self.foreign = self.create_test_chapter(published=0)
        self.board = self.create_test_board_member(self.own.name)

    def _refusal_as_board(self, member, chapter):
        before = len(frappe.local.message_log)
        with self.set_user(self.board.user):
            with self.assertRaises(frappe.ValidationError) as ctx:
                approve_membership_application(
                    member_name=member, membership_type=self.membership_type, chapter=chapter
                )
        log = []
        for entry in frappe.local.message_log[before:]:
            entry = json.loads(entry) if isinstance(entry, str) else dict(entry)
            entry.pop("__frappe_exc_id", None)  # a random per-call id, not a channel difference
            log.append({k: str(v).replace(chapter, "<C>") for k, v in entry.items()})
        del frappe.local.message_log[before:]
        return type(ctx.exception), str(ctx.exception).replace(chapter, "<C>"), log

    def test_a_foreign_chapter_is_refused_exactly_like_an_unknown_one(self):
        member = self._submit_application_as_guest(selected_chapter=self.own.name)

        foreign = self._refusal_as_board(member, self.foreign.name)
        unknown = self._refusal_as_board(member, f"No Such Chapter {frappe.generate_hash(length=6)}")

        self.assertIn("cannot be assigned", foreign[1])
        self.assertEqual(foreign, unknown)
        self.assertEqual(frappe.db.get_value("Member", member, "status"), "Pending")
        self.assertFalse(
            frappe.db.exists("Chapter Member", {"member": member, "parent": self.foreign.name})
        )

    def test_the_approvers_own_chapter_is_still_assignable(self):
        """Control: the scoped approver can approve into the chapter they manage."""
        member = self._submit_application_as_guest(selected_chapter=self.own.name)

        with self.set_user(self.board.user):
            approve_membership_application(
                member_name=member, membership_type=self.membership_type, chapter=self.own.name
            )

        self.assertEqual(frappe.db.get_value("Member", member, "status"), "Active")

    def test_the_review_page_defaults_to_a_chapter_the_approver_manages(self):
        """#1908 review F1: an applicant with rows in two chapters must not be offered the OTHER
        chapter as the review page's default (the approver would then be refused on the default).

        Probe shortcut: the second row is written with create_pending_chapter_membership and its
        join date is set directly, to make the foreign row the most recent one."""
        from verenigingen.api.membership_application_review import get_pending_applications
        from verenigingen.utils.application_helpers import create_pending_chapter_membership

        member = self._submit_application_as_guest(selected_chapter=self.own.name)
        create_pending_chapter_membership(frappe.get_doc("Member", member), self.foreign.name)
        frappe.db.set_value(
            "Chapter Member",
            {"member": member, "parent": self.own.name},
            "chapter_join_date",
            frappe.utils.add_days(frappe.utils.today(), -30),
        )

        with self.set_user(self.board.user):
            apps = get_pending_applications()
        apps = apps.get("data", apps) if isinstance(apps, dict) else apps
        row = next(a for a in apps if a["name"] == member)

        self.assertEqual(row["current_chapter_display"], self.own.name)
