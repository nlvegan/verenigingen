# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt

"""Tests for chapter_permission_service.get_user_board_chapters().

This helper decides which chapters the board-facing portal pages
(/chapter_dashboard and /volunteer/skills) let a user act on. It was previously
copy-pasted into both pages and the copies had silently diverged on their admin
role set: volunteer/skills.py included Verenigingen Staff, chapter_dashboard.py
did not, so a staff member who was not a board member saw every chapter on one
page and none on the other (docs/audits/2026-07-17-portal-pages-code-quality-audit.md,
LIVE-1).

Both pages now share this one implementation and staff is treated as an
administrator on both. Note this is deliberately broader than
ChapterPermissionService.get_permission_query_conditions(), which still limits
staff to published chapters in list views.

Real data, no business-logic mocking.
"""

import frappe

from verenigingen.services.chapter.chapter_permission_service import get_user_board_chapters
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestGetUserBoardChapters(EnhancedTestCase):
    """Role-driven behaviour of the shared board-chapter lookup."""

    def setUp(self):
        super().setUp()
        run = frappe.generate_hash(length=8)

        self.chapter = self.create_test_chapter(
            chapter_name=f"TEST Board Chapters {run}",
            region="Test Region Board",
        )

        # Board member: member -> volunteer -> active Chapter Board Member row.
        self.board_email = f"bc-board-{run}@example.com"
        self.board_member = self.create_test_member(
            first_name="Board", last_name="Chapters", email=self.board_email, birth_date="1985-01-01"
        )
        self.board_member.db_set("status", "Active")
        self.board_member.db_set("user", self._ensure_user(self.board_email, "Board"))
        self.volunteer = self.create_test_volunteer(member_name=self.board_member.name)

        self._ensure_chapter_role("Chapter Head")
        chapter_doc = frappe.get_doc("Chapter", self.chapter.name)
        chapter_doc.append(
            "board_members",
            {
                "volunteer": self.volunteer.name,
                "chapter_role": "Chapter Head",
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        chapter_doc.save(ignore_permissions=True)

        # Staff member who is deliberately NOT a board member anywhere.
        self.staff_email = f"bc-staff-{run}@example.com"
        self.staff_member = self.create_test_member(
            first_name="Staff", last_name="Chapters", email=self.staff_email, birth_date="1986-01-01"
        )
        self.staff_member.db_set("user", self._ensure_user(self.staff_email, "Staff", "Verenigingen Staff"))

    def _ensure_user(self, email, first_name, extra_role=None):
        if not frappe.db.exists("User", email):
            roles = [{"role": "Verenigingen Member"}]
            if extra_role:
                roles.append({"role": extra_role})
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": first_name,
                    "send_welcome_email": 0,
                    "roles": roles,
                }
            ).insert(ignore_permissions=True)
        return email

    def _ensure_chapter_role(self, role_name):
        if not frappe.db.exists("Chapter Role", role_name):
            frappe.get_doc({"doctype": "Chapter Role", "role_name": role_name, "is_active": 1}).insert(
                ignore_permissions=True
            )

    def _names(self, rows):
        return {r.get("chapter_name") for r in rows}

    # ------------------------------------------------------------------
    # The divergence this consolidation fixed
    # ------------------------------------------------------------------

    def test_staff_who_is_not_a_board_member_sees_all_chapters(self):
        """Verenigingen Staff short-circuits to every chapter.

        This is the behaviour that used to differ per page: staff saw all chapters
        on /volunteer/skills and none on /chapter_dashboard.
        """
        with self.as_user(self.staff_email):
            chapters = get_user_board_chapters()

        self.assertIn(self.chapter.name, self._names(chapters))

    def test_staff_result_is_not_limited_to_board_membership(self):
        """The staff grant must not fall through to the board-member walk.

        The staff user holds no Chapter Board Member row, so without the
        short-circuit this would be empty.
        """
        with self.as_user(self.staff_email):
            staff_chapters = get_user_board_chapters()
        with self.as_user(self.board_email):
            board_chapters = get_user_board_chapters()

        self.assertGreater(len(staff_chapters), len(board_chapters))

    def test_both_portal_pages_use_this_one_implementation(self):
        """Regression guard against the copy-paste re-appearing.

        The two pages previously defined their own get_user_board_chapters and
        drifted apart on the admin role set. Importing the same object is what
        keeps them from diverging again.
        """
        from verenigingen.templates.pages.chapter_dashboard import (
            get_user_board_chapters as dashboard_fn,
        )
        from verenigingen.templates.pages.volunteer.skills import (
            get_user_board_chapters as skills_fn,
        )

        self.assertIs(dashboard_fn, get_user_board_chapters)
        self.assertIs(skills_fn, get_user_board_chapters)

    # ------------------------------------------------------------------
    # Behaviour preserved for everyone else
    # ------------------------------------------------------------------

    def test_board_member_sees_only_their_chapter(self):
        with self.as_user(self.board_email):
            chapters = get_user_board_chapters()

        self.assertIn(self.chapter.name, self._names(chapters))

    def test_board_member_rows_carry_role_fields(self):
        """chapter_dashboard.html reads more than chapter_name on the board path."""
        with self.as_user(self.board_email):
            chapters = get_user_board_chapters()

        row = next(c for c in chapters if c.get("chapter_name") == self.chapter.name)
        self.assertEqual(row.get("chapter_role"), "Chapter Head")
        self.assertEqual(row.get("is_active"), 1)
        self.assertIn("region", row)

    def test_plain_member_sees_no_chapters(self):
        email = f"bc-plain-{frappe.generate_hash(length=8)}@example.com"
        member = self.create_test_member(
            first_name="Plain", last_name="Chapters", email=email, birth_date="1990-01-01"
        )
        member.db_set("user", self._ensure_user(email, "Plain"))

        with self.as_user(email):
            self.assertEqual(get_user_board_chapters(), [])

    def test_user_without_member_record_sees_no_chapters(self):
        email = f"bc-nomember-{frappe.generate_hash(length=8)}@example.com"
        self._ensure_user(email, "NoMember")

        with self.as_user(email):
            self.assertEqual(get_user_board_chapters(), [])

    def test_admin_sees_all_chapters(self):
        admin = self.ensure_test_admin_user()
        with self.as_user(admin.email):
            chapters = get_user_board_chapters()

        self.assertIn(self.chapter.name, self._names(chapters))

    def test_explicit_user_argument_is_honoured(self):
        """The helper resolves the passed user, not just the session user."""
        with self.as_user(self.board_email):
            as_plain = get_user_board_chapters(user=f"nobody-{frappe.generate_hash(length=6)}@example.com")

        self.assertEqual(as_plain, [])
