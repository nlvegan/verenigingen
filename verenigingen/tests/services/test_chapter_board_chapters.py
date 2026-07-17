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
        #
        # The role alone is not enough to model a real staff user: the API security
        # framework authorizes on Frappe ROLE PROFILES, not roles
        # (authorization_policy.ROLE_PROFILE_SECURITY_MAPPING keyed by profile name,
        # resolved via AuthorizationEngine.get_user_role_profiles). Every enabled
        # Verenigingen Staff user on production carries role_profile_name
        # "Verenigingen Staff"; without it the @high_security_api endpoints deny with
        # "Your profiles: none" and the staff-access tests below would pass for the
        # wrong reason.
        from verenigingen.setup.role_profile_setup import assign_role_profile_to_user

        self.staff_email = f"bc-staff-{run}@example.com"
        self.staff_member = self.create_test_member(
            first_name="Staff", last_name="Chapters", email=self.staff_email, birth_date="1986-01-01"
        )
        self.staff_member.db_set("user", self._ensure_user(self.staff_email, "Staff", "Verenigingen Staff"))
        # Assert rather than `if exists`: a skipped assignment would leave the staff tests
        # silently exercising a profile-less user, which the security framework denies for a
        # reason unrelated to what they assert.
        self.assertTrue(
            frappe.db.exists("Role Profile", "Verenigingen Staff"),
            "Role Profile 'Verenigingen Staff' must exist - the staff tests below depend on it",
        )
        assign_role_profile_to_user(self.staff_email, "Verenigingen Staff")

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
        on /volunteer/skills and none on /chapter_dashboard. Asserts the full count,
        not just membership - a partial grant is also wrong.
        """
        with self.as_user(self.staff_email):
            chapters = get_user_board_chapters()

        self.assertIn(self.chapter.name, self._names(chapters))
        self.assertEqual(len(chapters), frappe.db.count("Chapter"))

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
    # Authorization scope of the staff grant (owner decision, 2026-07-17)
    # ------------------------------------------------------------------

    def test_staff_may_read_chapter_member_emails(self):
        """Staff act as read-only administrators over every chapter.

        This helper is the only chapter gate for eight whitelisted read endpoints in
        api/chapter_dashboard_api.py - the security decorators gate on tier, not
        chapter, and authorization_policy.py grants staff HIGH/MEDIUM/LOW. Including
        staff here therefore opens member-email access across all chapters. That is an
        explicit decision; this pins it so it cannot change by accident.

        Asserts the seeded member's address is actually returned. `assertIsInstance(
        ..., list)` would pass on an empty list from a chapter with no members, and so
        would not demonstrate the exposure it claims to pin.
        """
        from verenigingen.api.chapter_dashboard_api import get_chapter_member_emails
        from verenigingen.utils.performance_utils import CacheManager

        # get_chapter_member_emails is @cached(ttl=300) with a user-agnostic key, so a
        # warm entry from another test would return without consulting the gate and
        # this test would pass without exercising staff access at all.
        CacheManager._cache.clear()
        CacheManager._cache_ttl.clear()

        # The board fixture already registers this member as an active Chapter Member,
        # so the chapter has a known address to find.
        self.assertTrue(
            frappe.db.exists(
                "Chapter Member",
                {"parent": self.chapter.name, "member": self.board_member.name, "enabled": 1},
            ),
            "fixture precondition: the board member must be an active chapter member",
        )

        with self.as_user(self.staff_email):
            emails = get_chapter_member_emails(self.chapter.name)

        self.assertIsInstance(emails, list)
        self.assertIn(self.board_email, emails)

    def test_staff_may_not_approve_members(self):
        """The safety property that keeps the staff grant read-only.

        quick_approve_member takes a SECOND gate - get_user_board_role(), which has no
        staff branch and returns None - so staff are denied despite seeing every
        chapter. If someone ever adds staff to get_user_board_role's admin
        short-circuit, this fails, and that is the point.

        The denial is a RETURN value, not an exception: @handle_api_error converts the
        frappe.throw into an OperationResult/dict. Asserting assertRaises here would
        fail even though access is correctly denied.
        """
        from verenigingen.api.chapter_dashboard_api import quick_approve_member

        with self.as_user(self.staff_email):
            result = quick_approve_member(member_name=self.board_member.name, chapter_name=self.chapter.name)

        payload = result.to_dict() if hasattr(result, "to_dict") else result
        self.assertFalse(payload.get("success"))
        self.assertIn("permission", str(payload).lower())

    def test_staff_have_no_board_role(self):
        """get_user_board_role() must stay staff-free - it is what denies mutations."""
        from verenigingen.templates.pages.chapter_dashboard import get_user_board_role

        with self.as_user(self.staff_email):
            self.assertIsNone(get_user_board_role(self.chapter.name))

    # ------------------------------------------------------------------
    # Behaviour preserved for everyone else
    # ------------------------------------------------------------------

    def test_board_member_sees_only_their_chapter(self):
        """Exactly their own chapter - not a superset.

        assertIn would pass if a bug handed board members every chapter, which is
        the very failure this consolidation could introduce.
        """
        with self.as_user(self.board_email):
            chapters = get_user_board_chapters()

        self.assertEqual(self._names(chapters), {self.chapter.name})

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
        self.assertEqual(len(chapters), frappe.db.count("Chapter"))

    def test_explicit_user_argument_is_honoured(self):
        """The helper resolves the passed user, not just the session user."""
        with self.as_user(self.board_email):
            as_plain = get_user_board_chapters(user=f"nobody-{frappe.generate_hash(length=6)}@example.com")

        self.assertEqual(as_plain, [])
