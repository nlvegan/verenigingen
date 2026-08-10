# -*- coding: utf-8 -*-
# Copyright (c) 2026, Your Organization and Contributors
# See license.txt

"""
Coverage-focused integration tests for verenigingen/api/chapter_dashboard_api.py

Covers the production chapter-dashboard endpoints:
  - get_chapter_member_emails (board-access gate + DISTINCT active-email query)
  - quick_approve_member (board-permission gate + Chapter-Member-join approval
    path + membership-application path + error/no-permission paths)
  - the number-card REPORTING endpoints: get_active_members_count,
    get_pending_applications_count, get_board_members_count,
    get_new_members_count, get_filed_expense_claims_count,
    get_approved_expense_claims_count, get_volunteer_expenses_count
    (both the explicit-chapter branch and the "no chapter -> sum the user's
    board chapters" branch, plus the no-board-chapters zero branch).
  - reprocess_mt940_import error path (no live banking).

These are REAL integration tests: real Member/Chapter/Volunteer/Chapter Board
Member docs are created, the whitelisted APIs are invoked, and the returned
shapes + DB state are asserted. Permission gates are exercised by switching the
session user via the PortalSelfServiceTestMixin helpers (admin runs as default
Administrator; board/plain paths run as linked Users).
"""

import frappe

from verenigingen.api import chapter_dashboard_api
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.portal_self_service_mixin import PortalSelfServiceTestMixin


