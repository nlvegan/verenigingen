#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
National-chapter access tests for the application-review and pending-applications
surfaces.

These cover two spots that previously read a *phantom* ``national_chapter`` field
off Verenigingen Settings (the real field is ``national_board_chapter``). Because
the read always returned ``None``, the national-board branch never fired and
national-board members were wrongly restricted:

- ``api.membership_application_review.get_user_chapter_access`` — must report
  ``has_national_access`` / ``restrict_to_chapters=False`` for a member with a
  Membership-level board seat in the configured national chapter.
- ``report.pending_membership_applications`` — scoped by the application permission query
  since #1765 (see TestPendingApplicationsChapterScope).

The national chapter is configured via NON-committed ``set_single_value`` so it
rolls back with the test and production reads it in the same transaction (no
committed Single -> no parallel-shard race).
"""

import time

import frappe
from frappe.utils import now_datetime, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.region_fixtures import ensure_test_region
from verenigingen.utils.constants import Roles


class NationalChapterAccessBase(EnhancedTestCase):
    """A member who is a Membership-level board member of a single chapter that
    the tests then designate as the national board chapter."""

    def setUp(self):
        super().setUp()
        self.token = f"{int(time.time() * 1000)}{frappe.generate_hash(length=4)}"
        region = self._ensure_region()

        self.national_like_chapter = self.create_chapter(
            chapter_name=f"Nat Chapter {self.token}", region=region
        )

        self.board_user = self.create_test_user(
            email=f"nat-board-{self.token}@test.com",
            roles=[Roles.VERENIGINGEN_MEMBER, Roles.CHAPTER_BOARD_MEMBER],
        )
        self.board_member = self.create_test_member(
            first_name="Nat",
            last_name="Board",
            email=f"nat-board-{self.token}@test.com",
            user=self.board_user.name,
        )
        self.board_volunteer = self.create_test_volunteer(self.board_member.name)

        # Admin-level role -> qualifies for the application-review surfaces.
        #
        # This said "Membership" until the harness stopped suppressing
        # _validate_selects(). Chapter Role.permissions_level offers only
        # Basic/Financial/Admin, so no such role can exist in production -- the value
        # only ever persisted here because frappe.flags.in_import skipped Select
        # validation, which made get_user_chapter_access's `level in ("Admin",
        # "Membership")` arm reachable in tests and nowhere else. "Admin" is the only
        # level that actually reaches the branch under test.
        self.membership_role = frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": f"Nat Membership {self.token}",
                "permissions_level": "Admin",
                "is_active": 1,
            }
        )
        self.membership_role.insert()

        frappe.get_doc(
            {
                "doctype": "Chapter Board Member",
                "parent": self.national_like_chapter.name,
                "parenttype": "Chapter",
                "parentfield": "board_members",
                "volunteer": self.board_volunteer.name,
                "chapter_role": self.membership_role.name,
                "from_date": today(),
                "is_active": 1,
            }
        ).insert()

        frappe.db.commit()

    def _ensure_region(self):
        # One owner for the shared "Test Region" docname (#406).
        return ensure_test_region()

    def _set_national_chapter(self, chapter_name):
        # NON-committed: rolls back with the test, read in-transaction by prod.
        frappe.db.set_single_value("Verenigingen Settings", "national_board_chapter", chapter_name)


class TestGetUserChapterAccess(NationalChapterAccessBase):
    """api.membership_application_review.get_user_chapter_access"""

    def test_national_board_member_gets_national_access(self):
        from verenigingen.api.membership_application_review import get_user_chapter_access

        original_user = frappe.session.user
        try:
            frappe.set_user(self.board_user.name)

            # Pre-condition: with no national chapter configured the board member
            # is restricted to their own chapter.
            self._set_national_chapter(None)
            scoped = get_user_chapter_access()
            self.assertIn(self.national_like_chapter.name, scoped["chapters"])
            self.assertFalse(scoped["has_national_access"])
            self.assertTrue(scoped["restrict_to_chapters"])

            # Designate their chapter as the national board chapter -> national
            # access unlocks (no restriction).
            self._set_national_chapter(self.national_like_chapter.name)
            result = get_user_chapter_access()
            self.assertTrue(result["has_national_access"])
            self.assertFalse(result["restrict_to_chapters"])
        finally:
            frappe.set_user(original_user)


class TestPendingApplicationsChapterScope(NationalChapterAccessBase):
    """report.pending_membership_applications scope (#1765).

    The report used to open up to see-all for a board member whose ONLY chapter was the configured
    national board chapter (get_user_chapter_filter, now removed with the Member-based query). It now
    reads applications through the MAS permission query: a seat scopes the rows to that seat's chapter
    whether or not the chapter is the national one; the "Verenigingen National Board Member" ROLE (Ruling
    O) is what sees all. This pins the new rule and the control that the national setting alone widens
    nothing. Whether a national-chapter SEAT should still see all is tracked in a follow-up issue.
    """

    def _application(self, chapter):
        application = frappe.get_doc(
            {
                "doctype": "Membership Application Submission",
                "email": f"nat-app-{frappe.generate_hash(length=8)}@example.org",
                "source": "Full Form",
                "payload": "{}",
            }
        ).insert()
        self.track_doc("Membership Application Submission", application.name)
        application.db_set("confirmed_on", now_datetime())
        if chapter:
            application.db_set("chapter", chapter)
        application.set_status("Pending Review")
        return application.name

    def test_national_chapter_seat_is_scoped_to_its_chapter(self):
        from verenigingen.verenigingen.report.pending_membership_applications.pending_membership_applications import (
            execute,
        )

        other = self.create_chapter(
            chapter_name=f"Nat Other {self.token}", region=self._ensure_region()
        )
        own_application = self._application(self.national_like_chapter.name)
        other_application = self._application(other.name)
        unassigned = self._application(None)

        original_user = frappe.session.user
        try:
            frappe.set_user(self.board_user.name)
            for national in (None, self.national_like_chapter.name):
                self._set_national_chapter(national)
                names = {row["name"] for row in execute({})[1]}
                self.assertIn(own_application, names)
                self.assertFalse({other_application, unassigned} & names, (national, names))
        finally:
            frappe.set_user(original_user)
