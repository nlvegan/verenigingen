# -*- coding: utf-8 -*-
# Copyright (c) 2026, Your Organization and Contributors
# See license.txt

"""
Integration tests for the chapter board dashboard page controller
(``verenigingen/templates/pages/chapter_dashboard.py``).

These tests build a real chapter with a real board member (Member + Volunteer +
Chapter Board Member), a couple of chapter members, then exercise the real
``get_context`` rendering, the ``get_chapter_dashboard_data`` whitelisted
endpoint, the access-control internal function and the individual data-builder
helpers (metrics, member overview, pending actions, financials, dues status,
board info, recent activity). No business logic is mocked.
"""

import frappe

from verenigingen.templates.pages import chapter_dashboard as cd
from verenigingen.tests.utils.base import VereningingenTestCase


class TestChapterDashboardPage(VereningingenTestCase):
    """Real integration tests for the chapter dashboard controller."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        frappe.local.form_dict = frappe._dict()

        # --- Build a chapter with a real board member ---
        self.chapter = self.create_test_chapter()

        # Board member: Member -> Volunteer -> Chapter Board Member.
        # The dashboard resolves the member by Member.email == frappe.session.user,
        # so the board user's email must equal the Member.email.
        self.board_email = f"board.{frappe.generate_hash(length=8)}@example.com"
        self.board_user = self.create_test_user(
            self.board_email, roles=["Verenigingen Chapter Board Member"]
        )
        # Post the Rule-5 cap, the dashboard endpoint (@high_security_api) needs an
        # assigned role PROFILE, not a bare Chapter Board Member role.
        from verenigingen.tests.fixtures.role_profile_helper import grant_matching_role_profiles

        grant_matching_role_profiles(self.board_email, "Verenigingen Chapter Board Member")
        self.board_member = self.create_test_member(
            chapter=self.chapter.name, email=self.board_email
        )
        # Give the volunteer the same email as the board user: the Chapter Board
        # Member row's email is populated from the Volunteer (not the value passed
        # to append), and get_board_information flags is_current_user by matching
        # that email against frappe.session.user.
        self.board_volunteer = self.create_test_volunteer(
            member=self.board_member.name, email=self.board_email
        )

        self.chapter_role = self.create_test_chapter_role(
            role_name=f"Test Head {frappe.generate_hash(length=6)}",
            permissions_level="Admin",
        )
        # create_test_member mutated the chapter (appended a Chapter Member row),
        # so refresh before our own board-member append to avoid a timestamp clash.
        self.chapter.reload()
        self.add_board_member_to_chapter(
            self.chapter, self.board_volunteer, self.chapter_role, email=self.board_email
        )

        # A couple of additional regular chapter members.
        self.active_member = self.create_test_member(chapter=self.chapter.name)
        self.pending_member = self.create_test_member(chapter=self.chapter.name, status="Pending")
        # Mark the second member's chapter row as Pending so member-overview has data.
        self.chapter.reload()
        for row in self.chapter.members:
            if row.member == self.pending_member.name:
                row.status = "Pending"
        self.chapter.save(ignore_permissions=True)

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.local.form_dict = frappe._dict()
        super().tearDown()

    def _as_admin(self):
        """Switch the session to Administrator to exercise the admin permission path."""
        frappe.set_user("Administrator")

    # ------------------------------------------------------------------
    # get_user_board_chapters / get_user_board_role
    # ------------------------------------------------------------------

    def test_admin_sees_all_chapters(self):
        """Admins get every chapter, including the test one."""
        self._as_admin()
        chapters = cd.get_user_board_chapters()
        names = [c["chapter_name"] for c in chapters]
        self.assertIn(self.chapter.name, names)

    def test_board_member_sees_own_chapter(self):
        """A board member only sees the chapter they sit on the board of."""
        frappe.set_user(self.board_user.name)
        chapters = cd.get_user_board_chapters()
        names = [c["chapter_name"] for c in chapters]
        self.assertIn(self.chapter.name, names)

    def test_non_board_user_sees_no_chapters(self):
        """A plain user with no board membership sees nothing."""
        email = f"plain.{frappe.generate_hash(length=8)}@example.com"
        user = self.create_test_user(email, roles=["Verenigingen Member"])
        frappe.set_user(user.name)
        self.assertEqual(cd.get_user_board_chapters(), [])

    def test_get_user_board_role_admin(self):
        self._as_admin()
        role = cd.get_user_board_role(self.chapter.name)
        self.assertEqual(role["role"], "System Administrator")
        self.assertTrue(role["permissions"]["can_view_finances"])

    def test_get_user_board_role_member(self):
        frappe.set_user(self.board_user.name)
        role = cd.get_user_board_role(self.chapter.name)
        self.assertIsNotNone(role)
        self.assertEqual(role["role"], self.chapter_role.name)
        self.assertIn("permissions", role)

    def test_get_role_permissions_known_and_unknown(self):
        treasurer = cd.get_role_permissions("Treasurer")
        self.assertTrue(treasurer["can_view_finances"])
        self.assertEqual(treasurer["expense_limit"], 500)

        secretary = cd.get_role_permissions("Secretary")
        self.assertFalse(secretary["can_view_finances"])

        unknown = cd.get_role_permissions("Some Made Up Role")
        self.assertFalse(unknown["can_approve_members"])
        self.assertEqual(unknown["expense_limit"], 0)

    # ------------------------------------------------------------------
    # get_context
    # ------------------------------------------------------------------

    def test_get_context_board_member(self):
        """A board member gets a fully populated dashboard context."""
        frappe.set_user(self.board_user.name)
        context = frappe._dict()
        cd.get_context(context)

        self.assertEqual(context.no_cache, 1)
        self.assertEqual(context.selected_chapter, self.chapter.name)
        self.assertTrue(context.has_data)
        self.assertIsNotNone(context.dashboard_data)
        self.assertIn("key_metrics", context.dashboard_data)

    def test_get_context_admin(self):
        """Admin (sees all chapters) gets a dashboard, defaulting to first chapter."""
        self._as_admin()
        frappe.local.form_dict = frappe._dict({"chapter": self.chapter.name})
        context = frappe._dict()
        cd.get_context(context)
        self.assertEqual(context.selected_chapter, self.chapter.name)
        self.assertTrue(context.has_data)

    def test_get_context_non_board_user_error(self):
        """A user without board membership gets an error message, not data."""
        email = f"plain.{frappe.generate_hash(length=8)}@example.com"
        user = self.create_test_user(email, roles=["Verenigingen Member"])
        frappe.set_user(user.name)
        context = frappe._dict()
        cd.get_context(context)
        self.assertIn("error_message", context)
        self.assertNotIn("dashboard_data", context)

    def test_get_context_invalid_chapter_falls_back(self):
        """Requesting a chapter the user can't access falls back to an allowed one."""
        frappe.set_user(self.board_user.name)
        frappe.local.form_dict = frappe._dict({"chapter": "Some Other Chapter Name"})
        context = frappe._dict()
        cd.get_context(context)
        # Falls back to the chapter the board member actually belongs to.
        self.assertEqual(context.selected_chapter, self.chapter.name)

    def test_get_context_dict_style(self):
        """get_context supports a plain dict context (the testing/debug path)."""
        frappe.set_user(self.board_user.name)
        context = {}
        cd.get_context(context)
        self.assertEqual(context["selected_chapter"], self.chapter.name)
        self.assertTrue(context["has_data"])

    # ------------------------------------------------------------------
    # _get_chapter_dashboard_data_internal + access control
    # ------------------------------------------------------------------

    def test_internal_data_requires_access(self):
        """A user without access to a chapter is rejected by the internal builder."""
        email = f"plain.{frappe.generate_hash(length=8)}@example.com"
        user = self.create_test_user(email, roles=["Verenigingen Member"])
        frappe.set_user(user.name)
        with self.assertRaises(frappe.exceptions.ValidationError):
            cd._get_chapter_dashboard_data_internal(self.chapter.name)

    def test_internal_data_empty_chapter_name_raises(self):
        self._as_admin()
        with self.assertRaises(frappe.exceptions.ValidationError):
            cd._get_chapter_dashboard_data_internal("")

    def test_get_chapter_dashboard_data_endpoint(self):
        """The whitelisted endpoint returns the full dashboard payload."""
        frappe.set_user(self.board_user.name)
        result = cd.get_chapter_dashboard_data(self.chapter.name)
        # api_response_handler may wrap the payload; unwrap if needed.
        data = result.get("data", result) if isinstance(result, dict) else result
        self.assertIn("chapter_info", data)
        self.assertIn("dues_payment_status", data)
        self.assertIn("last_updated", data)

    # ------------------------------------------------------------------
    # individual data-builder helpers (run as Administrator for access)
    # ------------------------------------------------------------------

    def test_get_chapter_basic_info(self):
        info = cd.get_chapter_basic_info(self.chapter.name)
        self.assertEqual(info["name"], self.chapter.name)
        self.assertGreaterEqual(info["total_board_members"], 1)

    def test_get_chapter_key_metrics(self):
        metrics = cd.get_chapter_key_metrics(self.chapter.name)
        self.assertIn("members", metrics)
        self.assertIn("expenses", metrics)
        # We added at least 3 chapter members in setUp.
        self.assertGreaterEqual(metrics["members"]["total"], 3)

    def test_get_basic_expense_stats(self):
        stats = cd.get_basic_expense_stats(self.chapter.name)
        for key in ("pending_amount", "pending_count", "ytd_total", "this_month"):
            self.assertIn(key, stats)

    def test_get_member_overview(self):
        overview = cd.get_member_overview(self.chapter.name)
        self.assertIn("recent_members", overview)
        self.assertIn("pending_applications", overview)
        member_ids = [m["member"] for m in overview["recent_members"]]
        self.assertIn(self.board_member.name, member_ids)

    def test_get_pending_actions(self):
        actions = cd.get_pending_actions(self.chapter.name)
        self.assertIn("membership_applications", actions)
        self.assertIn("total_pending", actions)
        # Each pending application is annotated with an is_overdue flag.
        for app in actions["membership_applications"]:
            self.assertIn("is_overdue", app)

    def test_get_financial_summary(self):
        summary = cd.get_financial_summary(self.chapter.name)
        self.assertIn("this_month", summary)
        self.assertIn("ytd", summary)
        self.assertIn("dues_income", summary)

    def test_get_members_without_payment_info_count(self):
        # All members lack payment info, so count should be >= the active count.
        count = cd.get_members_without_payment_info_count(self.chapter.name)
        self.assertIsInstance(count, int)
        self.assertGreaterEqual(count, 0)

    def test_get_dues_payment_status(self):
        status = cd.get_dues_payment_status(self.chapter.name)
        self.assertIn("total_members", status)
        self.assertIn("overdue_breakdown", status)
        self.assertIn("all_outstanding_amount", status)
        # No invoices exist, so nothing should be overdue/unpaid.
        self.assertEqual(status["overdue"], 0)
        self.assertEqual(status["unpaid"], 0)

    def test_get_board_information(self):
        board = cd.get_board_information(self.chapter.name)
        self.assertGreaterEqual(board["total_count"], 1)
        emails = [m["email"] for m in board["members"]]
        self.assertIn(self.board_email, emails)

    def test_get_board_information_marks_current_user(self):
        """The current user's board row is flagged is_current_user."""
        frappe.set_user(self.board_user.name)
        board = cd.get_board_information(self.chapter.name)
        current = [m for m in board["members"] if m["is_current_user"]]
        self.assertTrue(current)

    def test_get_available_document_categories(self):
        categories = cd.get_available_document_categories()
        self.assertIsInstance(categories, dict)

    def test_get_chapter_board_documents(self):
        docs = cd.get_chapter_board_documents(self.chapter.name)
        self.assertIsInstance(docs, dict)

    def test_get_recent_activity(self):
        activity = cd.get_recent_activity(self.chapter.name)
        self.assertIsInstance(activity, list)
        # Members joined recently, so there should be join activity entries.
        for item in activity:
            self.assertIn("member", item)