class _ChapterDashboardBase(PortalSelfServiceTestMixin, EnhancedTestCase):
    """Shared board-member fixture builder for the dashboard API tests."""

    def setUp(self):
        super().setUp()
        self._original_form_dict = frappe.form_dict
        self.chapter = self.factory.create_chapter(
            chapter_name=f"CDChapter-{self.uid}",
            region="Test Region CD",
        )

    def tearDown(self):
        frappe.form_dict = self._original_form_dict
        super().tearDown()

    def _make_member(self, **kwargs):
        kwargs.setdefault(
            "email", f"cd-{self.uid}-{frappe.generate_hash(length=6)}@example.com"
        )
        return self.factory.create_member(
            first_name="CDTest",
            last_name="Member",
            **kwargs,
        )

    def _add_chapter_member(self, member_name, status="Active", enabled=1):
        """Append a Chapter Member child row to self.chapter."""
        chapter_doc = frappe.get_doc("Chapter", self.chapter.name)
        chapter_doc.append(
            "members",
            {
                "member": member_name,
                "status": status,
                "enabled": enabled,
                "chapter_join_date": frappe.utils.today(),
            },
        )
        chapter_doc.save()

    # Default was "Membership", which Chapter Role.permissions_level does not offer
    # (Basic/Financial/Admin only); it persisted solely because the harness suppressed
    # _validate_selects(). "Admin" keeps the same effective access, since the code that
    # reads this field treats "Membership" as a synonym for "Admin" via a legacy string
    # no real role can carry. Approval in this file is driven by chapter_role NAME
    # rather than by level, so this default is incidental to most cases here.
    def _make_board_user(self, role_permissions_level="Admin", chapter_role_name=None):
        """Create a member->volunteer->active board seat on self.chapter, link a
        User whose email matches Member.email (so get_user_board_chapters resolves
        it), and return (member, user, volunteer)."""
        member = self._make_member()
        volunteer = self.factory.create_volunteer(member_name=member.name)
        role_name = chapter_role_name or f"CD Board Role {self.uid}"
        role = self.factory.ensure_chapter_role(
            role_name, attributes={"permissions_level": role_permissions_level}
        )
        chapter_doc = frappe.get_doc("Chapter", self.chapter.name)
        chapter_doc.append(
            "board_members",
            {
                "volunteer": volunteer.name,
                "chapter_role": role.name,
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        chapter_doc.save()
        # Real chapter board members carry the 'Verenigingen Chapter Board Member'
        # role profile, which grants the HIGH security tier the member-data
        # endpoints require. Without it the @high_security_api gate would reject
        # the board user before its body-level board check runs.
        user = self._link_member_to_user(
            member,
            roles=("Verenigingen Member", "Verenigingen Chapter Board Member"),
            role_profile="Verenigingen Chapter Board Member",
        )
        return member, user, volunteer

    def _make_privileged_non_board_user(self):
        """A User carrying the 'Verenigingen Auditor' role profile, which grants
        the MEDIUM security tier (so the @standard_api REPORTING decorator lets
        the call through) but is NOT a system/association admin and holds no board
        seat -> get_user_board_chapters() returns [] for it. This is the only
        realistic actor that reaches the "no board chapters -> 0" body branches of
        the number-card endpoints (a plain member is rejected at the decorator;
        an admin sees every chapter)."""
        user = self.factory.create_user_with_roles(
            email=f"cd-auditor-{self.uid}-{frappe.generate_hash(length=6)}@example.com",
            roles=["Verenigingen Auditor"],
        )
        user.reload()
        user.set("role_profiles", [{"role_profile": "Verenigingen Auditor"}])
        user.save()
        return user


class TestChapterDashboardMemberEmails(_ChapterDashboardBase):
    """get_chapter_member_emails."""

    def test_admin_gets_active_member_emails(self):
        # As Administrator (admin sees all chapters via get_user_board_chapters).
        m1 = self._make_member(email=f"alice-{self.uid}@example.com")
        m2 = self._make_member(email=f"bob-{self.uid}@example.com")
        self._add_chapter_member(m1.name, status="Active")
        self._add_chapter_member(m2.name, status="Active")

        emails = chapter_dashboard_api.get_chapter_member_emails(self.chapter.name)

        self.assertIn(m1.email, emails)
        self.assertIn(m2.email, emails)

    def test_excludes_inactive_members(self):
        active = self._make_member(email=f"act-{self.uid}@example.com")
        inactive = self._make_member(email=f"inact-{self.uid}@example.com")
        self._add_chapter_member(active.name, status="Active", enabled=1)
        self._add_chapter_member(inactive.name, status="Inactive", enabled=0)

        emails = chapter_dashboard_api.get_chapter_member_emails(self.chapter.name)

        self.assertIn(active.email, emails)
        self.assertNotIn(inactive.email, emails)

    def test_board_member_can_access_own_chapter(self):
        board_member, board_user, _vol = self._make_board_user()
        target = self._make_member(email=f"tgt-{self.uid}@example.com")
        self._add_chapter_member(target.name, status="Active")

        with self._as_user(board_user.name):
            emails = chapter_dashboard_api.get_chapter_member_emails(self.chapter.name)

        self.assertIn(target.email, emails)

    def test_plain_member_denied_at_security_tier(self):
        """A plain 'Verenigingen Member' (LOW tier) is rejected by the
        @high_security_api decorator BEFORE the body runs -> PermissionError
        propagates (the decorator gate is outside @handle_api_error)."""
        from verenigingen.utils.error_handling import PermissionError as VPermissionError

        plain = self._make_member()
        user = self._link_member_to_user(plain, roles=("Verenigingen Member",))
        with self._as_user(user.name):
            self.expectErrorLog()
            with self.assertRaises(VPermissionError):
                chapter_dashboard_api.get_chapter_member_emails(self.chapter.name)

    def test_privileged_non_board_user_denied_in_body(self):
        """An Auditor-profile user passes the HIGH... no — Auditor is MEDIUM only,
        so it is still rejected by the HIGH-tier @high_security_api gate. This
        documents that get_chapter_member_emails requires HIGH (member-data) tier."""
        from verenigingen.utils.error_handling import PermissionError as VPermissionError

        user = self._make_privileged_non_board_user()
        with self._as_user(user.name):
            self.expectErrorLog()
            with self.assertRaises(VPermissionError):
                chapter_dashboard_api.get_chapter_member_emails(self.chapter.name)


class TestChapterDashboardQuickApprove(_ChapterDashboardBase):
    """quick_approve_member."""

    def test_approve_pending_chapter_member(self):
        """Board head approves a pending Chapter Member join request."""
        board_member, board_user, _vol = self._make_board_user(
            chapter_role_name=f"CD Head {self.uid}"
        )
        # The "Chapter Head" role name drives get_role_permissions (can_approve).
        # get_user_board_role maps by chapter_role NAME, so use a known-approving
        # role name. Re-seat the board member under "Chapter Head".
        applicant = self._make_member()
        self._add_chapter_member(applicant.name, status="Pending")

        # Give the board user an approving role: re-seat under "Chapter Head".
        self._reseat_board_as_chapter_head(_vol.name)

        with self._as_user(board_user.name):
            # The post-approval audit Comment is inserted via secure_document_operation,
            # which requires elevated-operation permission the board user lacks; the
            # endpoint deliberately logs that and continues (approval is NOT blocked).
            self.expectErrorLog()
            result = chapter_dashboard_api.quick_approve_member(
                applicant.name, self.chapter.name
            )

        self.assertTrue(result.get("success"), msg=result)
        # The Chapter Member row should now be Active.
        status = frappe.db.get_value(
            "Chapter Member", {"member": applicant.name, "parent": self.chapter.name}, "status"
        )
        self.assertEqual(status, "Active")

    def test_approve_requires_board_membership(self):
        """A plain member is rejected by the @high_security_api tier gate before
        the body's board-membership check is reached."""
        from verenigingen.utils.error_handling import PermissionError as VPermissionError

        plain = self._make_member()
        user = self._link_member_to_user(plain, roles=("Verenigingen Member",))
        applicant = self._make_member()
        self._add_chapter_member(applicant.name, status="Pending")
        with self._as_user(user.name):
            self.expectErrorLog()
            with self.assertRaises(VPermissionError):
                chapter_dashboard_api.quick_approve_member(applicant.name, self.chapter.name)

    def test_approve_board_member_without_permission_role(self):
        """A board member whose chapter role does NOT grant can_approve_members
        is blocked at the permission check (frappe.throw -> serialized failure)."""
        # Use a role NAME that is not in get_role_permissions' approving set, so
        # default_permissions (can_approve_members=False) applies.
        board_member, board_user, _vol = self._make_board_user(
            chapter_role_name=f"CD NonApprover {self.uid}"
        )
        applicant = self._make_member()
        self._add_chapter_member(applicant.name, status="Pending")
        with self._as_user(board_user.name):
            self.expectErrorLog()
            result = chapter_dashboard_api.quick_approve_member(
                applicant.name, self.chapter.name
            )
        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("success"))

    def _reseat_board_as_chapter_head(self, volunteer_name):
        """Ensure 'Chapter Head' role exists and seat volunteer under it so
        get_user_board_role returns approving permissions."""
        self.factory.ensure_chapter_role(
            "Chapter Head", attributes={"permissions_level": "Admin"}
        )
        chapter_doc = frappe.get_doc("Chapter", self.chapter.name)
        for bm in chapter_doc.board_members:
            if bm.volunteer == volunteer_name:
                bm.chapter_role = "Chapter Head"
        chapter_doc.save()


class TestChapterDashboardNumberCards(_ChapterDashboardBase):
    """Number-card REPORTING endpoints (read-only, @standard_api)."""

    def test_active_members_count_explicit_chapter(self):
        m1 = self._make_member()
        m2 = self._make_member()
        self._add_chapter_member(m1.name, status="Active")
        self._add_chapter_member(m2.name, status="Active")

        res = chapter_dashboard_api.get_active_members_count(self.chapter.name)

        self.assertEqual(res["fieldtype"], "Data")
        self.assertEqual(res["value"], 2)

    def test_active_members_count_no_chapter_sums_board_chapters(self):
        """No chapter arg -> sum over the current user's board chapters."""
        board_member, board_user, _vol = self._make_board_user()
        m1 = self._make_member()
        self._add_chapter_member(m1.name, status="Active")
        with self._as_user(board_user.name):
            res = chapter_dashboard_api.get_active_members_count()
        # Board member's own active Chapter Member row + the added one.
        self.assertGreaterEqual(res["value"], 1)
        self.assertEqual(res["fieldtype"], "Data")

    def test_active_members_count_no_board_returns_zero(self):
        user = self._make_privileged_non_board_user()
        with self._as_user(user.name):
            res = chapter_dashboard_api.get_active_members_count()
        self.assertEqual(res["value"], 0)

    def test_pending_applications_count_explicit_chapter(self):
        m1 = self._make_member()
        m2 = self._make_member()
        self._add_chapter_member(m1.name, status="Pending")
        self._add_chapter_member(m2.name, status="Active")

        res = chapter_dashboard_api.get_pending_applications_count(self.chapter.name)
        self.assertEqual(res["value"], 1)

    def test_pending_applications_count_no_board_returns_zero(self):
        user = self._make_privileged_non_board_user()
        with self._as_user(user.name):
            res = chapter_dashboard_api.get_pending_applications_count()
        self.assertEqual(res["value"], 0)

    def test_board_members_count_explicit_chapter(self):
        # _make_board_user adds one active board member to self.chapter.
        self._make_board_user()
        res = chapter_dashboard_api.get_board_members_count(self.chapter.name)
        self.assertGreaterEqual(res["value"], 1)

    def test_board_members_count_no_board_returns_zero(self):
        user = self._make_privileged_non_board_user()
        with self._as_user(user.name):
            res = chapter_dashboard_api.get_board_members_count()
        self.assertEqual(res["value"], 0)

    def test_new_members_count_counts_recent_joins(self):
        m1 = self._make_member()
        self._add_chapter_member(m1.name, status="Active")  # join date = today
        res = chapter_dashboard_api.get_new_members_count(self.chapter.name)
        self.assertGreaterEqual(res["value"], 1)

    def test_new_members_count_no_board_returns_zero(self):
        user = self._make_privileged_non_board_user()
        with self._as_user(user.name):
            res = chapter_dashboard_api.get_new_members_count()
        self.assertEqual(res["value"], 0)

    def test_filed_expense_claims_count_explicit_and_default(self):
        # Both branches return a count of non-draft Expense Claims (global on this
        # site). We assert shape + non-negativity (no expense fixtures needed).
        res_chapter = chapter_dashboard_api.get_filed_expense_claims_count(self.chapter.name)
        self.assertEqual(res_chapter["fieldtype"], "Data")
        self.assertGreaterEqual(res_chapter["value"], 0)

        # Default branch needs board chapters; run as admin (has board chapters).
        res_default = chapter_dashboard_api.get_filed_expense_claims_count()
        self.assertGreaterEqual(res_default["value"], 0)

    def test_filed_expense_claims_count_no_board_returns_zero(self):
        user = self._make_privileged_non_board_user()
        with self._as_user(user.name):
            res = chapter_dashboard_api.get_filed_expense_claims_count()
        self.assertEqual(res["value"], 0)

    def test_approved_expense_claims_count(self):
        res = chapter_dashboard_api.get_approved_expense_claims_count(self.chapter.name)
        self.assertEqual(res["fieldtype"], "Data")
        self.assertGreaterEqual(res["value"], 0)

    def test_approved_expense_claims_count_no_board_returns_zero(self):
        user = self._make_privileged_non_board_user()
        with self._as_user(user.name):
            res = chapter_dashboard_api.get_approved_expense_claims_count()
        self.assertEqual(res["value"], 0)

    def test_volunteer_expenses_count_handles_archived_doctype(self):
        """Volunteer Expense was archived on migrated sites; the endpoint must
        return 0 rather than raising 'Unknown table'."""
        res = chapter_dashboard_api.get_volunteer_expenses_count(self.chapter.name)
        self.assertEqual(res["fieldtype"], "Data")
        self.assertGreaterEqual(res["value"], 0)

    def test_volunteer_expenses_count_no_board_returns_zero(self):
        # Only reaches the no-board branch if the DocType still exists.
        if not frappe.db.exists("DocType", "Volunteer Expense"):
            res = chapter_dashboard_api.get_volunteer_expenses_count()
            self.assertEqual(res["value"], 0)
            return
        user = self._make_privileged_non_board_user()
        with self._as_user(user.name):
            res = chapter_dashboard_api.get_volunteer_expenses_count()
        self.assertEqual(res["value"], 0)


class TestChapterDashboardReprocessMT940(_ChapterDashboardBase):
    """reprocess_mt940_import error path (no live banking)."""

    def test_reprocess_nonexistent_import_returns_error(self):
        self.expectErrorLog()
        result = chapter_dashboard_api.reprocess_mt940_import(f"NO-SUCH-IMPORT-{self.uid}")
        self.assertFalse(result.get("success"))
        self.assertIn("error", result)
